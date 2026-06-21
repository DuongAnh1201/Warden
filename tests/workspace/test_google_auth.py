"""Tests for tools/google_auth.py — scope resolution, encrypted token store,
the interactive menu, and lifecycle ledger logging. No network / real OAuth.
"""
from __future__ import annotations

import asyncio

import pytest

from tools.google_auth import (
    SCOPE_CATALOG,
    delete_token,
    granted_scopes,
    load_token,
    log_workspace_event,
    prompt_scope_selection,
    resolve_scopes,
    save_token,
    summarize_selection,
)

KEY = "unit-test-key"


# ── Scope resolution ─────────────────────────────────────────────────────────────

def test_off_yields_no_scopes():
    assert resolve_scopes({"drive": "off", "gmail": "off", "calendar": "off"}) == []


def test_drive_full_scope():
    assert resolve_scopes({"drive": "full"}) == ["https://www.googleapis.com/auth/drive"]


def test_drive_file_is_least_privilege_default():
    assert SCOPE_CATALOG["drive"]["default"] == "file"
    assert resolve_scopes({"drive": "file"}) == ["https://www.googleapis.com/auth/drive.file"]


def test_scopes_are_deduped_and_sorted():
    scopes = resolve_scopes({"gmail": "send", "calendar": "manage"})
    assert scopes == sorted(set(scopes))
    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert "https://www.googleapis.com/auth/gmail.modify" in scopes  # send level includes modify


def test_unknown_surface_fails_closed():
    with pytest.raises(ValueError, match="Unknown surface"):
        resolve_scopes({"sharepoint": "full"})


def test_unknown_level_fails_closed():
    with pytest.raises(ValueError, match="Unknown level"):
        resolve_scopes({"drive": "superuser"})


def test_summarize_selection_is_human_readable():
    s = summarize_selection({"drive": "file", "gmail": "off"})
    assert "Google Drive" in s and "Gmail" in s


# ── Interactive menu (injected IO) ───────────────────────────────────────────────

def test_prompt_defaults_on_empty_input():
    answers = iter(["", "", ""])  # accept default for each surface
    selection = prompt_scope_selection(input_fn=lambda _: next(answers), print_fn=lambda *a, **k: None)
    assert selection == {"drive": "file", "gmail": "read", "calendar": "manage"}


def test_prompt_accepts_named_and_numeric_choices():
    # drive -> "full" by name; gmail -> "1" (off); calendar -> "read" by name
    answers = iter(["full", "1", "read"])
    selection = prompt_scope_selection(input_fn=lambda _: next(answers), print_fn=lambda *a, **k: None)
    assert selection["drive"] == "full"
    assert selection["gmail"] == "off"
    assert selection["calendar"] == "read"


# ── Encrypted token store ────────────────────────────────────────────────────────

def test_token_roundtrip(tmp_path):
    p = tmp_path / "creds.enc"
    data = {"refresh_token": "rt", "scopes": ["s1", "s2"], "client_id": "cid"}
    save_token(data, path=p, key=KEY)
    assert p.exists()
    assert load_token(path=p, key=KEY) == data


def test_token_is_encrypted_on_disk(tmp_path):
    p = tmp_path / "creds.enc"
    save_token({"refresh_token": "super-secret-value"}, path=p, key=KEY)
    raw = p.read_bytes()
    assert b"super-secret-value" not in raw  # not stored in cleartext


def test_wrong_key_cannot_decrypt(tmp_path):
    p = tmp_path / "creds.enc"
    save_token({"refresh_token": "rt"}, path=p, key=KEY)
    assert load_token(path=p, key="different-key") is None  # fails closed


def test_load_missing_returns_none(tmp_path):
    assert load_token(path=tmp_path / "nope.enc", key=KEY) is None


def test_granted_scopes_and_delete(tmp_path):
    p = tmp_path / "creds.enc"
    save_token({"scopes": ["a", "b"]}, path=p, key=KEY)
    assert granted_scopes(path=p, key=KEY) == ["a", "b"]
    assert delete_token(path=p) is True
    assert granted_scopes(path=p, key=KEY) == []
    assert delete_token(path=p) is False  # already gone


# ── Lifecycle ledger logging ─────────────────────────────────────────────────────

def test_log_workspace_event_writes_ledger(tmp_path):
    from tools.ledger import FileLedger

    ledger = FileLedger(path=tmp_path / "ledger.jsonl")

    async def _run():
        await log_workspace_event(ledger, "workspace.connect", "Connected — Drive: file", {"drive": "file"})
        return await ledger.history(limit=1)

    entries = asyncio.run(_run())
    assert len(entries) == 1
    assert entries[0].request.action_type == "workspace.connect"
    assert entries[0].decision.decision == "approve"
    assert entries[0].outcome == "executed"
