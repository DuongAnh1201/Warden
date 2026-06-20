"""macOS communication tools — iMessage, phone calls, and Contacts lookup.

``send_imessage`` and ``make_call`` return ``bool`` (success); ``search_contact``
returns a list of ``{"name", "phone"}`` dicts. In :data:`DEMO_MODE` or off macOS
the actions are simulated.
"""
from __future__ import annotations

import subprocess

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


def send_imessage(recipient: str, body: str) -> bool:
    """Send an iMessage. Returns True on success."""
    require_consent("comms.imessage")
    if _demo():
        print(f"[DEMO] iMessage -> {recipient}: {body!r}")
        return True
    try:
        _osascript(
            'tell application "Messages"\n'
            '  set targetService to 1st service whose service type = iMessage\n'
            f'  set targetBuddy to buddy "{recipient}" of targetService\n'
            f'  send "{body}" to targetBuddy\n'
            "end tell"
        )
        return True
    except RuntimeError:
        return False


def make_call(recipient: str) -> bool:
    """Start a phone/FaceTime call. Returns True on success."""
    require_consent("comms.call")
    if _demo():
        print(f"[DEMO] Calling {recipient}...")
        return True
    try:
        subprocess.run(["open", f"tel://{recipient}"], check=True, timeout=20)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def search_contact(name: str) -> list[dict]:
    """Look up a contact by name; returns matches with phone numbers."""
    if _demo():
        return [{"name": name, "phone": "+1 (555) 010-0000 (demo)"}]
    script = (
        'tell application "Contacts"\n'
        f'  set the People to (every person whose name contains "{name}")\n'
        "  set out to {}\n"
        "  repeat with p in the People\n"
        "    repeat with ph in phones of p\n"
        '      set end of out to (name of p) & "|" & (value of ph)\n'
        "    end repeat\n"
        "  end repeat\n"
        '  set AppleScript\'s text item delimiters to "\\n"\n'
        "  return out as text\n"
        "end tell"
    )
    try:
        raw = _osascript(script)
    except RuntimeError:
        return []
    results: list[dict] = []
    for line in filter(None, raw.splitlines()):
        person, _, phone = line.partition("|")
        results.append({"name": person, "phone": phone})
    return results
