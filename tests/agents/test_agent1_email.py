"""Tests for agent1 — Email send agent (contact verification + Gmail)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai.agents.agent1 import get_email_agent
from tests.agents.conftest import Ctx, get_tool, run


# ── lookup_contact ─────────────────────────────────────────────────────────────

def test_lookup_contact_returns_tom(ctx):
    fn = get_tool(get_email_agent, "lookup_contact")
    result = run(fn(ctx, "Tom"))
    assert "tomnguyen6766@gmail.com" in result


def test_lookup_contact_returns_khoi(ctx):
    fn = get_tool(get_email_agent, "lookup_contact")
    result = run(fn(ctx, "Khoi"))
    assert "khoiduong2913@gmail.com" in result


def test_lookup_contact_partial_name(ctx):
    fn = get_tool(get_email_agent, "lookup_contact")
    result = run(fn(ctx, "nguyen"))
    assert "tomnguyen6766@gmail.com" in result


def test_lookup_contact_not_found(ctx):
    fn = get_tool(get_email_agent, "lookup_contact")
    result = run(fn(ctx, "xyzzy_nobody"))
    assert "No verified contact found" in result


def test_lookup_contact_merges_graph_results(ctx):
    """Knowledge graph contacts appear alongside defaults."""
    mock_node = MagicMock()
    mock_node.node_type = "contact"
    mock_node.label = "Alice"
    mock_node.content = "email: alice@work.com\nstatus: verified"

    mock_knowledge = AsyncMock()
    mock_knowledge.search = AsyncMock(return_value=[mock_node])
    ctx.deps.knowledge = mock_knowledge

    fn = get_tool(get_email_agent, "lookup_contact")
    result = run(fn(ctx, "Alice"))
    assert "alice@work.com" in result


# ── send_user_email — guard ────────────────────────────────────────────────────

def test_send_user_email_blocked_unknown_address(ctx):
    """Unverified addresses are blocked when knowledge graph is active."""
    mock_knowledge = AsyncMock()
    mock_knowledge.search = AsyncMock(return_value=[])
    ctx.deps.knowledge = mock_knowledge

    fn = get_tool(get_email_agent, "send_user_email")
    result = run(fn(ctx, to="hacker@evil.com", subject="Hi", body="Hello"))
    assert "Blocked" in result


def test_send_user_email_default_contact_bypasses_guard(ctx, ledger):
    """Default contacts bypass the knowledge-graph guard and reach Gmail."""
    mock_knowledge = AsyncMock()
    mock_knowledge.search = AsyncMock(return_value=[])
    ctx.deps.knowledge = mock_knowledge

    fn = get_tool(get_email_agent, "send_user_email")
    with patch("tools.gmail.send_message", return_value="ok"):
        result = run(fn(ctx, to="tomnguyen6766@gmail.com", subject="Hey", body="Test"))
    assert "sent" in result.lower()


def test_send_user_email_demo_mode_no_creds(ctx):
    """With no workspace creds, Gmail returns a [DEMO] string — not an error."""
    fn = get_tool(get_email_agent, "send_user_email")
    # knowledge=None → guard skipped; creds=None → demo mode
    result = run(fn(ctx, to="tomnguyen6766@gmail.com", subject="Demo", body="Hi"))
    assert "[DEMO]" in result or "sent" in result.lower()


def test_send_user_email_cancelled_by_user(ctx, ledger):
    """Cancelling the consent request returns the cancel message."""
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    fn = get_tool(get_email_agent, "send_user_email")
    result = run(fn(ctx, to="tomnguyen6766@gmail.com", subject="X", body="Y"))
    assert "Cancelled" in result or "cancel" in result.lower()


# ── register_unverified_contact ───────────────────────────────────────────────

def test_register_unverified_contact_saves_node(ctx):
    """On approval, a new contact node is written to the knowledge graph."""
    mock_knowledge = AsyncMock()
    mock_knowledge.upsert_node = AsyncMock()
    ctx.deps.knowledge = mock_knowledge

    fn = get_tool(get_email_agent, "register_unverified_contact")
    result = run(fn(ctx, name="Dave", email="dave@example.com"))

    assert "verified" in result.lower() or "saved" in result.lower()
    mock_knowledge.upsert_node.assert_called_once()
    call_kwargs = mock_knowledge.upsert_node.call_args.kwargs
    assert call_kwargs.get("node_type") == "contact"
    assert "dave@example.com" in call_kwargs.get("content", "")


def test_register_unverified_contact_no_knowledge(ctx):
    """With no knowledge graph, registration fails gracefully."""
    ctx.deps.knowledge = None
    fn = get_tool(get_email_agent, "register_unverified_contact")
    result = run(fn(ctx, name="Dave", email="dave@example.com"))
    assert "unavailable" in result.lower() or "cannot" in result.lower()


# ── send_notification_email ───────────────────────────────────────────────────

def test_send_notification_email_demo_mode(ctx):
    fn = get_tool(get_email_agent, "send_notification_email")
    result = run(fn(ctx, to="tomnguyen6766@gmail.com", subject="Alert", details="Test alert"))
    assert "[DEMO]" in result or "sent" in result.lower()


def test_send_notification_email_blocked_unknown(ctx):
    mock_knowledge = AsyncMock()
    mock_knowledge.search = AsyncMock(return_value=[])
    ctx.deps.knowledge = mock_knowledge

    fn = get_tool(get_email_agent, "send_notification_email")
    result = run(fn(ctx, to="unknown@nowhere.com", subject="X", details="Y"))
    assert "Blocked" in result
