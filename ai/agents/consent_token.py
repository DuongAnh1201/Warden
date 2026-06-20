"""The Consent_Token — the cryptographic proof that a human approved an action.

Implements Phase 1 §3 of docs/consent-architecture/01-consent-gate.md.

A token is an HMAC-SHA256 over ``timestamp | action_id | transcript`` keyed by a
server-side secret. Because the key never leaves the backend, a token cannot be
forged by the LLM, a tool, or a client — it can only be minted here, after the
consent gate has recorded the user's approval. The token is appended to the
consent ledger (the Consent Ledger) and is what the execution lock requires
before any real-world side effect runs.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def _secret() -> bytes:
    """Resolve the signing secret from settings, then env, then a dev default."""
    secret: str | None = None
    try:
        from config import settings

        secret = getattr(settings, "consent_secret", None)
    except Exception:  # noqa: BLE001 — config may be unavailable in some contexts
        secret = None
    secret = secret or os.environ.get("CONSENT_SECRET") or "moneypenny-dev-consent-secret-change-me"
    return secret.encode("utf-8")


def mint_consent_token(action_id: str, transcript: str, timestamp: str) -> str:
    """Mint a forgery-resistant Consent_Token for an approved action.

    Args:
        action_id: The id of the ``ActionRequest`` being approved.
        transcript: The text basis of the approval (e.g. the spoken transcription,
            or a deterministic summary of the action when no transcript exists).
        timestamp: ISO-8601 timestamp of the approval.
    """
    message = f"{timestamp}|{action_id}|{transcript}".encode("utf-8")
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()


def tokens_match(expected: str, provided: str) -> bool:
    """Constant-time comparison of two tokens (defends against timing attacks)."""
    return hmac.compare_digest(expected or "", provided or "")
