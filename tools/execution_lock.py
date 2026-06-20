"""The execution lock — the hard-coded gate around every real-world side effect.

Implements Phase 1 §4 of docs/consent-architecture/01-consent-gate.md.

The rule: a side-effecting tool wrapper (the function that physically hits
Resend, the macOS Calendar, Messages, the filesystem, ...) MUST call
``require_consent(action_type)`` before it acts. The *only* code path that grants
consent is ``ai.agents.consent.gate``, which opens a ``consent_scope`` carrying a
valid Consent_Token *after* it has recorded the user's approval.

If a tool runs outside that scope — e.g. the orchestrator hallucinates and calls a
sensitive tool directly, bypassing the ProposedAction/consent step — there is no
active grant and ``require_consent`` raises :class:`ConsentError`. The system fails
closed: no token, no effect.

The grant is propagated via a :class:`contextvars.ContextVar`, which
``asyncio.to_thread`` copies into worker threads, so synchronous tool wrappers run
under the same scope as the awaiting gate.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone


class ConsentError(Exception):
    """Raised when a side effect is attempted without valid, active consent.

    Deliberately subclasses :class:`Exception` (not :class:`RuntimeError`) so that
    tool code which broadly catches ``RuntimeError`` cannot accidentally swallow a
    fail-closed signal.
    """


@dataclass
class ConsentGrant:
    """An active authorization for exactly one side effect.

    Single-use and scoped to one ``action_type``: a grant minted for, say,
    ``calendar.create`` cannot be used to ``email.send``.
    """

    action_id: str
    action_type: str
    token: str
    expires_at: datetime
    consumed: bool = field(default=False)


_active_grant: contextvars.ContextVar["ConsentGrant | None"] = contextvars.ContextVar(
    "moneypenny_active_consent_grant", default=None
)


@contextmanager
def consent_scope(grant: ConsentGrant):
    """Activate ``grant`` for the duration of the block (and any thread it spawns)."""
    token = _active_grant.set(grant)
    try:
        yield
    finally:
        _active_grant.reset(token)


def active_grant() -> "ConsentGrant | None":
    """Return the currently active grant, if any (read-only; does not consume)."""
    return _active_grant.get()


def require_consent(action_type: str) -> str:
    """Fail closed unless a valid, active, matching grant exists. Returns its token.

    Enforced invariants (any failure raises :class:`ConsentError`):
      * a grant is active in this context (else: a bypass attempt),
      * it has not already been consumed (single-use),
      * its ``action_type`` matches the action being attempted,
      * it has not expired (the 300s consent TTL).

    On success the grant is consumed, so a single approval authorizes exactly one
    side effect.
    """
    grant = _active_grant.get()
    if grant is None:
        raise ConsentError(
            f"BLOCKED: '{action_type}' attempted with no active consent grant. "
            "Every real-world action must pass through the consent gate."
        )
    if grant.consumed:
        raise ConsentError(
            f"BLOCKED: consent for action '{grant.action_id}' was already consumed "
            "(Consent_Tokens are single-use)."
        )
    if grant.action_type != action_type:
        raise ConsentError(
            f"BLOCKED: consent was granted for '{grant.action_type}', "
            f"but a '{action_type}' action was attempted."
        )
    if datetime.now(timezone.utc) >= grant.expires_at:
        raise ConsentError(
            f"BLOCKED: consent for action '{grant.action_id}' has expired."
        )
    grant.consumed = True
    return grant.token
