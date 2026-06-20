"""The consent gate — the single funnel for every consequential action.

Usage inside any gated tool:

    return await gate(
        ctx,
        action_type="email.send",
        agent="email_agent",
        summary="Send email to priya@example.com — subject 'Deck is ready'",
        payload={"to": ..., "subject": ..., "body": ...},
        execute=_execute,   # async () -> str
    )

The gate records the request, asks the user (via deps.request_approval), records
the decision, runs the side effect on approve, and records the outcome.
Default policy when no approver is set: DENY (nothing fires silently).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ai.agents.consent_token import mint_consent_token
from schemas.consent import ActionDecision, ActionRequest, ActionType
from tools.execution_lock import ConsentError, ConsentGrant, consent_scope

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from ai.agents.deps import OrchestratorDeps

# The consent TTL: an approval authorizes execution for this long, then expires.
# Mirrors the 300s PENDING_CONSENT TTL in 01-consent-gate.md.
CONSENT_TTL_SECONDS = 300


async def gate(
    ctx: RunContext[OrchestratorDeps],
    action_type: ActionType,
    agent: str,
    summary: str,
    payload: dict,
    execute: Callable[[], Awaitable[str]],
) -> str:
    """Ask for consent, then execute (or not). Always writes to the ledger."""
    deps = ctx.deps
    ledger = deps.ledger

    req = ActionRequest(
        action_type=action_type,
        agent=agent,
        summary=summary,
        payload=payload,
    )
    await ledger.record_request(req)

    decision = await _decide(deps, req)

    # On approval, mint the Consent_Token *before* recording the decision so the
    # ledger captures the cryptographic proof of consent (Phase 1 §3).
    approved_at = datetime.now(timezone.utc)
    if decision.decision == "approve" and not decision.consent_token:
        approval_basis = decision.revision_note or req.summary
        decision.consent_token = mint_consent_token(
            req.action_id, approval_basis, approved_at.isoformat()
        )

    await ledger.record_decision(decision)

    if decision.decision == "cancel":
        await ledger.record_outcome(req.action_id, "cancelled", "User cancelled.")
        return "Cancelled — nothing was done."

    if decision.decision == "revise":
        note = decision.revision_note or "No note provided."
        await ledger.record_outcome(
            req.action_id, "cancelled", f"User requested revision: {note}"
        )
        return f"Revision requested: {note} — please adjust and re-propose."

    # decision == "approve": open a single-use, action-scoped consent grant and run
    # the side effect inside it. The physical tool wrapper calls require_consent()
    # and will fail closed if this scope is ever absent (Phase 1 §4).
    grant = ConsentGrant(
        action_id=req.action_id,
        action_type=action_type,
        token=decision.consent_token,
        expires_at=approved_at + timedelta(seconds=CONSENT_TTL_SECONDS),
    )
    try:
        with consent_scope(grant):
            result = await execute()
        await ledger.record_outcome(req.action_id, "executed", result)
        return result
    except ConsentError as e:
        # The execution lock fired even though the gate approved — a structural
        # anomaly. Fail closed and record it as a security-relevant failure.
        msg = f"consent lock blocked execution: {e}"
        await ledger.record_outcome(req.action_id, "failed", msg)
        return f"Action blocked by the consent lock: {e}. Do not retry."
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        await ledger.record_outcome(req.action_id, "failed", msg)
        return f"Action failed: {msg}. Do not retry."


async def _decide(
    deps: OrchestratorDeps, req: ActionRequest
) -> ActionDecision:
    """Return a decision, either from the registered approver or the auto policy."""
    if deps.request_approval is not None:
        return await deps.request_approval(req)

    if deps.auto_approve:
        return ActionDecision(action_id=req.action_id, decision="approve")

    # Safe default: deny when no approver is wired up.
    return ActionDecision(action_id=req.action_id, decision="cancel")
