"""Tests for ai/agents/consent_token.py — HMAC Consent_Token minting."""
from __future__ import annotations

from ai.agents.consent_token import mint_consent_token, tokens_match


def test_mint_is_deterministic_for_same_inputs():
    a = mint_consent_token("aid-1", "send email to priya", "2026-06-20T00:00:00+00:00")
    b = mint_consent_token("aid-1", "send email to priya", "2026-06-20T00:00:00+00:00")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_mint_differs_when_action_id_changes():
    ts = "2026-06-20T00:00:00+00:00"
    a = mint_consent_token("aid-1", "yes", ts)
    b = mint_consent_token("aid-2", "yes", ts)
    assert a != b


def test_mint_differs_when_transcript_changes():
    a = mint_consent_token("aid-1", "yes", "2026-06-20T00:00:00+00:00")
    b = mint_consent_token("aid-1", "no", "2026-06-20T00:00:00+00:00")
    assert a != b


def test_tokens_match_uses_constant_time_comparison():
    token = mint_consent_token("x", "y", "z")
    assert tokens_match(token, token) is True
    assert tokens_match(token, "wrong") is False
    assert tokens_match("", "") is True
