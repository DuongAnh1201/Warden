"""Tests for consent bypass detection and kill switch."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai.agents.consent_token import mint_consent_token
from observability.evaluator import (
    detect_consent_bypass,
    evaluate_consent_trace,
    verify_ledger_token,
)
from observability.kill_switch import (
    SessionFrozenError,
    assert_session_active,
    is_session_frozen,
    reset_kill_switch,
    trigger_kill_switch,
    KillSwitchEvent,
)
from observability.spans import (
    GATE_PAUSED,
    INTENT_GENERATED,
    LEDGER_APPENDED,
    TOOL_EXECUTED,
    VOICE_APPROVAL,
)
from schemas.consent import ActionDecision, ActionRequest, LedgerEntry


@pytest.fixture(autouse=True)
def _reset_kill_switch():
    reset_kill_switch()
    yield
    reset_kill_switch()


def test_healthy_sequence_passes():
    seq = [
        INTENT_GENERATED,
        GATE_PAUSED,
        VOICE_APPROVAL,
        LEDGER_APPENDED,
        TOOL_EXECUTED,
    ]
    assert detect_consent_bypass(seq).ok


def test_bypass_detected_without_ledger():
    seq = [INTENT_GENERATED, GATE_PAUSED, VOICE_APPROVAL, TOOL_EXECUTED]
    result = detect_consent_bypass(seq)
    assert not result.ok
    assert LEDGER_APPENDED in result.reason


def test_cancel_path_without_tool_executed_passes():
    seq = [INTENT_GENERATED, GATE_PAUSED, VOICE_APPROVAL]
    assert evaluate_consent_trace(seq, action_id="a1", ledger_token="", entry=None).ok


def test_verify_ledger_token_matches_hmac():
    req = ActionRequest(action_type="email.send", agent="email", summary="hi", payload={})
    decided_at = datetime.now(timezone.utc)
    token = mint_consent_token(req.action_id, req.summary, decided_at.isoformat())
    entry = LedgerEntry(
        request=req,
        decision=ActionDecision(
            action_id=req.action_id,
            decision="approve",
            consent_token=token,
            decided_at=decided_at,
        ),
    )
    assert verify_ledger_token(entry, token, req.action_id).ok


def test_verify_ledger_token_missing_entry_is_not_bypass():
    """Redis lookup failure (entry=None) must not trigger the kill switch."""
    result = verify_ledger_token(None, "some-token", "action-xyz")
    assert result.ok, f"Expected ok=True for missing entry, got: {result.reason}"


def test_evaluate_consent_trace_missing_entry_does_not_kill():
    """Full trace eval with entry=None should pass — span sequence is the real check."""
    seq = [INTENT_GENERATED, GATE_PAUSED, VOICE_APPROVAL, LEDGER_APPENDED, TOOL_EXECUTED]
    result = evaluate_consent_trace(seq, action_id="a1", ledger_token="tok", entry=None)
    assert result.ok, f"Expected ok=True for missing ledger entry, got: {result.reason}"


def test_kill_switch_freezes_session():
    trigger_kill_switch(KillSwitchEvent(reason="test bypass", action_id="x"))
    assert is_session_frozen()
    with pytest.raises(SessionFrozenError):
        assert_session_active()
