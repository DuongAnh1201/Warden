"""Tests for agent6 — Gmail inbox agent (read + triage)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ai.agents.agent6 import get_gmail_agent
from schemas.agent6 import GmailSearchRequest, GmailTriageRequest
from tests.agents.conftest import get_tool, run

DEMO_MSG_ID = "demo-1"


# ── search_inbox (no side effect, no consent gate) ────────────────────────────

def test_search_inbox_demo_mode(ctx):
    """With no creds, returns the demo string — not an error."""
    req = GmailSearchRequest(query="is:unread")
    with patch("tools.gmail.search_messages", return_value="[DEMO] 2 messages matching..."):
        fn = get_tool(get_gmail_agent, "search_inbox")
        result = run(fn(ctx, req))
    assert "[DEMO]" in result or "messages" in result.lower()


def test_search_inbox_empty(ctx):
    req = GmailSearchRequest(query="label:nonexistent")
    with patch("tools.gmail.search_messages", return_value="No messages matched 'label:nonexistent'."):
        fn = get_tool(get_gmail_agent, "search_inbox")
        result = run(fn(ctx, req))
    assert "No messages" in result or "nonexistent" in result


# ── read_email (no side effect, no consent gate) ──────────────────────────────

def test_read_email_demo_mode(ctx):
    with patch("tools.gmail.read_message", return_value="[DEMO] Message demo-1\nFrom: Priya"):
        fn = get_tool(get_gmail_agent, "read_email")
        result = run(fn(ctx, DEMO_MSG_ID))
    assert "Priya" in result or "demo-1" in result


# ── mark_read (consent gate) ──────────────────────────────────────────────────

def test_mark_read_approved(ctx, ledger):
    req = GmailTriageRequest(message_id=DEMO_MSG_ID)
    with patch("tools.gmail.modify_labels", return_value="mark read on message demo-1."):
        fn = get_tool(get_gmail_agent, "mark_read")
        result = run(fn(ctx, req))
    assert "demo-1" in result or "read" in result.lower()


def test_mark_read_cancelled(ctx, ledger):
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    req = GmailTriageRequest(message_id=DEMO_MSG_ID)
    fn = get_tool(get_gmail_agent, "mark_read")
    result = run(fn(ctx, req))
    assert "Cancelled" in result or "cancel" in result.lower()


# ── mark_unread (consent gate) ────────────────────────────────────────────────

def test_mark_unread_approved(ctx, ledger):
    req = GmailTriageRequest(message_id=DEMO_MSG_ID)
    with patch("tools.gmail.modify_labels", return_value="mark unread on message demo-1."):
        fn = get_tool(get_gmail_agent, "mark_unread")
        result = run(fn(ctx, req))
    assert "demo-1" in result or "unread" in result.lower()


# ── archive_email (consent gate) ──────────────────────────────────────────────

def test_archive_email_approved(ctx, ledger):
    req = GmailTriageRequest(message_id=DEMO_MSG_ID)
    with patch("tools.gmail.modify_labels", return_value="archive on message demo-1."):
        fn = get_tool(get_gmail_agent, "archive_email")
        result = run(fn(ctx, req))
    assert "demo-1" in result or "archive" in result.lower()


# ── star_email (consent gate) ─────────────────────────────────────────────────

def test_star_email_approved(ctx, ledger):
    req = GmailTriageRequest(message_id=DEMO_MSG_ID)
    with patch("tools.gmail.modify_labels", return_value="star on message demo-1."):
        fn = get_tool(get_gmail_agent, "star_email")
        result = run(fn(ctx, req))
    assert "demo-1" in result or "star" in result.lower()


# ── create_draft (consent gate) ──────────────────────────────────────────────

def test_create_draft_approved(ctx, ledger):
    req = GmailTriageRequest(
        to="priya@example.com",
        subject="Re: Deck",
        body="I'll have updates by EOD.",
    )
    with patch(
        "tools.gmail.create_draft",
        return_value="Draft created to priya@example.com — subject 'Re: Deck'. draft_id=d001",
    ):
        fn = get_tool(get_gmail_agent, "create_draft")
        result = run(fn(ctx, req))
    assert "draft" in result.lower() or "priya" in result.lower()


# ── trash_email (consent gate) ────────────────────────────────────────────────

def test_trash_email_approved(ctx, ledger):
    req = GmailTriageRequest(message_id=DEMO_MSG_ID)
    with patch("tools.gmail.trash_message", return_value="Moved message demo-1 to Trash."):
        fn = get_tool(get_gmail_agent, "trash_email")
        result = run(fn(ctx, req))
    assert "Trash" in result or "demo-1" in result


def test_trash_email_cancelled(ctx, ledger):
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    req = GmailTriageRequest(message_id=DEMO_MSG_ID)
    fn = get_tool(get_gmail_agent, "trash_email")
    result = run(fn(ctx, req))
    assert "Cancelled" in result or "cancel" in result.lower()
