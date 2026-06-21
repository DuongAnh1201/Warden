"""Comprehensive Google Workspace integration tests — Drive, Gmail, Calendar.

Runs against REAL Google APIs. Opt-in, self-contained, self-cleaning.

Prerequisites
─────────────
1. Complete the OAuth flow on the server:
       GET https://sss-production-a90a.up.railway.app/api/workspace/connect
   (or locally: uv run python server.py, then visit http://localhost:8765/api/workspace/connect)

2. Set env vars (all required):
       RUN_GOOGLE_INTEGRATION=1
       DESIR_DEMO=0

3. Run:
       uv run pytest tests/integration/test_google_workspace.py -v -s

Why these tests exist
─────────────────────
The Google tools work locally when credentials are present in .workspace/credentials.enc.
On Railway the file is gone on every deploy — so either:
  - Visit /api/workspace/connect once per deploy to re-authorize, OR
  - Store WORKSPACE_TOKEN_B64 (see below) in Railway env vars for persistence.

Persistence tip for Railway
───────────────────────────
After authorizing locally, run:
    python -c "
    from tools.google_auth import load_token; import json, base64
    t = load_token()
    print(base64.b64encode(json.dumps(t).encode()).decode())
    "
Paste the output as WORKSPACE_TOKEN_B64 in Railway env vars.
The _load_or_inject_token() helper below reads it automatically.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

# ── Skip gating ───────────────────────────────────────────────────────────────

pytestmark = pytest.mark.integration


def _opted_in() -> bool:
    return os.getenv("RUN_GOOGLE_INTEGRATION", "").strip() in {"1", "true", "yes"}


def _skip_unless_opted_in(surface: str):
    if not _opted_in():
        pytest.skip(f"RUN_GOOGLE_INTEGRATION=1 required for live {surface} tests")


def _load_or_inject_token():
    """Load credentials from file OR from WORKSPACE_TOKEN_B64 env var.

    WORKSPACE_TOKEN_B64 is the base64-encoded JSON token blob — useful for
    Railway where the .workspace/ directory is ephemeral.
    """
    # Try env var first (Railway-friendly)
    b64 = os.getenv("WORKSPACE_TOKEN_B64", "")
    if b64:
        try:
            data = json.loads(base64.b64decode(b64).decode())
            # Inject into the normal token path so all tools pick it up
            from tools.google_auth import save_token
            save_token(data)
            print("\n[workspace] token loaded from WORKSPACE_TOKEN_B64")
        except Exception as e:
            print(f"\n[workspace] WARNING: could not load WORKSPACE_TOKEN_B64: {e}")

    from tools.google_auth import get_workspace_credentials
    return get_workspace_credentials()


@contextmanager
def _consent(action_type: str):
    """Open a real consent scope so gated write tools run in tests."""
    from tools.execution_lock import ConsentGrant, consent_scope
    grant = ConsentGrant(
        action_id=f"integration-{action_type}-{uuid.uuid4().hex[:6]}",
        action_type=action_type,
        token="integration-token",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
    )
    with consent_scope(grant):
        yield


def _require_creds(surface: str, scope_keyword: str):
    _skip_unless_opted_in(surface)

    from tools import DEMO_MODE
    if DEMO_MODE:
        pytest.skip(f"DESIR_DEMO=0 required for live {surface} tests")

    creds = _load_or_inject_token()
    if creds is None:
        pytest.skip(
            f"No Workspace credentials — visit /api/workspace/connect to authorize, "
            f"or set WORKSPACE_TOKEN_B64 for Railway."
        )

    from tools.google_auth import granted_scopes
    scopes = " ".join(granted_scopes())
    if scope_keyword not in scopes:
        pytest.skip(
            f"Connected token has no {surface} scope (got: {scopes or 'none'}). "
            f"Re-authorize with ?{surface}=full"
        )
    return creds


# ── OAuth status endpoint ─────────────────────────────────────────────────────


class TestOAuthEndpoints:
    """Test the FastAPI OAuth routes (server.py) without a browser."""

    def test_workspace_status_endpoint(self):
        """GET /api/workspace/status returns valid JSON with connection state."""
        from fastapi.testclient import TestClient
        from server import app

        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/workspace/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "connected" in data
        assert "surfaces" in data
        assert isinstance(data["surfaces"], dict)
        print(f"\n[status] connected={data['connected']} surfaces={data['surfaces']}")

    def test_workspace_connect_redirects_to_google(self):
        """GET /api/workspace/connect redirects to accounts.google.com."""
        import os
        if not os.getenv("GOOGLE_CLIENT_ID"):
            pytest.skip("GOOGLE_CLIENT_ID not set — cannot test OAuth redirect")

        from fastapi.testclient import TestClient
        from server import app

        client = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
        resp = client.get("/api/workspace/connect?drive=file&gmail=read&calendar=manage")
        assert resp.status_code in (302, 307), f"Expected redirect, got {resp.status_code}"
        location = resp.headers.get("location", "")
        assert "accounts.google.com" in location, (
            f"Expected Google auth URL, got: {location!r}"
        )
        print(f"\n[connect] redirects → {location[:80]}…")

    def test_health_endpoint(self):
        """Sanity: /health returns ok."""
        from fastapi.testclient import TestClient
        from server import app

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── Google Drive ──────────────────────────────────────────────────────────────


class TestGoogleDrive:
    """Live Drive tests: create → read → update → read → trash."""

    def test_drive_upload_read_update_trash(self):
        creds = _require_creds("Drive", "drive")
        from tools.google_drive import delete_file, read_file, update_file, upload_file

        name = f"moneypenny-test-{uuid.uuid4().hex[:8]}.txt"
        content = "hello from MoneyPenny integration test"
        file_id = None

        try:
            with _consent("drive.upload"):
                result = upload_file(name, content, creds=creds)
            print(f"\n[drive] upload: {result}")
            assert "file_id=" in result, f"upload didn't return file_id: {result!r}"
            file_id = re.search(r"file_id=(\S+)", result).group(1)

            body = read_file(file_id, creds=creds)
            assert content in body, f"read didn't contain uploaded content: {body!r}"
            print(f"[drive] read OK ({len(body)} chars)")

            with _consent("drive.update"):
                update_file(file_id, "updated content", creds=creds)

            body2 = read_file(file_id, creds=creds)
            assert "updated content" in body2
            print("[drive] update + re-read OK")

        finally:
            if file_id:
                with _consent("drive.delete"):
                    delete_file(file_id, creds=creds, trash=True)
                print(f"[drive] trashed {file_id}")

    def test_drive_list_files(self):
        creds = _require_creds("Drive", "drive")
        from tools.google_drive import list_files

        result = list_files(creds=creds)
        print(f"\n[drive] list_files: {result[:120]}…")
        assert isinstance(result, str) and len(result) > 0

    @pytest.mark.skipif(
        not os.getenv("GOOGLE_TEST_SHARE_EMAIL"),
        reason="Set GOOGLE_TEST_SHARE_EMAIL to test file sharing",
    )
    def test_drive_share(self):
        creds = _require_creds("Drive", "drive")
        from tools.google_drive import delete_file, share_file, upload_file

        target = os.environ["GOOGLE_TEST_SHARE_EMAIL"]
        name = f"moneypenny-share-{uuid.uuid4().hex[:8]}.txt"
        file_id = None
        try:
            with _consent("drive.upload"):
                result = upload_file(name, "share test", creds=creds)
            file_id = re.search(r"file_id=(\S+)", result).group(1)

            with _consent("drive.share"):
                msg = share_file(file_id, target, role="reader", creds=creds)
            assert target in msg
            print(f"\n[drive] shared {file_id} with {target}: {msg}")
        finally:
            if file_id:
                with _consent("drive.delete"):
                    delete_file(file_id, creds=creds, trash=True)


# ── Gmail ─────────────────────────────────────────────────────────────────────


class TestGmail:
    """Live Gmail tests: send-to-self → search → read → triage → draft → trash."""

    def _send_to_self(self, creds, subject: str) -> tuple[str, str]:
        """Send a test email to yourself. Returns (gmail_message_id, email_address)."""
        from googleapiclient.discovery import build
        import base64
        from email.message import EmailMessage

        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        me = svc.users().getProfile(userId="me").execute()["emailAddress"]
        mime = EmailMessage()
        mime["To"] = me
        mime["From"] = me
        mime["Subject"] = subject
        mime.set_content("MoneyPenny integration test message. Safe to delete.")
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()

        # Poll until indexed (Gmail indexing can be async)
        for _ in range(15):
            resp = svc.users().messages().list(userId="me", q=f'subject:"{subject}"').execute()
            msgs = resp.get("messages", [])
            if msgs:
                return msgs[0]["id"], me
            time.sleep(1)
        pytest.fail(f"self-sent message '{subject}' never appeared in Gmail")

    def test_gmail_search_and_read(self):
        creds = _require_creds("Gmail", "gmail")
        from tools.gmail import read_message, search_messages

        subject = f"MoneyPenny IT {uuid.uuid4().hex[:8]}"
        msg_id, me = self._send_to_self(creds, subject)
        try:
            listing = search_messages(f'subject:"{subject}"', creds=creds)
            assert msg_id in listing, f"search didn't include msg_id: {listing!r}"
            print(f"\n[gmail] search found msg_id={msg_id}")

            body = read_message(msg_id, creds=creds)
            assert "integration test message" in body
            print(f"[gmail] read OK ({len(body)} chars)")
        finally:
            from googleapiclient.discovery import build
            from tools.execution_lock import ConsentGrant, consent_scope
            svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
            try:
                svc.users().messages().trash(userId="me", id=msg_id).execute()
            except Exception:
                pass

    def test_gmail_triage(self):
        creds = _require_creds("Gmail", "gmail")
        from tools.gmail import LABEL_INBOX, LABEL_STARRED, LABEL_UNREAD, modify_labels

        subject = f"MoneyPenny Triage {uuid.uuid4().hex[:8]}"
        msg_id, _ = self._send_to_self(creds, subject)
        try:
            with _consent("gmail.modify"):
                modify_labels(msg_id, creds=creds, remove=[LABEL_UNREAD], summary="mark read")
            with _consent("gmail.modify"):
                modify_labels(msg_id, creds=creds, add=[LABEL_STARRED], summary="star")
            with _consent("gmail.modify"):
                modify_labels(msg_id, creds=creds, remove=[LABEL_INBOX], summary="archive")
            print(f"\n[gmail] triage OK — marked read, starred, archived")
        finally:
            from googleapiclient.discovery import build
            svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
            try:
                svc.users().messages().trash(userId="me", id=msg_id).execute()
            except Exception:
                pass

    def test_gmail_draft_and_trash(self):
        creds = _require_creds("Gmail", "gmail")
        from tools.gmail import create_draft, trash_message

        subject = f"MoneyPenny Draft {uuid.uuid4().hex[:8]}"
        msg_id, me = self._send_to_self(creds, subject)
        draft_id = None
        try:
            with _consent("gmail.draft"):
                draft_result = create_draft(me, f"Re: {subject}", "Draft by test.", creds=creds)
            assert "draft_id=" in draft_result
            draft_id = draft_result.split("draft_id=", 1)[1].strip()
            print(f"\n[gmail] draft OK: draft_id={draft_id}")

            with _consent("gmail.trash"):
                trash_message(msg_id, creds=creds)
            print(f"[gmail] trashed msg_id={msg_id}")
        finally:
            if draft_id:
                from googleapiclient.discovery import build
                svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
                try:
                    svc.users().drafts().delete(userId="me", id=draft_id).execute()
                except Exception:
                    pass


# ── Google Calendar ───────────────────────────────────────────────────────────


class TestGoogleCalendar:
    """Live Calendar tests: create → update → freebusy → delete."""

    def test_calendar_roundtrip(self):
        creds = _require_creds("Calendar", "calendar")
        from schemas.agent2 import CalendarRequest
        from tools.calendar import (
            create_calendar_delete,
            create_calendar_event,
            create_calendar_update,
            freebusy_check,
        )

        start = (datetime.now() + timedelta(days=1)).replace(microsecond=0)
        end = start + timedelta(hours=1)
        invite = os.getenv("GOOGLE_TEST_INVITE_EMAIL", "")

        req = CalendarRequest(
            calendarName="primary",
            title="MoneyPenny integration test",
            description="Created by the integration suite. Safe to delete.",
            start=start,
            end=end,
            attendees=[invite] if invite else [],
        )
        event_id = None
        try:
            with _consent("calendar.create"):
                created = create_calendar_event(req, creds=creds)
            m = re.search(r"event_id=(\S+)", created)
            assert m, f"no event_id in: {created!r}"
            event_id = m.group(1)
            print(f"\n[calendar] created event_id={event_id}")

            upd = CalendarRequest(
                calendarName="primary",
                id=event_id,
                title="MoneyPenny integration test (updated)",
            )
            with _consent("calendar.update"):
                upd_msg = create_calendar_update(upd, creds=creds)
            assert event_id in upd_msg
            print(f"[calendar] update OK")

            fb = freebusy_check(
                CalendarRequest(calendarName="primary", start=start, end=end),
                creds=creds,
            )
            assert "primary" in fb.lower() or "busy" in fb.lower()
            print(f"[calendar] freebusy OK: {fb[:80]}")
        finally:
            if event_id:
                with _consent("calendar.delete"):
                    create_calendar_delete(
                        CalendarRequest(calendarName="primary", id=event_id),
                        creds=creds,
                    )
                print(f"[calendar] deleted event_id={event_id}")


# ── Full agent pipeline (LLM + tools) ────────────────────────────────────────


class TestAgentPipeline:
    """Run agent6/agent7 tools directly with live credentials (no LLM call)."""

    def test_agent7_drive_tool_list(self):
        """agent7's list_drive tool returns real Drive content."""
        creds = _require_creds("Drive", "drive")
        from ai.agents.agent7 import get_drive_agent
        from ai.agents.deps import OrchestratorDeps
        from tools.ledger import get_ledger
        from dataclasses import dataclass

        @dataclass
        class _Ctx:
            deps: OrchestratorDeps

        deps = OrchestratorDeps(
            user_id="integration_test",
            knowledge=None,
            execution_log=None,
            ledger=get_ledger(),
            auto_approve=True,
            workspace_creds=creds,
        )
        ctx = _Ctx(deps=deps)

        agent = get_drive_agent()
        list_fn = None
        for ts in agent.toolsets:
            tools = getattr(ts, "tools", {})
            if "search_drive" in tools:
                list_fn = tools["search_drive"].function
                break
        if list_fn is None:
            pytest.skip("search_drive tool not found on agent7")

        import asyncio
        from schemas.agent7 import DriveSearchRequest
        result = asyncio.run(list_fn(ctx, DriveSearchRequest(query="")))
        print(f"\n[agent7] search_drive: {result[:120]}…")
        assert isinstance(result, str) and len(result) > 0
        assert "[DEMO]" not in result, "Got demo mode response — credentials not applied"

    def test_agent6_gmail_search_tool(self):
        """agent6's search_inbox tool returns real Gmail results."""
        creds = _require_creds("Gmail", "gmail")
        from ai.agents.agent6 import get_gmail_agent
        from ai.agents.deps import OrchestratorDeps
        from schemas.agent6 import GmailSearchRequest
        from tools.ledger import get_ledger
        from dataclasses import dataclass

        @dataclass
        class _Ctx:
            deps: OrchestratorDeps

        deps = OrchestratorDeps(
            user_id="integration_test",
            knowledge=None,
            execution_log=None,
            ledger=get_ledger(),
            auto_approve=True,
            workspace_creds=creds,
        )
        ctx = _Ctx(deps=deps)

        agent = get_gmail_agent()
        search_fn = None
        for ts in agent.toolsets:
            tools = getattr(ts, "tools", {})
            if "search_inbox" in tools:
                search_fn = tools["search_inbox"].function
                break
        if search_fn is None:
            pytest.skip("search_inbox tool not found on agent6")

        import asyncio
        req = GmailSearchRequest(query="is:inbox")
        result = asyncio.run(search_fn(ctx, req))
        print(f"\n[agent6] search_inbox: {result[:120]}…")
        assert isinstance(result, str) and len(result) > 0
        assert "[DEMO]" not in result, "Got demo mode response — credentials not applied"
