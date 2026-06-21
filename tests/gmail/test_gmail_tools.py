"""Tests for tools/gmail.py — reads are free, triage fails closed without consent.

These run in DEMO_MODE (no real Google calls). They assert the security split:
reading/searching need no consent; triage (modify/draft/trash) requires an active
consent grant opened by the gate.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tools.execution_lock import ConsentError, ConsentGrant, consent_scope
from tools.gmail import (
    LABEL_UNREAD,
    create_draft,
    modify_labels,
    read_message,
    search_messages,
    trash_message,
)


def _grant(action_type: str) -> ConsentGrant:
    return ConsentGrant(
        action_id="t",
        action_type=action_type,
        token="tok",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
    )


# ── Reads are free (no consent scope needed) ─────────────────────────────────────

def test_search_is_free():
    out = search_messages("from:priya", creds=None)
    assert "demo" in out.lower()


def test_read_is_free():
    out = read_message("demo-1", creds=None)
    assert "Subject:" in out


# ── Triage fails closed without consent ──────────────────────────────────────────

def test_modify_labels_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        modify_labels("demo-1", creds=None, remove=[LABEL_UNREAD], summary="Mark read")


def test_create_draft_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        create_draft("priya@example.com", "Hi", "body", creds=None)


def test_trash_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        trash_message("demo-1", creds=None)


# ── Triage succeeds inside the right consent scope ───────────────────────────────

def test_modify_labels_succeeds_in_scope():
    with consent_scope(_grant("gmail.modify")):
        out = modify_labels("demo-1", creds=None, remove=[LABEL_UNREAD], summary="Mark read")
    assert "Mark read" in out


def test_draft_succeeds_in_scope():
    with consent_scope(_grant("gmail.draft")):
        out = create_draft("priya@example.com", "Hi", "body", creds=None)
    assert "Draft created" in out


def test_trash_succeeds_in_scope():
    with consent_scope(_grant("gmail.trash")):
        out = trash_message("demo-1", creds=None)
    assert "Trash" in out


def test_wrong_scope_cannot_drive_triage():
    """A draft grant must not authorize a trash (action-type scoping)."""
    with consent_scope(_grant("gmail.draft")):
        with pytest.raises(ConsentError, match="consent was granted for 'gmail.draft'"):
            trash_message("demo-1", creds=None)


def test_triage_via_to_thread_in_scope():
    """Mirrors the agent: gate opens the scope, wrapper runs in a worker thread."""

    async def _run():
        with consent_scope(_grant("gmail.modify")):
            return await asyncio.to_thread(
                modify_labels, "demo-1", None, summary="Archive"
            )

    assert "Archive" in asyncio.run(_run())
