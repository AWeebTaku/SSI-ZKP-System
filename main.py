"""Start the local SSI/ZKP demo with one command.

Usage:
    python main.py

The launcher starts Ganache when no EVM node is already reachable, deploys
the contract, and then starts the FastAPI application. Press Ctrl+C to stop
the application and any Ganache process started by this script.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
DEFAULT_GANACHE_URL = "http://127.0.0.1:8545"
DEFAULT_APP_HOST = "0.0.0.0"
DEFAULT_APP_PORT = 8000
GANACHE_START_TIMEOUT = 30


def _rpc_endpoint(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Invalid GANACHE_URL: {url}")
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def chain_is_reachable(url: str) -> bool:
    """Return whether the configured JSON-RPC endpoint responds to eth_chainId."""
    payload = json.dumps(
        {"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1}
    ).encode("utf-8")
    request = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=2) as response:
            result = json.loads(response.read().decode("utf-8"))
            return bool(result.get("result"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def wait_for_chain(url: str, timeout: int = GANACHE_START_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if chain_is_reachable(url):
            return
        time.sleep(0.5)
    raise RuntimeError(
        f"Ganache did not become reachable at {url} within {timeout} seconds."
    )


def start_ganache(url: str) -> subprocess.Popen:
    hostname, port = _rpc_endpoint(url)
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        raise RuntimeError(
            "npx is required to start Ganache. Install Node.js/npm or start Ganache manually."
        )

    command = [
        npx,
        "--yes",
        "ganache",
        "--deterministic",
        "--host",
        hostname,
        "--port",
        str(port),
    ]
    print(f"[main] Starting Ganache at {url} ...", flush=True)
    return subprocess.Popen(
        command,
        cwd=BASE_DIR,
        start_new_session=True,
    )


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def deploy_contract(environment: dict[str, str]) -> None:
    print("[main] Compiling and deploying DidRegistry.sol ...", flush=True)
    subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "deploy.py")],
        cwd=BASE_DIR,
        env=environment,
        check=True,
    )


def run_backend(environment: dict[str, str], host: str, port: int) -> int:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    print(f"[main] Starting backend at http://127.0.0.1:{port}/", flush=True)
    process = subprocess.Popen(command, cwd=BASE_DIR, env=environment)
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        return process.wait()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_APP_HOST, help="FastAPI bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_APP_PORT, help="FastAPI port")
    parser.add_argument(
        "--ganache-url",
        default=os.environ.get("GANACHE_URL", DEFAULT_GANACHE_URL),
        help="Ganache JSON-RPC URL",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Use the existing build/deployment.json instead of deploying again",
    )
    parser.add_argument(
        "--no-ganache",
        action="store_true",
        help="Require an already-running Ganache instance",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    environment = os.environ.copy()
    environment["GANACHE_URL"] = args.ganache_url
    ganache_process = None

    try:
        if chain_is_reachable(args.ganache_url):
            print(f"[main] Ganache is already reachable at {args.ganache_url}.", flush=True)
        elif args.no_ganache:
            raise RuntimeError(
                f"No Ganache instance is reachable at {args.ganache_url}."
            )
        else:
            ganache_process = start_ganache(args.ganache_url)
            wait_for_chain(args.ganache_url)

        if not args.skip_deploy:
            deploy_contract(environment)
        elif not os.path.exists(os.path.join(BASE_DIR, "build", "deployment.json")):
            raise RuntimeError("--skip-deploy requires build/deployment.json to exist.")

        return run_backend(environment, args.host, args.port)
    finally:
        if ganache_process is not None and ganache_process.poll() is None:
            print("[main] Stopping Ganache ...", flush=True)
            stop_process(ganache_process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[main] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)