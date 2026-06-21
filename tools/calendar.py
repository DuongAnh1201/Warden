"""Google Calendar tools (via the Google Calendar API).

Each function returns a human-readable string and raises :class:`RuntimeError`
on failure (the calendar agent catches ``RuntimeError``). When :data:`DEMO_MODE`
is on **or** no Google credentials are available yet, the actions are simulated so
the scheduling flow stays demoable — a stable fake event id is returned so the
agent can track the event.

Credentials come from the user's Workspace OAuth grant (see
``docs/workspace-integration/``). Until that grant is wired up, calendar tools run
in demo mode. Side-effecting tools (create/update/delete) still pass through the
consent gate via :func:`require_consent`, exactly like every other real action.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any

from schemas.agent2 import CalendarRequest
from tools import DEMO_MODE
from tools.execution_lock import require_consent

# Time zone applied to naive datetimes when talking to Google Calendar.
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "America/Los_Angeles")


def _demo(creds: Any) -> bool:
    """Simulate when demo mode is on or we have no Google credentials yet."""
    return DEMO_MODE or creds is None


def _service(creds: Any):
    """Build a Google Calendar v3 service client."""
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _calendar_id(req: CalendarRequest) -> str:
    """Resolve the Google calendarId. The user's email is a valid id for their
    primary calendar; ``primary`` is the safe default."""
    return req.calendarName or "primary"


def _rfc3339(dt: datetime) -> str:
    """Render a datetime as RFC3339. Naive datetimes are treated as UTC."""
    return dt.isoformat() + "Z" if dt.tzinfo is None else dt.isoformat()


def _time_field(dt: datetime) -> dict:
    """Build a Google event start/end object, attaching the configured time zone."""
    return {"dateTime": dt.isoformat(), "timeZone": CALENDAR_TIMEZONE}


def calendars(creds: Any = None) -> str:
    """List available Google calendars (read-only — not gated)."""
    if _demo(creds):
        return "Available calendars (demo): primary, Work, khoiduong2913@gmail.com"
    try:
        items = _service(creds).calendarList().list().execute().get("items", [])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    names = ", ".join(f"{c.get('summary')} ({c.get('id')})" for c in items)
    return f"Available calendars: {names}"


def create_calendar_event(req: CalendarRequest, creds: Any = None) -> str:
    """Create an event. Returns a message including the new event id."""
    require_consent("calendar.create")
    if not req.start or not req.end:
        raise RuntimeError("start and end times are required to create an event")

    if _demo(creds):
        event_id = f"demo-{uuid.uuid4().hex[:8]}"
        return (
            f"[DEMO] Created '{req.title}' on calendar '{_calendar_id(req)}' "
            f"from {req.start} to {req.end}. event_id={event_id}"
        )

    body = {
        "summary": req.title,
        "description": req.description,
        "start": _time_field(req.start),
        "end": _time_field(req.end),
    }
    if req.attendees:
        body["attendees"] = [{"email": e} for e in req.attendees]
    # Send invitations to attendees when there are any; otherwise no notifications.
    send_updates = "all" if req.attendees else "none"
    try:
        event = (
            _service(creds)
            .events()
            .insert(calendarId=_calendar_id(req), body=body, sendUpdates=send_updates)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    invited = f" (invited {', '.join(req.attendees)})" if req.attendees else ""
    return (
        f"Created '{req.title}' from {req.start} to {req.end}{invited}. "
        f"event_id={event.get('id')}"
    )


def create_calendar_update(req: CalendarRequest, creds: Any = None) -> str:
    """Update an existing event identified by ``req.id``."""
    require_consent("calendar.update")
    if _demo(creds):
        return f"[DEMO] Updated event {req.id} ('{req.title}')."

    body: dict = {}
    if req.title:
        body["summary"] = req.title
    if req.description:
        body["description"] = req.description
    if req.start:
        body["start"] = _time_field(req.start)
    if req.end:
        body["end"] = _time_field(req.end)
    try:
        _service(creds).events().patch(
            calendarId=_calendar_id(req), eventId=req.id, body=body
        ).execute()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return f"Updated event {req.id}."


def create_calendar_delete(req: CalendarRequest, creds: Any = None) -> str:
    """Delete an event identified by ``req.id``."""
    require_consent("calendar.delete")
    if _demo(creds):
        return f"[DEMO] Deleted event {req.id}."

    try:
        _service(creds).events().delete(
            calendarId=_calendar_id(req), eventId=req.id
        ).execute()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return f"Deleted event {req.id}."


def freebusy_check(req: CalendarRequest, creds: Any = None) -> str:
    """Report whether the calendar is busy in the [start, end] window (read-only)."""
    if not req.start or not req.end:
        raise RuntimeError("start and end times are required for a free/busy check")

    cid = _calendar_id(req)
    if _demo(creds):
        return f"[DEMO] {cid} appears free between {req.start} and {req.end}."

    body = {
        "timeMin": _rfc3339(req.start),
        "timeMax": _rfc3339(req.end),
        "items": [{"id": cid}],
    }
    try:
        resp = _service(creds).freebusy().query(body=body).execute()
        busy = resp.get("calendars", {}).get(cid, {}).get("busy", [])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    if not busy:
        return f"{cid} is free between {req.start} and {req.end}."
    slots = "; ".join(f"{b.get('start')}–{b.get('end')}" for b in busy)
    return f"Busy in that window: {slots}"
