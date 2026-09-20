"""
Backend Controller
===================
FastAPI application implementing the Verifier/Issuer/Holder tripartite flow
on top of the DidRegistry smart contract.

Run from the project root:
    python -m uvicorn backend.main:app --reload --port 8000
"""

import datetime
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend import chain, crypto_utils, storage

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ISSUER_DID = os.environ.get("ISSUER_DID", "did:ssi:issuer:national-visa-authority")
ISSUER_HMAC_SECRET = os.environ.get(
    "ISSUER_HMAC_SECRET", "dev-only-insecure-issuer-secret-change-me"
).encode("utf-8")
DEFAULT_HOLDER_DID = os.environ.get("DEFAULT_HOLDER_DID", "did:ssi:holder:demo-traveler")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Best-effort: register the issuer DID on-chain at startup if reachable.
    try:
        if not chain.did_exists(ISSUER_DID):
            pubkey_hex = crypto_utils.sign_credential(ISSUER_HMAC_SECRET, "issuer-genesis-key")
            chain.register_did(ISSUER_DID, pubkey_hex)
            print(f"[startup] Registered issuer DID on-chain: {ISSUER_DID}")
    except chain.ChainNotReady as exc:
        print(f"[startup] Chain not ready, skipping issuer DID bootstrap: {exc}")
    except Exception as exc:
        print(f"[startup] Issuer DID bootstrap skipped: {exc}")
    yield


app = FastAPI(title="SSI / ZKP Cross-Border Travel Verification System", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def _chain_status() -> dict:
    try:
        connected = chain.get_w3().is_connected()
    except Exception:
        connected = False
    deployed = os.path.exists(chain.DEPLOYMENT_FILE)
    return {"connected": connected, "deployed": deployed}


# ---------------------------------------------------------------------------
# Frontend Views (Navigation Hub + three dashboards)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "chain": _chain_status()})


@app.get("/issuer", response_class=HTMLResponse)
def issuer_console(request: Request):
    registry = storage.read_registry()
    issued = [v for v in registry.values() if v.get("issuer_did") == ISSUER_DID]
    issued.sort(key=lambda r: r.get("issued_at", ""), reverse=True)
    return templates.TemplateResponse(
        "issuer.html",
        {"request": request, "chain": _chain_status(), "issuer_did": ISSUER_DID, "issued": issued},
    )


@app.get("/wallet", response_class=HTMLResponse)
def traveler_wallet(request: Request, did: str = DEFAULT_HOLDER_DID):
    wallets = storage.read_wallets()
    credentials = list(reversed(wallets.get(did, [])))
    return templates.TemplateResponse(
        "wallet.html",
        {"request": request, "chain": _chain_status(), "holder_did": did, "credentials": credentials},
    )


@app.get("/customs", response_class=HTMLResponse)
def customs_portal(request: Request):
    return templates.TemplateResponse("customs.html", {"request": request, "chain": _chain_status()})


# ---------------------------------------------------------------------------
# API: DID registration (general-purpose, backs registerDid on the contract)
# ---------------------------------------------------------------------------

@app.post("/register-did")
def register_did_endpoint(did: str = Form(...), public_key_hex: str = Form(...)):
    try:
        if chain.did_exists(did):
            return JSONResponse({"status": "exists", "did": did})
        tx_info = chain.register_did(did, public_key_hex)
        return JSONResponse({"status": "registered", "did": did, **tx_info})
    except chain.ChainNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# API: Issuance
# ---------------------------------------------------------------------------

@app.post("/issue-visa")
def issue_visa(
    holder_did: str = Form(...),
    traveler_name: str = Form(...),
    passport_number: str = Form(...),
    nationality: str = Form(...),
    visa_status: str = Form("VALID"),
    validity_days: int = Form(90),
):
    """
    Signs traveler data with the issuer's HMAC-SHA256 key, anchors an opaque
    credential-hash commitment on-chain via DidRegistry.anchorCredential, and
    writes the full credential (including the blinding salt) to holder wallet
    storage only.
    """
    try:
        registry = storage.read_registry()
        if any(
            record.get("holder_did") == holder_did and not record.get("revoked", False)
            for record in registry.values()
        ):
            raise HTTPException(
                status_code=409,
                detail="Holder DID already has an active credential",
            )

        if not chain.did_exists(holder_did):
            placeholder_key = crypto_utils.generate_salt(32)
            chain.register_did(holder_did, placeholder_key)

        credential_id = f"vc-{crypto_utils.generate_salt(8)}"
        salt = crypto_utils.generate_salt(16)
        commitment = crypto_utils.compute_commitment(visa_status, salt)

        issued_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        expiry_at = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=validity_days)
        ).isoformat().replace("+00:00", "Z")

        message = crypto_utils.canonical_message(
            credential_id, holder_did, ISSUER_DID, commitment, issued_at, expiry_at
        )
        signature = crypto_utils.sign_credential(ISSUER_HMAC_SECRET, message)

        credential_hash = chain.credential_hash_bytes32(credential_id, commitment)
        tx_info = chain.anchor_credential(ISSUER_DID, credential_hash)

        # Holder-owned record: full plaintext, lives ONLY in wallet storage.
        wallet_record = {
            "credential_id": credential_id,
            "issuer_did": ISSUER_DID,
            "holder_did": holder_did,
            "traveler_name": traveler_name,
            "passport_number": passport_number,
            "nationality": nationality,
            "visa_status": visa_status,
            "issued_at": issued_at,
            "expiry_at": expiry_at,
            "salt": salt,
            "commitment": commitment,
            "signature": signature,
            "credential_hash": credential_hash.hex(),
            "anchor_tx": tx_info["tx_hash"],
        }
        wallets = storage.read_wallets()
        wallets.setdefault(holder_did, []).append(wallet_record)
        storage.write_wallets(wallets)

        # Verifier/issuer-facing record: NO PII, NO salt.
        registry[credential_id] = {
            "credential_id": credential_id,
            "issuer_did": ISSUER_DID,
            "holder_did": holder_did,
            "commitment": commitment,
            "credential_hash": credential_hash.hex(),
            "signature": signature,
            "issued_at": issued_at,
            "expiry_at": expiry_at,
            "anchor_tx": tx_info["tx_hash"],
            "revoked": False,
        }
        storage.write_registry(registry)

        return JSONResponse(
            {
                "status": "issued",
                "credential_id": credential_id,
                "credential_hash": credential_hash.hex(),
                "anchor_tx": tx_info["tx_hash"],
                "commitment": commitment,
                "note": "Salt and raw traveler data persisted only in holder wallet storage; "
                        "the registry (verifier-facing) holds only the commitment and hash.",
            }
        )
    except HTTPException:
        raise
    except chain.ChainNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# API: Revocation
# ---------------------------------------------------------------------------

@app.post("/revoke-visa")
def revoke_visa(credential_id: str = Form(...)):
    """Writes a revocation transaction directly to DidRegistry.sol."""
    try:
        registry = storage.read_registry()
        record = registry.get(credential_id)
        if not record:
            raise HTTPException(status_code=404, detail="Unknown credential_id")

        credential_hash = bytes.fromhex(record["credential_hash"].replace("0x", ""))
        tx_info = chain.revoke_credential(record["issuer_did"], credential_hash)

        record["revoked"] = True
        record["revoke_tx"] = tx_info["tx_hash"]
        registry[credential_id] = record
        storage.write_registry(registry)

        wallets = storage.read_wallets()
        for cred in wallets.get(record["holder_did"], []):
            if cred["credential_id"] == credential_id:
                cred["visa_status"] = "REVOKED"
        storage.write_wallets(wallets)

        return JSONResponse(
            {"status": "revoked", "credential_id": credential_id, "revoke_tx": tx_info["tx_hash"]}
        )
    except HTTPException:
        raise
    except chain.ChainNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# API: Border verification (blinded hash-commitment check)
# ---------------------------------------------------------------------------

@app.post("/verify-border")
def verify_border(
    credential_id: str = Form(...),
    claimed_status: str = Form(...),
    proof_hash: str = Form(...),
):
    """
    Checks on-chain revocation state via isRevoked() and validates a blinded
    selective-disclosure proof (SHA256(claimed_status || salt), computed
    client-side in the traveler's wallet) against the issuer's commitment.

    No raw PII, and no salt, is ever received or persisted by this endpoint --
    only credential_id, the asserted status label, and the opaque proof hash.
    """
    try:
        registry = storage.read_registry()
        record = registry.get(credential_id)

        result = {
            "credential_id": credential_id,
            "claimed_status": claimed_status,
            "proof_valid": False,
            "anchored": False,
            "revoked": None,
            "expired": None,
            "verified": False,
            "reason": None,
        }

        if not record:
            result["reason"] = "Credential ID not found in registry."
            return JSONResponse(result, status_code=404)

        proof_valid = crypto_utils.safe_hash_eq(proof_hash, record["commitment"])
        credential_hash = bytes.fromhex(record["credential_hash"].replace("0x", ""))
        anchored_onchain = chain.is_anchored(credential_hash)
        revoked_onchain = chain.is_revoked(credential_hash)

        expired = False
        try:
            expiry = datetime.datetime.fromisoformat(record["expiry_at"].replace("Z", ""))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=datetime.timezone.utc)
            expired = datetime.datetime.now(datetime.timezone.utc) > expiry
        except Exception:
            pass

        result.update(
            {
                "proof_valid": proof_valid,
                "anchored": anchored_onchain,
                "revoked": revoked_onchain,
                "expired": expired,
                "expiry_at": record.get("expiry_at"),
            }
        )

        if not anchored_onchain:
            result["reason"] = "Credential is not anchored on-chain."
        elif revoked_onchain:
            result["reason"] = "Credential has been revoked on-chain."
        elif expired:
            result["reason"] = "Credential has expired."
        elif not proof_valid:
            result["reason"] = "Blinded proof does not match issuer commitment -- status assertion rejected."
        else:
            result["reason"] = "Zero-knowledge status assertion verified against on-chain state."

        result["verified"] = bool(proof_valid and anchored_onchain and not revoked_onchain and not expired)

        # Only the verification outcome would be audit-logged in production --
        # deliberately nothing PII-bearing is written here.
        return JSONResponse(result)
    except chain.ChainNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))
