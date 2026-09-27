"""
Storage layer.

Three deliberately separate stores, matching the trust boundaries of the
system:

- wallets.json  : Holder-owned. Full credential records (including plaintext
                   status, salt, and traveler PII) live only here, because
                   the Holder is the sole party entitled to hold that data.

- registry.json : Verifier/Issuer-facing. Contains only opaque commitments,
                   on-chain hash references, and signatures -- never raw PII
                   or the blinding salt. This is what /verify-border reads.

- holders.json  : Issuer-side operational convenience only -- a case-file
                   style cache of (traveler_name, passport_number,
                   nationality) keyed by holder_did, so the Issuer Console
                   can autofill a repeat holder's details instead of
                   retyping them. This is NOT part of the SSI protocol and
                   nothing outside the Issuer Console reads it -- Customs
                   and the Wallet view never touch this file.
"""

import json
import os
import tempfile
import threading

_LOCK = threading.Lock()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
WALLET_FILE = os.path.join(STORAGE_DIR, "wallets.json")
REGISTRY_FILE = os.path.join(STORAGE_DIR, "registry.json")
HOLDER_FILE = os.path.join(STORAGE_DIR, "holders.json")


def _ensure() -> None:
    os.makedirs(STORAGE_DIR, exist_ok=True)
    for path in (WALLET_FILE, REGISTRY_FILE, HOLDER_FILE):
        if not os.path.exists(path):
            with open(path, "w") as fh:
                json.dump({}, fh)


def _read(path: str) -> dict:
    _ensure()
    with _LOCK:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)


def _write(path: str, data: dict) -> None:
    _ensure()
    with _LOCK:
        directory = os.path.dirname(path)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False
        ) as fh:
            json.dump(data, fh, indent=2, default=str)
            fh.write("\n")
            temporary_path = fh.name
        os.replace(temporary_path, path)


def read_wallets() -> dict:
    return _read(WALLET_FILE)


def write_wallets(data: dict) -> None:
    _write(WALLET_FILE, data)


def read_registry() -> dict:
    return _read(REGISTRY_FILE)


def write_registry(data: dict) -> None:
    _write(REGISTRY_FILE, data)


def read_holders() -> dict:
    return _read(HOLDER_FILE)


def write_holders(data: dict) -> None:
    _write(HOLDER_FILE, data)
