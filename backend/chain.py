"""
Chain interaction layer.

Wraps the deployed DidRegistry contract (address + ABI loaded from
build/deployment.json, produced by deploy.py) with typed helper functions
used by the FastAPI controller.
"""

import json
import os

from web3 import Web3
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
BUILD_DIR = os.path.join(BASE_DIR, "build")
DEPLOYMENT_FILE = os.path.join(BUILD_DIR, "deployment.json")
GANACHE_URL = os.environ.get("GANACHE_URL", "http://127.0.0.1:8545")

_w3 = None
_contract = None
_deployment = None


class ChainNotReady(Exception):
    """Raised when the EVM ledger or deployed contract are not yet available."""


def get_w3() -> Web3:
    global _w3
    if _w3 is None:
        _w3 = Web3(Web3.HTTPProvider(GANACHE_URL))
    return _w3


def _load_deployment() -> dict:
    global _deployment
    if _deployment is None:
        if not os.path.exists(DEPLOYMENT_FILE):
            raise ChainNotReady(
                f"No deployment found at {DEPLOYMENT_FILE}. Run `python deploy.py` first "
                f"(with Ganache running at {GANACHE_URL})."
            )
        with open(DEPLOYMENT_FILE, "r", encoding="utf-8") as fh:
            _deployment = json.load(fh)
    return _deployment


def get_contract():
    global _contract
    if _contract is None:
        deployment = _load_deployment()
        w3 = get_w3()
        _contract = w3.eth.contract(
            address=Web3.to_checksum_address(deployment["address"]),
            abi=deployment["abi"],
        )
    return _contract


def get_default_account() -> str:
    w3 = get_w3()
    deployment = _load_deployment()
    account = deployment.get("deployer")
    if account:
        return Web3.to_checksum_address(account)
    return w3.eth.accounts[0]


def credential_hash_bytes32(credential_id: str, commitment: str) -> bytes:
    """keccak256(credentialId || ':' || commitment) -- the opaque on-chain reference."""
    return Web3.keccak(text=f"{credential_id}:{commitment}")


def register_did(did: str, public_key_hex: str) -> dict:
    w3 = get_w3()
    contract = get_contract()
    account = get_default_account()
    public_key_bytes = bytes.fromhex(public_key_hex.replace("0x", ""))
    tx_hash = contract.functions.registerDid(did, public_key_bytes).transact({"from": account})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return {"tx_hash": tx_hash.hex(), "block_number": receipt.blockNumber, "status": receipt.status}


def did_exists(did: str) -> bool:
    contract = get_contract()
    return contract.functions.didExists(did).call()


def anchor_credential(issuer_did: str, credential_hash: bytes) -> dict:
    w3 = get_w3()
    contract = get_contract()
    account = get_default_account()
    tx_hash = contract.functions.anchorCredential(issuer_did, credential_hash).transact({"from": account})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return {"tx_hash": tx_hash.hex(), "block_number": receipt.blockNumber, "status": receipt.status}


def revoke_credential(issuer_did: str, credential_hash: bytes) -> dict:
    w3 = get_w3()
    contract = get_contract()
    account = get_default_account()
    tx_hash = contract.functions.revokeCredential(issuer_did, credential_hash).transact({"from": account})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return {"tx_hash": tx_hash.hex(), "block_number": receipt.blockNumber, "status": receipt.status}


def is_revoked(credential_hash: bytes) -> bool:
    contract = get_contract()
    return contract.functions.isRevoked(credential_hash).call()


def is_anchored(credential_hash: bytes) -> bool:
    contract = get_contract()
    return contract.functions.isAnchored(credential_hash).call()
