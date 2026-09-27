# SSI / ZKP Cross-Border Travel Verification System

A working demo of a **tripartite trust model** (Issuer &rarr; Holder/Wallet &rarr;
Verifier/Customs) anchored to an EVM smart contract acting as a **Verifiable
Data Registry**.

```
contracts/DidRegistry.sol   Solidity ^0.8.0 registry: DID<->pubkey, revocation ledger
deploy.py                   Web3.py deployment engine (compiles + deploys to Ganache)
backend/                    FastAPI controller (issue / revoke / verify) + chain + crypto + storage
templates/                  Jinja2 + Tailwind dashboards (issuer, wallet, customs, hub)
static/                     Static assets
storage/                    Runtime JSON stores (wallets.json, registry.json) -- created automatically
build/                      Compiled ABI/bytecode + deployment.json -- created by deploy.py
```

## 1. Architecture summary

| Party | Component | Responsibility |
|---|---|---|
| Issuer | `/issuer` | Signs traveler data (HMAC-SHA256), anchors a commitment hash on-chain, never exposes salts |
| Holder | `/wallet` | Stores the full credential (incl. blinding salt) locally, computes disclosure proofs **in-browser** |
| Verifier | `/customs` | Checks `isRevoked()` on-chain and validates the blinded proof -- never touches raw PII or the salt |
| Registry | `DidRegistry.sol` | On-chain source of truth for DID ownership and credential revocation state |

**Selective disclosure / blinding scheme:** at issuance, the issuer picks a
random salt and commits to `commitment = SHA256(status || salt)`. Only the
holder ever learns the salt. To prove a status claim at the border, the
wallet computes `proof = SHA256(claimed_status || salt)` **client-side**
(Web Crypto `SubtleCrypto`) and sends only `{credential_id, claimed_status,
proof}` to Customs. The verifier checks `proof == commitment` from the
registry and `isRevoked()` on-chain; it never receives the salt or raw PII.

> **Design note on HMAC-SHA256:** HMAC is a symmetric MAC, so true
> verification requires the issuer's secret key. This project uses it because
> it was specified as the signing primitive; in a production SSI system you
> would use an asymmetric scheme (ECDSA/EdDSA) so the Verifier can check
> signatures with only a public key. Here, the Customs verification path
> deliberately relies only on the on-chain revocation state and the blinded
> commitment match -- not on re-checking the HMAC signature -- so the
> Verifier never needs the issuer's secret.

## 2. Setup on Windows, macOS, or Linux

### 2.1 Install prerequisites

This project is tested against **Python 3.11-3.13** and **Node.js 20 LTS**.
Avoid Python 3.14 for now -- two dependencies with native extensions
(`pydantic-core`, via Rust/PyO3, and `ckzg`, via a C extension) don't
reliably have prebuilt wheels for 3.14 yet on every platform, which forces
a from-source build that fails outright on a machine without a C/C++
toolchain (most commonly Windows -- see Troubleshooting). If a supported
version isn't already installed, use the commands for your OS below.

**Arch Linux:** `pacman`'s `python` package tracks upstream releases
closely and may already be newer than 3.13 -- check with `python
--version` before assuming it's fine. If it's too new, install a pinned
version with `pyenv` (in the official `extra` repo) rather than fighting
the system package:

```bash
sudo pacman -S pyenv git base-devel nodejs npm
pyenv install 3.12.8
pyenv local 3.12.8   # run from the project root; writes a .python-version file
```

**Debian / Ubuntu:**

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip nodejs npm git
```

If `python3.12` isn't available in your release's repos, install it via
the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa)
(Ubuntu) or with `pyenv`'s official installer: `curl https://pyenv.run | bash`.

**Fedora:**

```bash
sudo dnf install python3.12 nodejs npm git
```

**macOS (Homebrew):**

```bash
brew install pyenv node@20 git
pyenv install 3.12.8
pyenv local 3.12.8   # run from the project root
```

**Windows:** download the Python 3.12.x installer from
[python.org/downloads](https://www.python.org/downloads/) -- on the first
setup screen, check **"Add python.exe to PATH"** -- and the Node.js 20 LTS
installer from [nodejs.org](https://nodejs.org/). Both coexist fine
alongside any other Python/Node versions already on the machine; nothing
needs to be uninstalled, since the next step targets the right one
explicitly with the `py` launcher.

Then verify you're pointed at a supported version:

```text
python --version
node --version
```

On Windows, if `python --version` doesn't show 3.12.x (e.g. 3.14 is your
default), use `py -3.12 --version` instead -- the `py` launcher can target
a specific installed version without changing your system default.

### 2.2 Create a Python environment

Create the environment once, using the interpreter version confirmed
above rather than a bare `python` that might resolve to something newer
than this project supports:

Windows:

```powershell
py -3.12 -m venv .venv
```

macOS/Linux:

```bash
python3.12 -m venv .venv
```

(If you installed Python via `pyenv` and ran `pyenv local 3.12.8` in 2.1,
plain `python3.12 -m venv .venv` -- or even `python -m venv .venv` -- will
already resolve to the right version automatically.)

Activate it for the current terminal session:

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```bat
.venv\Scripts\activate.bat
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install the Python dependencies:

```text
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2.3 Install the local EVM ledger

Install the project-local Node dependency from the project root:

```text
npm install
```

The launcher uses this local Ganache installation; a global install and
administrator privileges are not required.

### 2.4 Configure environment variables

Copy `.env.example` to `.env` using your file manager, or use the command for
your shell:

Windows PowerShell: `Copy-Item .env.example .env`

Windows Command Prompt: `copy .env.example .env`

macOS/Linux: `cp .env.example .env`

The application loads `.env` automatically. Change `ISSUER_HMAC_SECRET` before
using the demo outside a disposable local environment.

### 2.5 Start everything with one command

```text
python main.py
```

This starts Ganache if needed, waits for JSON-RPC, compiles and deploys the
contract, and starts FastAPI at `http://127.0.0.1:8000/`. Press `Ctrl+C` to
stop the server and any Ganache process started by the launcher.

Useful options:

```text
python main.py --port 8001
python main.py --ganache-url http://127.0.0.1:9545
python main.py --no-ganache
python main.py --skip-deploy
```

Use `--skip-deploy` only when the current Ganache instance still contains the
contract recorded in `build/deployment.json`. A fresh or restarted Ganache
instance requires the default deployment step again.

## 3. Manual commands (optional)

The one-command launcher is recommended. For manual operation, run Ganache
from the project root:

```text
npx ganache --deterministic --host 127.0.0.1 --port 8545
```

Leave it running, open a second terminal, activate the Python environment, and
run:

```text
python deploy.py
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

This will:
1. Compile `contracts/DidRegistry.sol` with solc 0.8.19.
2. Export `build/DidRegistry.abi.json` and `build/DidRegistry.bytecode.txt`.
3. Deploy the contract to Ganache and write `build/deployment.json`
   (contract address, ABI, deployer account, tx hash).

Expected output ends with something like:
```
[deploy] DidRegistry deployed at: 0xA1b2C3...
[deploy] Done. Summary: { "address": "0x...", "deployer": "0x...", ... }
```

## 4. Run the backend

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

On startup the backend automatically registers the issuer DID
(`did:ssi:issuer:national-visa-authority` by default) on-chain if it isn't
registered yet.

Open http://127.0.0.1:8000/ for the navigation hub.

## 5. End-to-end verification flow

### Step A -- Issue a visa credential
1. Go to **http://127.0.0.1:8000/issuer**.
2. Fill in holder DID (default `did:ssi:holder:demo-traveler` is fine),
   traveler name, passport number, nationality, and pick `VALID`.
3. Click **Sign & Anchor Credential**. You'll see a JSON response with the
   `credential_id`, `credential_hash`, and the on-chain `anchor_tx` hash.
   The issued credential appears in the right-hand panel as `ACTIVE`.

### Step B -- Inspect the wallet & generate a disclosure proof
1. Go to **http://127.0.0.1:8000/wallet** (same holder DID).
2. Expand "Show blinding entropy factor" to see the random salt -- this
   never leaves the browser except when you choose to use it below.
3. Choose "Assert status" = `VALID` and click **Compute proof
   (client-side)**. This runs `SHA256(status + salt)` via the Web Crypto API
   in your browser and displays `credential_id`, `claimed_status`, and
   `proof_hash`.

### Step C -- Verify at the border
1. Go to **http://127.0.0.1:8000/customs**.
2. Paste the `credential_id`, `claimed_status`, and `proof_hash` from Step B.
3. Click **Verify against chain**. You should see **VERIFIED** with
   `proof_valid: true`, `anchored: true`, `revoked: false`.
4. Try changing `claimed_status` to something else (e.g. `DENIED`) without
  recomputing the proof. The commitment check still requires the original
  proof, but the server cannot independently bind the displayed label to the
  proof without learning the salt or running a real zero-knowledge protocol.

### Step D -- Revoke and re-verify
1. Back on **/issuer**, click **Revoke on-chain** next to the credential.
   This calls `DidRegistry.revokeCredential(...)` and the badge flips to
   `REVOKED`.
2. Re-run Step C with the same (still mathematically valid) proof. The
   result now shows **NOT VERIFIED**, `revoked: true`, confirming the
   verifier is checking live on-chain state and not a cached issuance
   record.

## 6. API reference (curl examples)

```bash
# Issue
curl -X POST http://127.0.0.1:8000/issue-visa \
  -F holder_did="did:ssi:holder:demo-traveler" \
  -F traveler_name="Jane Doe" \
  -F passport_number="X1234567" \
  -F nationality="IN" \
  -F visa_status="VALID" \
  -F validity_days=90

# Revoke
curl -X POST http://127.0.0.1:8000/revoke-visa \
  -F credential_id="vc-XXXXXXXX"

# Verify (proof_hash computed client-side as SHA256(status + salt))
curl -X POST http://127.0.0.1:8000/verify-border \
  -F credential_id="vc-XXXXXXXX" \
  -F claimed_status="VALID" \
  -F proof_hash="<sha256 hex digest>"

# Register an arbitrary DID
curl -X POST http://127.0.0.1:8000/register-did \
  -F did="did:ssi:holder:another-traveler" \
  -F public_key_hex="deadbeef"
```

## 7. Data boundaries (what is stored where)

- `storage/wallets.json` -- **holder-owned**. Full credential, including
  plaintext traveler PII and the blinding salt. This is the only place PII
  or salts are persisted.
- `storage/registry.json` -- **verifier/issuer-facing**. Only DIDs,
  commitments, credential hashes, signatures, and timestamps. No PII, no
  salts.
- `DidRegistry.sol` (on-chain) -- only DIDs, public keys, and opaque
  `keccak256` credential hashes. No PII, no commitments in plaintext.

## 8. Known limitations (read before treating this as production)

- **HMAC vs asymmetric signatures**: see the design note in Section 1 -- the
  Customs verifier deliberately does not re-check the HMAC signature (it
  would need the issuer's secret to do so). It relies solely on the on-chain
  `isRevoked()`/`isAnchored()` state and the blinded proof match.
- **Single-status commitment, not a general ZK circuit**: each credential
  commits to exactly one status value chosen at issuance. The `claimed_status`
  field submitted at `/verify-border` is not independently re-derived or
  cryptographically bound by the server (it has no salt to do so) -- the
  server can only check whether the supplied `proof_hash` matches the on-file
  commitment. This is a hash-commitment demonstration, not a zk-SNARK/zk-STARK circuit with
  range proofs or multi-attribute disclosure -- extending it to prove
  richer statements (e.g. "age > 18" without revealing birth date) would
  require an actual proving system such as circom/snarkjs or a Bulletproofs
  range proof.
- **Single-signer demo key management**: all on-chain transactions are sent
  from `accounts[0]` (the deployer) for simplicity, including issuer and
  holder DID registrations. A real deployment would give each issuer and
  holder their own keypair and have them sign their own transactions.
- **No rate limiting / auth** on the API endpoints -- add an auth layer
  before exposing this beyond localhost.

## 9. Troubleshooting

- **`ChainNotReady` / 503 errors**: Ganache isn't running or `deploy.py`
  hasn't been run yet. Start Ganache, then `python deploy.py`.
- **`DidRegistry: caller is not DID controller`**: the backend always
  transacts from the account recorded as `deployer` in
  `build/deployment.json`. If you restart Ganache (which resets all state
  and balances) you must re-run `python deploy.py` -- the previous
  `deployment.json` will point at a contract address that no longer exists.
- **Port already in use**: change `--port` for either `ganache` or
  `uvicorn`, and update `GANACHE_URL` accordingly.
- **`pip install` fails building `pydantic-core` or `ckzg`** (Rust/`cargo`
  or `'cl' is not recognized` errors): you're very likely on Python 3.14.
  Neither package reliably ships prebuilt wheels for 3.14 yet, so `pip`
  falls back to compiling from source -- which then needs a Rust
  toolchain PyO3 doesn't yet support that far, or (for `ckzg`) an MSVC
  compiler that a default Windows install doesn't have. This isn't a
  missing-tool problem you can install your way out of for the
  `pydantic-core` half; installing a supported Python version fixes both
  at once. See section 2.1 above for per-OS install commands, then
  recreate `.venv` with that version (section 2.2) and reinstall.
