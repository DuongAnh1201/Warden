"""REAL Gmail integration test — opt-in, hits your actual mailbox.

Self-contained and self-cleaning: it sends a uniquely-tagged email to *yourself*,
then exercises the product tools against it, then trashes everything it created.
No external recipient is ever contacted.

Gating (all must hold, else skipped):
  1. ``RUN_GOOGLE_INTEGRATION=1``,
  2. ``DESIR_DEMO=0``,
  3. a connected token with a Gmail scope (``gmail.modify`` is needed for triage,
     and this test also sends a fixture mail to self, which needs ``gmail.send``).

Run (PowerShell):
    $env:DESIR_DEMO="0"; $env:RUN_GOOGLE_INTEGRATION="1"
    uv run pytest tests/workspace/test_google_gmail_integration.py -v -s

Flow: send-to-self -> search -> read -> mark read/star/archive (gated) ->
create draft (gated) -> trash message + clean draft.
"""
from __future__ import annotations

import base64
import time
import uuid
from email.message import EmailMessage

import pytest

from tests.workspace._integration import gmail_service, live_consent, require_live_gmail

pytestmark = pytest.mark.integration


def _send_self(svc, subject: str) -> str:
    """Send a fixture email to the authenticated user. Returns the address used."""
    me = svc.users().getProfile(userId="me").execute()["emailAddress"]
    mime = EmailMessage()
    mime["To"] = me
    mime["From"] = me
    mime["Subject"] = subject
    mime.set_content("This is a MoneyPenny integration-test message. Safe to delete.")
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    return me


def _find(svc, subject: str, attempts: int = 10) -> str:
    """Poll search until the self-sent message is indexed; return its message id."""
    for _ in range(attempts):
        resp = svc.users().messages().list(userId="me", q=f'subject:"{subject}"').execute()
        msgs = resp.get("messages", [])
        if msgs:
            return msgs[0]["id"]
        time.sleep(1.5)
    raise AssertionError(f"self-sent message with subject {subject!r} never appeared")


def test_gmail_roundtrip():
    creds = require_live_gmail()
    from tools.gmail import (
        LABEL_INBOX,
        LABEL_STARRED,
        LABEL_UNREAD,
        create_draft,
        modify_labels,
        read_message,
        search_messages,
        trash_message,
    )

    svc = gmail_service(creds)
    subject = f"MoneyPenny IT {uuid.uuid4().hex[:8]}"
    me = _send_self(svc, subject)
    msg_id = _find(svc, subject)
    draft_id = None
    try:
        # Reads (free).
        listing = search_messages(f'subject:"{subject}"', creds=creds)
        assert msg_id in listing
        body = read_message(msg_id, creds=creds)
        assert "integration-test message" in body

        # Triage (gated): mark read, star, archive — one grant per action.
        with live_consent("gmail.modify"):
            modify_labels(msg_id, creds=creds, remove=[LABEL_UNREAD], summary="mark read")
        with live_consent("gmail.modify"):
            modify_labels(msg_id, creds=creds, add=[LABEL_STARRED], summary="star")
        with live_consent("gmail.modify"):
            modify_labels(msg_id, creds=creds, remove=[LABEL_INBOX], summary="archive")

        # Confirm the label changes landed.
        meta = svc.users().messages().get(userId="me", id=msg_id, format="minimal").execute()
        labels = meta.get("labelIds", [])
        assert LABEL_UNREAD not in labels
        assert LABEL_STARRED in labels
        assert LABEL_INBOX not in labels

        # Draft (gated) — created, not sent.
        with live_consent("gmail.draft"):
            draft_msg = create_draft(me, f"Re: {subject}", "Drafted by the test.", creds=creds)
        assert "draft_id=" in draft_msg
        draft_id = draft_msg.split("draft_id=", 1)[1].strip()

        # Trash the message (gated).
        with live_consent("gmail.trash"):
            trash_message(msg_id, creds=creds)
        meta2 = svc.users().messages().get(userId="me", id=msg_id, format="minimal").execute()
        assert "TRASH" in meta2.get("labelIds", [])
    finally:
        # Clean up the draft we created (not a product tool — direct API).
        if draft_id:
            try:
                svc.users().drafts().delete(userId="me", id=draft_id).execute()
            except Exception:  # noqa: BLE001
                pass
