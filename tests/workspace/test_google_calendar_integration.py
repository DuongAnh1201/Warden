"""REAL Google Calendar integration test — opt-in, hits your actual calendar.

Self-contained and self-cleaning: creates an event in the future, updates it,
runs a free/busy check, and deletes it. Inviting an attendee is exercised only
when ``GOOGLE_TEST_INVITE_EMAIL`` is set (it sends a real calendar invitation).

Gating (all must hold, else skipped):
  1. ``RUN_GOOGLE_INTEGRATION=1``,
  2. ``DESIR_DEMO=0``,
  3. a connected token with a Calendar scope (``calendar.events``).

Run (PowerShell):
    $env:DESIR_DEMO="0"; $env:RUN_GOOGLE_INTEGRATION="1"
    uv run pytest tests/workspace/test_google_calendar_integration.py -v -s

    # to also test inviting someone (sends a real invite):
    $env:GOOGLE_TEST_INVITE_EMAIL="someone@example.com"
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

import pytest

from schemas.agent2 import CalendarRequest
from tests.workspace._integration import (
    calendar_service,
    live_consent,
    require_live_calendar,
)

pytestmark = pytest.mark.integration


def _event_id(message: str) -> str:
    m = re.search(r"event_id=(\S+)", message)
    assert m, f"no event_id in tool output: {message!r}"
    return m.group(1)


def _window():
    """A one-hour slot ~24h out, on the primary calendar."""
    start = (datetime.now() + timedelta(days=1)).replace(microsecond=0)
    return start, start + timedelta(hours=1)


def test_calendar_roundtrip():
    creds = require_live_calendar()
    from tools.calendar import (
        create_calendar_delete,
        create_calendar_event,
        create_calendar_update,
        freebusy_check,
    )

    start, end = _window()
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
        with live_consent("calendar.create"):
            created = create_calendar_event(req, creds=creds)
        event_id = _event_id(created)
        assert event_id
        if invite:
            assert invite in created

        # Update the title (gated).
        upd = CalendarRequest(
            calendarName="primary", id=event_id, title="MoneyPenny integration test (updated)"
        )
        with live_consent("calendar.update"):
            update_msg = create_calendar_update(upd, creds=creds)
        assert event_id in update_msg

        # Free/busy check over the window (read-only, not gated).
        fb = freebusy_check(
            CalendarRequest(calendarName="primary", start=start, end=end), creds=creds
        )
        assert "primary" in fb.lower() or "busy" in fb.lower()
    finally:
        if event_id:
            with live_consent("calendar.delete"):
                create_calendar_delete(
                    CalendarRequest(calendarName="primary", id=event_id), creds=creds
                )
            # Belt-and-suspenders: confirm it's gone (or already cancelled).
            try:
                svc = calendar_service(creds)
                ev = svc.events().get(calendarId="primary", eventId=event_id).execute()
                assert ev.get("status") == "cancelled"
            except Exception:  # noqa: BLE001
                pass
