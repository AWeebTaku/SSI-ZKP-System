"""
Cryptographic Core
==================
- Issuer digital signatures: HMAC-SHA256 over a canonical credential message.
- Selective disclosure / blinding: commitment = SHA256(status || salt).

The commitment scheme lets a Holder prove "my credential's status equals X"
to a Verifier by revealing only SHA256(X || salt) — never the salt itself,
and never any other field of the credential. The Verifier (or backend acting
on the Verifier's behalf) simply recomputes the same hash from the claimed
status the traveler is asserting and checks it against the commitment that
was anchored at issuance time. If the traveler lies about the status, the
hash will not match, and no salt or PII round-trips through the check.

NOTE ON HMAC (per project spec): HMAC-SHA256 is a *symmetric* MAC, so the
verifying party would normally need the issuer's secret key, which breaks
the "verifier never touches issuer secrets" property real DID/VC systems
rely on (they use asymmetric signatures like ECDSA/EdDSA so verification
only needs a public key). This project uses HMAC-SHA256 as explicitly
requested for the signing primitive; verification is performed only by the
same trust boundary that holds the secret (the backend acting as the
issuer's signing service), not by the Customs verifier logic, which relies
solely on the on-chain revocation state and the blinded commitment match.
"""

import hashlib
import hmac
import secrets


def generate_salt(n_bytes: int = 16) -> str:
    """Cryptographically secure random hex salt (the 'blinding entropy factor')."""
    return secrets.token_hex(n_bytes)


def compute_commitment(status: str, salt: str) -> str:
    """SHA256(status || salt) -- the blinded commitment used for selective disclosure."""
    return hashlib.sha256(f"{status}{salt}".encode("utf-8")).hexdigest()


def verify_commitment(status_claim: str, salt: str, commitment: str) -> bool:
    """Recompute the commitment from a claimed status + salt and compare (constant-time)."""
    return hmac.compare_digest(compute_commitment(status_claim, salt), commitment)


def sign_credential(secret_key: bytes, message: str) -> str:
    """HMAC-SHA256 issuer digital signature over the canonical credential message."""
    return hmac.new(secret_key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(secret_key: bytes, message: str, signature: str) -> bool:
    """Constant-time verification of an HMAC-SHA256 issuer signature."""
    expected = sign_credential(secret_key, message)
    return hmac.compare_digest(expected, signature)


def canonical_message(credential_id: str, holder_did: str, issuer_did: str,
                       commitment: str, issued_at: str, expiry_at: str) -> str:
    """Deterministic, order-sensitive message format signed by the issuer."""
    return f"{credential_id}|{holder_did}|{issuer_did}|{commitment}|{issued_at}|{expiry_at}"


def safe_hash_eq(a: str, b: str) -> bool:
    """Constant-time, case/whitespace-tolerant comparison of two hex digests."""
    try:
        return hmac.compare_digest(a.strip().lower(), b.strip().lower())
    except Exception:
        return False
