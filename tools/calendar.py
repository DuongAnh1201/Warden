"""macOS Calendar tools (via AppleScript / osascript).

Each function returns a human-readable string and raises :class:`RuntimeError`
on failure (the calendar agent catches ``RuntimeError``). In :data:`DEMO_MODE`
or off macOS, the actions are simulated so the scheduling flow stays demoable —
a fake but stable event id is returned so the agent can track the event.
"""
from __future__ import annotations

import subprocess
import uuid

from schemas.agent2 import CalendarRequest
from tools import DEMO_MODE, IS_MACOS
from tools.execution_lock import require_consent


def _demo() -> bool:
    return DEMO_MODE or not IS_MACOS


def _osascript(script: str) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=20
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "osascript failed")
    return proc.stdout.strip()


def _applescript_date(dt) -> str:
    """Render a datetime as an AppleScript date expression."""
    # Build the date piece-by-piece to avoid locale-dependent string parsing.
    return (
        'my makeDate(%d, %d, %d, %d, %d)'
        % (dt.year, dt.month, dt.day, dt.hour, dt.minute)
    )


_MAKE_DATE_HANDLER = (
    'on makeDate(y, m, d, hh, mm)\n'
    '  set theDate to current date\n'
    '  set year of theDate to y\n'
    '  set month of theDate to m\n'
    '  set day of theDate to d\n'
    '  set hours of theDate to hh\n'
    '  set minutes of theDate to mm\n'
    '  set seconds of theDate to 0\n'
    '  return theDate\n'
    'end makeDate\n'
)


def calendars() -> str:
    """List available calendar names."""
    if _demo():
        return "Available calendars (demo): Home, Work, tomnguyen6766@gmail.com"
    script = 'tell application "Calendar" to get name of every calendar'
    names = _osascript(script)
    return f"Available calendars: {names}"


def create_calendar_event(req: CalendarRequest) -> str:
    """Create an event. Returns a message including the new event id."""
    require_consent("calendar.create")
    if not req.start or not req.end:
        raise RuntimeError("start and end times are required to create an event")

    if _demo():
        event_id = f"demo-{uuid.uuid4().hex[:8]}"
        return (
            f"[DEMO] Created '{req.title}' on calendar '{req.calendarName}' "
            f"from {req.start} to {req.end}. event_id={event_id}"
        )

    script = (
        f'{_MAKE_DATE_HANDLER}'
        f'tell application "Calendar"\n'
        f'  tell calendar "{req.calendarName}"\n'
        f'    set newEvent to make new event with properties {{summary:"{req.title}", '
        f'start date:{_applescript_date(req.start)}, end date:{_applescript_date(req.end)}, '
        f'description:"{req.description}"}}\n'
        f'    return uid of newEvent\n'
        f'  end tell\n'
        f'end tell'
    )
    uid = _osascript(script)
    return f"Created '{req.title}' from {req.start} to {req.end}. event_id={uid}"


def create_calendar_update(req: CalendarRequest) -> str:
    """Update an existing event identified by ``req.id``."""
    require_consent("calendar.update")
    if _demo():
        return f"[DEMO] Updated event {req.id} ('{req.title}')."

    sets = []
    if req.title:
        sets.append(f'set summary of theEvent to "{req.title}"')
    if req.start:
        sets.append(f"set start date of theEvent to {_applescript_date(req.start)}")
    if req.end:
        sets.append(f"set end date of theEvent to {_applescript_date(req.end)}")
    if req.description:
        sets.append(f'set description of theEvent to "{req.description}"')
    body = "\n      ".join(sets) or "-- nothing to update"

    script = (
        f'{_MAKE_DATE_HANDLER}'
        f'tell application "Calendar"\n'
        f'  tell calendar "{req.calendarName}"\n'
        f'    set theEvent to first event whose uid = "{req.id}"\n'
        f'      {body}\n'
        f'  end tell\n'
        f'end tell\n'
        f'return "ok"'
    )
    _osascript(script)
    return f"Updated event {req.id}."


def create_calendar_delete(req: CalendarRequest) -> str:
    """Delete an event identified by ``req.id``."""
    require_consent("calendar.delete")
    if _demo():
        return f"[DEMO] Deleted event {req.id}."

    script = (
        f'tell application "Calendar"\n'
        f'  tell calendar "{req.calendarName}"\n'
        f'    delete (first event whose uid = "{req.id}")\n'
        f'  end tell\n'
        f'end tell\n'
        f'return "ok"'
    )
    _osascript(script)
    return f"Deleted event {req.id}."


def freebusy_check(req: CalendarRequest) -> str:
    """Report events overlapping the [start, end] window on the calendar."""
    if not req.start or not req.end:
        raise RuntimeError("start and end times are required for a free/busy check")

    if _demo():
        return (
            f"[DEMO] {req.calendarName} appears free between {req.start} and {req.end}."
        )

    script = (
        f'{_MAKE_DATE_HANDLER}'
        f'tell application "Calendar"\n'
        f'  tell calendar "{req.calendarName}"\n'
        f'    set busy to summary of (every event whose start date < '
        f'{_applescript_date(req.end)} and end date > {_applescript_date(req.start)})\n'
        f'  end tell\n'
        f'end tell\n'
        f'return busy'
    )
    busy = _osascript(script)
    if not busy:
        return f"{req.calendarName} is free between {req.start} and {req.end}."
    return f"Busy in that window with: {busy}"
