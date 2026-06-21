"""Gmail tools — reading, searching, and triaging the user's inbox.

Two risk classes, handled differently:

* **Reads** (:func:`search_messages`, :func:`read_message`) have no side effect and
  are **not gated** — the agent may call them freely.
* **Triage** (:func:`modify_labels`, :func:`create_draft`, :func:`trash_message`)
  changes mailbox state and therefore calls :func:`require_consent` and flows
  through the consent gate, exactly like every other real-world action.

When :data:`DEMO_MODE` is on **or** no Google credentials are available, the
actions are simulated so the flow stays demoable. Credentials come from the
user's Workspace OAuth grant (see ``docs/workspace-integration/``).
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from tools import DEMO_MODE
from tools.execution_lock import require_consent

# Gmail system label ids used by triage helpers.
LABEL_UNREAD = "UNREAD"
LABEL_INBOX = "INBOX"
LABEL_STARRED = "STARRED"


def _demo(creds: Any) -> bool:
    """Simulate when demo mode is on or we have no Google credentials yet."""
    return DEMO_MODE or creds is None


def _service(creds: Any):
    """Build a Gmail v1 service client."""
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ── Reads (no side effect, NOT gated) ────────────────────────────────────────────

def search_messages(query: str, creds: Any = None, max_results: int = 10) -> str:
    """Search the inbox. Returns a human-readable list of matching messages."""
    if _demo(creds):
        return (
            "[DEMO] 2 messages matching "
            f"{query!r}:\n"
            "  • id=demo-1 | Priya Nair <priya@example.com> | 'Deck is ready' "
            "| unread | \"Hi, the deck looks great — one note on slide 4…\"\n"
            "  • id=demo-2 | Acme Billing <billing@acme.com> | 'Invoice #4821' "
            "| read | \"Your invoice for June is attached…\""
        )
    try:
        svc = _service(creds)
        listing = (
            svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        ids = [m["id"] for m in listing.get("messages", [])]
        lines: list[str] = []
        for mid in ids:
            msg = (
                svc.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
            headers = msg.get("payload", {}).get("headers", [])
            unread = "UNREAD" in msg.get("labelIds", [])
            lines.append(
                f"  • id={mid} | {_header(headers, 'From')} | "
                f"'{_header(headers, 'Subject')}' | "
                f"{'unread' if unread else 'read'} | {msg.get('snippet', '')!r}"
            )
    except Exception as e:  # noqa: BLE001
        return f"Failed to search inbox: {e}"
    if not lines:
        return f"No messages matched {query!r}."
    return f"{len(lines)} messages matching {query!r}:\n" + "\n".join(lines)


def read_message(message_id: str, creds: Any = None) -> str:
    """Read a single message's full content. Returns a human-readable rendering."""
    if _demo(creds):
        return (
            f"[DEMO] Message {message_id}\n"
            "From: Priya Nair <priya@example.com>\n"
            "Subject: Deck is ready\n"
            "Date: Sat, 20 Jun 2026 10:12:00 -0700\n\n"
            "Hi! The deck looks great — one note on slide 4: can we swap the chart "
            "for the updated Q2 numbers? Thanks!"
        )
    try:
        svc = _service(creds)
        msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        body = _extract_body(payload)
    except Exception as e:  # noqa: BLE001
        return f"Failed to read message {message_id}: {e}"
    return (
        f"Message {message_id}\n"
        f"From: {_header(headers, 'From')}\n"
        f"To: {_header(headers, 'To')}\n"
        f"Subject: {_header(headers, 'Subject')}\n"
        f"Date: {_header(headers, 'Date')}\n\n"
        f"{body}"
    )


def _extract_body(payload: dict) -> str:
    """Pull the text/plain body out of a Gmail message payload."""
    def _decode(data: str) -> str:
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", "replace")

    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return _decode(data)
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return _decode(data)
        nested = _extract_body(part)
        if nested:
            return nested
    return "(no plain-text body)"


# ── Triage (state-changing, GATED via require_consent) ───────────────────────────

def modify_labels(
    message_id: str,
    creds: Any = None,
    *,
    add: list[str] | None = None,
    remove: list[str] | None = None,
    summary: str = "modify labels",
) -> str:
    """Add/remove labels on a message (mark read, archive, star, label…)."""
    require_consent("gmail.modify")
    add = add or []
    remove = remove or []
    if _demo(creds):
        return f"[DEMO] {summary} on message {message_id} (add={add}, remove={remove})."
    try:
        _service(creds).users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": add, "removeLabelIds": remove},
        ).execute()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return f"{summary} on message {message_id}."


def send_message(
    to: str,
    subject: str,
    body: str,
    creds: Any = None,
    html: str = "",
    cc: list[str] | None = None,
) -> str:
    """Send an email from the user's Gmail account. Returns 'ok' or an error string."""
    require_consent("email.send")
    if _demo(creds):
        return f"[DEMO] Email to {to} — subject '{subject}' (not sent)."
    try:
        mime = EmailMessage()
        mime["To"] = to
        mime["Subject"] = subject
        if cc:
            mime["Cc"] = ", ".join(cc)
        mime.set_content(body)
        if html:
            mime.add_alternative(html, subtype="html")
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        _service(creds).users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"gmail error: {e}"


def create_draft(to: str, subject: str, body: str, creds: Any = None) -> str:
    """Create a draft reply/message. A draft is NOT sent — it stays in the mailbox."""
    require_consent("gmail.draft")
    if _demo(creds):
        return f"[DEMO] Draft created to {to} — subject '{subject}' (not sent)."
    try:
        mime = EmailMessage()
        mime["To"] = to
        mime["Subject"] = subject
        mime.set_content(body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        draft = (
            _service(creds)
            .users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return f"Draft created to {to} — subject '{subject}'. draft_id={draft.get('id')}"


def trash_message(message_id: str, creds: Any = None) -> str:
    """Move a message to Trash (recoverable for ~30 days, but user-visible state change)."""
    require_consent("gmail.trash")
    if _demo(creds):
        return f"[DEMO] Moved message {message_id} to Trash."
    try:
        _service(creds).users().messages().trash(userId="me", id=message_id).execute()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return f"Moved message {message_id} to Trash."
