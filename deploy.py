"""
Deployment Engine
=================
Compiles contracts/DidRegistry.sol with py-solc-x and deploys it to a local
EVM ledger (Ganache, default http://127.0.0.1:8545). Exports the ABI and
bytecode to build/, and writes build/deployment.json with the deployed
contract address so the FastAPI backend can pick it up.

Usage:
    python deploy.py
"""

import json
import os

from solcx import compile_standard, get_installed_solc_versions, install_solc, set_solc_version
from web3 import Web3
from dotenv import load_dotenv

SOLC_VERSION = "0.8.19"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
GANACHE_URL = os.environ.get("GANACHE_URL", "http://127.0.0.1:8545")

CONTRACT_PATH = os.path.join(BASE_DIR, "contracts", "DidRegistry.sol")
BUILD_DIR = os.path.join(BASE_DIR, "build")


def compile_contract() -> dict:
    if SOLC_VERSION not in {str(version) for version in get_installed_solc_versions()}:
        print(f"[deploy] Installing solc {SOLC_VERSION} ...")
        install_solc(SOLC_VERSION)
    print(f"[deploy] Selecting solc {SOLC_VERSION} ...")
    set_solc_version(SOLC_VERSION)

    with open(CONTRACT_PATH, "r", encoding="utf-8") as f:
        source = f.read()

    print("[deploy] Compiling DidRegistry.sol ...")
    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {"DidRegistry.sol": {"content": source}},
            "settings": {
                "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
                "optimizer": {"enabled": True, "runs": 200},
            },
        },
        solc_version=SOLC_VERSION,
    )

    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(os.path.join(BUILD_DIR, "compiled.json"), "w", encoding="utf-8") as f:
        json.dump(compiled, f, indent=2)

    return compiled


def deploy() -> dict:
    compiled = compile_contract()
    contract_data = compiled["contracts"]["DidRegistry.sol"]["DidRegistry"]
    abi = contract_data["abi"]
    bytecode = contract_data["evm"]["bytecode"]["object"]

    with open(os.path.join(BUILD_DIR, "DidRegistry.abi.json"), "w", encoding="utf-8") as f:
        json.dump(abi, f, indent=2)
    with open(os.path.join(BUILD_DIR, "DidRegistry.bytecode.txt"), "w", encoding="utf-8") as f:
        f.write(bytecode)
    print(f"[deploy] ABI and bytecode exported to {BUILD_DIR}/")

    print(f"[deploy] Connecting to EVM ledger at {GANACHE_URL} ...")
    w3 = Web3(Web3.HTTPProvider(GANACHE_URL))
    if not w3.is_connected():
        raise RuntimeError(
            f"Could not connect to {GANACHE_URL}. Start Ganache or run `python main.py`."
        )

    accounts = w3.eth.accounts
    if not accounts:
        raise RuntimeError(f"No funded accounts were returned by {GANACHE_URL}.")

    deployer = accounts[0]
    w3.eth.default_account = deployer
    print(f"[deploy] Deploying from account: {deployer}")

    DidRegistry = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = DidRegistry.constructor().transact({"from": deployer})
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    contract_address = tx_receipt.contractAddress
    print(f"[deploy] DidRegistry deployed at: {contract_address}")
    print(f"[deploy] Tx hash: {tx_hash.hex()}  Block: {tx_receipt.blockNumber}")

    deployment_info = {
        "address": contract_address,
        "abi": abi,
        "deployer": deployer,
        "tx_hash": tx_hash.hex(),
        "block_number": tx_receipt.blockNumber,
        "ganache_url": GANACHE_URL,
    }

    deployment_path = os.path.join(BUILD_DIR, "deployment.json")
    with open(deployment_path, "w", encoding="utf-8") as f:
        json.dump(deployment_info, f, indent=2)
    print(f"[deploy] Deployment record written to {deployment_path}")

    return deployment_info


if __name__ == "__main__":
    info = deploy()
    print("\n[deploy] Done. Summary:")
    print(json.dumps({k: v for k, v in info.items() if k != "abi"}, indent=2))
