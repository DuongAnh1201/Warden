"""Tests for ai/agents/consent.py — the consent gate funnel."""
from __future__ import annotations

import asyncio

import pytest

from ai.agents.consent import gate
from ai.agents.deps import OrchestratorDeps
from tests.consent.conftest import FakeRunContext, approval, run
from tools.execution_lock import require_consent


async def _gate(
    ledger,
    *,
    decision: str = "approve",
    revision_note: str = "",
    auto_approve: bool = False,
    request_approval=None,
    action_type: str = "email.send",
    execute=None,
):
    if request_approval is None and not auto_approve and decision:
        request_approval = approval(decision, revision_note=revision_note)

    deps = OrchestratorDeps(
        ledger=ledger,
        auto_approve=auto_approve,
        request_approval=request_approval,
    )
    ctx = FakeRunContext(deps=deps)
    called = {"n": 0}

    async def _default_execute():
        called["n"] += 1
        require_consent(action_type)
        return "side-effect-ok"

    result = await gate(
        ctx,
        action_type=action_type,  # type: ignore[arg-type]
        agent="test_agent",
        summary="Send email to priya@example.com — subject 'Deck is ready'",
        payload={"to": "priya@example.com"},
        execute=execute or _default_execute,
    )
    entries = await ledger.history(limit=1)
    return result, entries[0] if entries else None, called["n"]


def test_gate_approve_executes_and_ledgers_token(ledger):
    result, entry, execute_count = run(_gate(ledger, decision="approve"))

    assert result == "side-effect-ok"
    assert execute_count == 1
    assert entry is not None
    assert entry.decision is not None
    assert entry.decision.decision == "approve"
    assert entry.decision.consent_token  # HMAC minted on approval
    assert entry.outcome == "executed"


def test_gate_cancel_does_not_execute(ledger):
    result, entry, execute_count = run(_gate(ledger, decision="cancel"))

    assert "Cancelled" in result
    assert execute_count == 0
    assert entry.outcome == "cancelled"


def test_gate_revise_does_not_execute(ledger):
    result, entry, execute_count = run(
        _gate(ledger, decision="revise", revision_note="make it more casual")
    )

    assert "Revision requested" in result
    assert "more casual" in result
    assert execute_count == 0
    assert entry.outcome == "cancelled"
    assert "more casual" in entry.result_message


def test_gate_default_deny_without_approver(ledger):
    async def _run():
        deps = OrchestratorDeps(ledger=ledger)  # no approver, auto_approve=False
        ctx = FakeRunContext(deps=deps)
        executed = False

        async def execute():
            nonlocal executed
            executed = True
            return "should-not-run"

        result = await gate(
            ctx,
            action_type="email.send",
            agent="test_agent",
            summary="test",
            payload={},
            execute=execute,
        )
        entries = await ledger.history(limit=1)
        return result, entries[0], executed

    result, entry, executed = run(_run())

    assert executed is False
    assert "Cancelled" in result
    assert entry.decision.decision == "cancel"


def test_gate_auto_approve_executes(ledger):
    result, entry, execute_count = run(_gate(ledger, auto_approve=True, decision=""))

    assert result == "side-effect-ok"
    assert execute_count == 1
    assert entry.outcome == "executed"


def test_gate_records_failed_when_lock_rejects_wrong_action_type(ledger):
    async def bad_execute():
        require_consent("calendar.create")  # scope is opened for email.send
        return "should-not-reach"

    result, entry, _ = run(_gate(ledger, decision="approve", execute=bad_execute))

    assert "action blocked by the consent lock" in result.lower()
    assert entry.outcome == "failed"
    assert "consent lock blocked" in entry.result_message.lower()


def test_gate_records_failed_when_execute_raises(ledger):
    async def failing_execute():
        require_consent("email.send")
        raise RuntimeError("resend error: 500")

    result, entry, _ = run(_gate(ledger, decision="approve", execute=failing_execute))

    assert "Action failed" in result
    assert "500" in result
    assert entry.outcome == "failed"


def test_gate_execute_via_to_thread(ledger):
    """End-to-end: gate scope survives asyncio.to_thread like real agent tools."""

    async def threaded_execute():
        return await asyncio.to_thread(require_consent, "email.send")

    async def _run():
        return await _gate(ledger, decision="approve", execute=threaded_execute)

    result, entry, _ = run(_run())

    assert entry.decision.consent_token
    assert entry.outcome == "executed"
    assert len(result) == 64  # HMAC token returned from require_consent via to_thread
