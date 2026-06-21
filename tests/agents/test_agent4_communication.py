"""Tests for agent4 — Communication agent (iMessage + phone calls)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ai.agents.agent4 import get_communication_agent
from schemas.agent4 import CallRequest, CommunicationRequest, iMessageRequest
from tests.agents.conftest import get_tool, run


# ── search_contact ────────────────────────────────────────────────────────────

def test_search_contact_tom(ctx):
    with patch("tools.communication.search_contact", return_value=[]):
        fn = get_tool(get_communication_agent, "search_contact")
        result = run(fn(ctx, "Tom"))
    assert any(c["name"] == "Tom Nguyen" for c in result)
    assert any(c["phone"] == "9253197021" for c in result)


def test_search_contact_khoi(ctx):
    with patch("tools.communication.search_contact", return_value=[]):
        fn = get_tool(get_communication_agent, "search_contact")
        result = run(fn(ctx, "Khoi"))
    assert any(c["name"] == "Khoi Duong" for c in result)
    assert any(c["phone"] == "9258608099" for c in result)


def test_search_contact_partial_match(ctx):
    """'duong' should match Khoi Duong from default contacts."""
    with patch("tools.communication.search_contact", return_value=[]):
        fn = get_tool(get_communication_agent, "search_contact")
        result = run(fn(ctx, "duong"))
    assert any("Khoi" in c.get("name", "") for c in result)


def test_search_contact_not_found_returns_fallback(ctx):
    with patch("tools.communication.search_contact", return_value=[]):
        fn = get_tool(get_communication_agent, "search_contact")
        result = run(fn(ctx, "xyzzy_nobody"))
    assert len(result) == 1
    assert "No contacts found" in result[0]["phone"]


def test_search_contact_merges_macos_results(ctx):
    """System contacts returned by macOS are included in results."""
    macos_contact = {"name": "Alice", "phone": "5551234567"}
    with patch("tools.communication.search_contact", return_value=[macos_contact]):
        fn = get_tool(get_communication_agent, "search_contact")
        result = run(fn(ctx, "Alice"))
    assert any(c["name"] == "Alice" for c in result)


# ── send_imessage ─────────────────────────────────────────────────────────────

def test_send_imessage_approved(ctx, ledger):
    req = CommunicationRequest(
        action="imessage",
        imessage=iMessageRequest(recipient="9253197021", body="I'm running 10 min late"),
    )
    with patch("tools.communication.send_imessage", return_value=True):
        fn = get_tool(get_communication_agent, "send_imessage")
        result = run(fn(ctx, req))
    assert "sent" in result.lower() or "iMessage" in result


def test_send_imessage_cancelled(ctx, ledger):
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    req = CommunicationRequest(
        action="imessage",
        imessage=iMessageRequest(recipient="9253197021", body="Hello"),
    )
    fn = get_tool(get_communication_agent, "send_imessage")
    result = run(fn(ctx, req))
    assert "Cancelled" in result or "cancel" in result.lower()


def test_send_imessage_tool_failure(ctx, ledger):
    req = CommunicationRequest(
        action="imessage",
        imessage=iMessageRequest(recipient="9253197021", body="Hi"),
    )
    with patch("tools.communication.send_imessage", return_value=False):
        fn = get_tool(get_communication_agent, "send_imessage")
        result = run(fn(ctx, req))
    assert "Failed" in result or "failed" in result.lower()


# ── make_call ─────────────────────────────────────────────────────────────────

def test_make_call_approved(ctx, ledger):
    req = CommunicationRequest(
        action="call",
        call=CallRequest(recipient="9253197021"),
    )
    with patch("tools.communication.make_call", return_value=True):
        fn = get_tool(get_communication_agent, "make_call")
        result = run(fn(ctx, req))
    assert "Calling" in result or "call" in result.lower()


def test_make_call_cancelled(ctx, ledger):
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    req = CommunicationRequest(action="call", call=CallRequest(recipient="9253197021"))
    fn = get_tool(get_communication_agent, "make_call")
    result = run(fn(ctx, req))
    assert "Cancelled" in result or "cancel" in result.lower()
