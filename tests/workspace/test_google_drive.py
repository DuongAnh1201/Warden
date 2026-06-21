"""Unit tests for tools/google_drive.py — reads free, writes fail closed.

Run in DEMO_MODE (no network). Asserts the security split: list/read need no
consent; upload/update/share/delete require a matching active consent grant.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tools.execution_lock import ConsentError, ConsentGrant, consent_scope
from tools.google_drive import (
    delete_file,
    list_files,
    read_file,
    share_file,
    update_file,
    upload_file,
)


def _grant(action_type: str) -> ConsentGrant:
    return ConsentGrant(
        action_id="t",
        action_type=action_type,
        token="tok",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
    )


# ── Reads are free ───────────────────────────────────────────────────────────────

def test_list_is_free():
    assert "demo" in list_files("name contains 'notes'", creds=None).lower()


def test_read_is_free():
    assert "demo" in read_file("demo-file-1", creds=None).lower()


# ── Writes fail closed without consent ───────────────────────────────────────────

def test_upload_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        upload_file("notes.txt", "hello", creds=None)


def test_update_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        update_file("demo-file-1", "new", creds=None)


def test_share_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        share_file("demo-file-1", "priya@example.com", creds=None)


def test_delete_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        delete_file("demo-file-1", creds=None)


# ── Writes succeed inside the right consent scope ────────────────────────────────

def test_upload_in_scope():
    with consent_scope(_grant("drive.upload")):
        assert "file_id=" in upload_file("notes.txt", "hello", creds=None)


def test_share_in_scope():
    with consent_scope(_grant("drive.share")):
        assert "Shared" in share_file("demo-file-1", "priya@example.com", creds=None)


def test_wrong_scope_cannot_drive_write():
    """An upload grant must not authorize a delete (action-type scoping)."""
    with consent_scope(_grant("drive.upload")):
        with pytest.raises(ConsentError, match="consent was granted for 'drive.upload'"):
            delete_file("demo-file-1", creds=None)


def test_write_via_to_thread_in_scope():
    async def _run():
        with consent_scope(_grant("drive.update")):
            return await asyncio.to_thread(update_file, "demo-file-1", "x", None)

    assert "Updated" in asyncio.run(_run())
