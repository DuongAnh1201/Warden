"""Tests for agent7 — Google Drive agent (read + write)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ai.agents.agent7 import get_drive_agent
from schemas.agent7 import DriveFileRequest, DriveSearchRequest
from tests.agents.conftest import get_tool, run

DEMO_FILE_ID = "file-abc123"


# ── search_drive (no side effect) ─────────────────────────────────────────────

def test_search_drive_demo_mode(ctx):
    req = DriveSearchRequest(query="Q2 report")
    with patch("tools.google_drive.list_files", return_value="[DEMO] 1 file: Q2-Report.docx"):
        fn = get_tool(get_drive_agent, "search_drive")
        result = run(fn(ctx, req))
    assert "Q2" in result or "file" in result.lower()


def test_search_drive_empty(ctx):
    req = DriveSearchRequest(query="nonexistent_xyzzy")
    with patch("tools.google_drive.list_files", return_value="No files found."):
        fn = get_tool(get_drive_agent, "search_drive")
        result = run(fn(ctx, req))
    assert "No files" in result or "found" in result.lower()


# ── read_drive_file (no side effect) ─────────────────────────────────────────

def test_read_drive_file_demo_mode(ctx):
    with patch("tools.google_drive.read_file", return_value="[DEMO] File content here"):
        fn = get_tool(get_drive_agent, "read_drive_file")
        result = run(fn(ctx, DEMO_FILE_ID))
    assert "content" in result.lower() or DEMO_FILE_ID in result or "[DEMO]" in result


# ── create_drive_file (consent gate) ─────────────────────────────────────────

def test_create_drive_file_approved(ctx, ledger):
    req = DriveFileRequest(name="Board Agenda June 2026", content="1. Q3 review")
    with patch("tools.google_drive.upload_file", return_value="file-new123"):
        fn = get_tool(get_drive_agent, "create_drive_file")
        result = run(fn(ctx, req))
    assert "file-new123" in result or "created" in result.lower() or "Board Agenda" in result


def test_create_drive_file_cancelled(ctx, ledger):
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    req = DriveFileRequest(name="Secret Doc", content="top secret")
    fn = get_tool(get_drive_agent, "create_drive_file")
    result = run(fn(ctx, req))
    assert "Cancelled" in result or "cancel" in result.lower()


# ── update_drive_file (consent gate) ─────────────────────────────────────────

def test_update_drive_file_approved(ctx, ledger):
    req = DriveFileRequest(file_id=DEMO_FILE_ID, content="Updated content")
    with patch("tools.google_drive.update_file", return_value=DEMO_FILE_ID):
        fn = get_tool(get_drive_agent, "update_drive_file")
        result = run(fn(ctx, req))
    assert DEMO_FILE_ID in result or "updated" in result.lower()


# ── share_drive_file (consent gate) ──────────────────────────────────────────

def test_share_drive_file_approved(ctx, ledger):
    req = DriveFileRequest(file_id=DEMO_FILE_ID, email="tom@example.com", role="reader")
    with patch("tools.google_drive.share_file", return_value="Shared with tom@example.com"):
        fn = get_tool(get_drive_agent, "share_drive_file")
        result = run(fn(ctx, req))
    assert "tom@example.com" in result or "shared" in result.lower()


def test_share_drive_file_cancelled(ctx, ledger):
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    req = DriveFileRequest(file_id=DEMO_FILE_ID, email="stranger@example.com")
    fn = get_tool(get_drive_agent, "share_drive_file")
    result = run(fn(ctx, req))
    assert "Cancelled" in result or "cancel" in result.lower()


# ── delete_drive_file (consent gate) ─────────────────────────────────────────

def test_delete_drive_file_approved(ctx, ledger):
    req = DriveFileRequest(file_id=DEMO_FILE_ID)
    with patch("tools.google_drive.delete_file", return_value=f"Deleted {DEMO_FILE_ID}"):
        fn = get_tool(get_drive_agent, "delete_drive_file")
        result = run(fn(ctx, req))
    assert DEMO_FILE_ID in result or "deleted" in result.lower()


def test_delete_drive_file_cancelled(ctx, ledger):
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    req = DriveFileRequest(file_id=DEMO_FILE_ID)
    fn = get_tool(get_drive_agent, "delete_drive_file")
    result = run(fn(ctx, req))
    assert "Cancelled" in result or "cancel" in result.lower()
