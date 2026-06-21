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

Every gated action emits Phoenix spans (Intent_Generated → … → Tool_Executed) and
runs the self-check bypass evaluator (see observability/).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING

from ai.agents.consent_token import mint_consent_token
from observability.consent_trace import ConsentSpanRecorder, consent_recorder_scope
from observability.evaluator import evaluate_consent_trace
from observability.kill_switch import (
    KillSwitchEvent,
    assert_session_active,
    trigger_kill_switch,
)
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
    assert_session_active()
    deps = ctx.deps
    ledger = deps.ledger

    req = ActionRequest(
        action_type=action_type,
        agent=agent,
        summary=summary,
        payload=payload,
    )
    recorder = ConsentSpanRecorder(req.action_id, action_type, agent)

    with consent_recorder_scope(recorder):
        recorder.intent_generated(req)
        await ledger.record_request(req)

        recorder.gate_paused()
        decision = await _decide(deps, req)
        recorder.voice_approval(decision)

        if decision.decision == "approve" and not decision.consent_token:
            approval_basis = decision.revision_note or req.summary
            decision.consent_token = mint_consent_token(
                req.action_id, approval_basis, decision.decided_at.isoformat()
            )

        await ledger.record_decision(decision)
        if decision.decision == "approve" and decision.consent_token:
            recorder.ledger_appended(decision.consent_token)
        else:
            recorder.ledger_only()

        if decision.decision == "cancel":
            await ledger.record_outcome(req.action_id, "cancelled", "User cancelled.")
            await _run_post_action_eval(deps, recorder, req.action_id)
            return "Cancelled — nothing was done."

        if decision.decision == "revise":
            note = decision.revision_note or "No note provided."
            await ledger.record_outcome(
                req.action_id, "cancelled", f"User requested revision: {note}"
            )
            await _run_post_action_eval(deps, recorder, req.action_id)
            return f"Revision requested: {note} — please adjust and re-propose."

        grant = ConsentGrant(
            action_id=req.action_id,
            action_type=action_type,
            token=decision.consent_token,
            expires_at=decision.decided_at + timedelta(seconds=CONSENT_TTL_SECONDS),
        )
        try:
            with consent_scope(grant):
                result = await execute()
            await ledger.record_outcome(req.action_id, "executed", result)
            await _run_post_action_eval(deps, recorder, req.action_id)
            return result
        except ConsentError as e:
            recorder.abort_open_spans(str(e))
            msg = f"consent lock blocked execution: {e}"
            await ledger.record_outcome(req.action_id, "failed", msg)
            await _run_post_action_eval(deps, recorder, req.action_id)
            return f"Action blocked by the consent lock: {e}. Do not retry."
        except Exception as e:  # noqa: BLE001
            recorder.abort_open_spans(str(e))
            msg = str(e)
            await ledger.record_outcome(req.action_id, "failed", msg)
            await _run_post_action_eval(deps, recorder, req.action_id)
            return f"Action failed: {msg}. Do not retry."


async def _run_post_action_eval(
    deps: OrchestratorDeps,
    recorder: ConsentSpanRecorder,
    action_id: str,
) -> None:
    """Self-check: reconcile span sequence + ledger token; trigger kill switch on bypass."""
    try:
        from config import settings
    except Exception:  # noqa: BLE001
        return
    if not settings.consent_eval_enabled:
        return

    entry = await deps.ledger.lookup(action_id)
    result = evaluate_consent_trace(
        recorder.sequence,
        action_id=action_id,
        ledger_token=recorder.ledger_token,
        entry=entry,
    )
    if result.ok:
        return
    if settings.kill_switch_on_bypass:
        trigger_kill_switch(
            KillSwitchEvent(
                reason=result.reason,
                action_id=action_id,
            )
        )


async def _decide(
    deps: OrchestratorDeps, req: ActionRequest
) -> ActionDecision:
    """Return a decision, either from the registered approver or the auto policy."""
    if deps.request_approval is not None:
        return await deps.request_approval(req)

    if deps.auto_approve:
        return ActionDecision(action_id=req.action_id, decision="approve")

    return ActionDecision(action_id=req.action_id, decision="cancel")
