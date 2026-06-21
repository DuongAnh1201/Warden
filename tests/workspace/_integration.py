"""Helpers for opt-in, live Google Workspace integration tests.

Centralizes the skip gating and the consent-scope shim so the live tests stay
readable. These helpers never touch the network themselves; they just decide
whether a live test should run and provide a real consent grant for gated tools.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from tools.execution_lock import ConsentGrant, consent_scope


def _opted_in() -> bool:
    return os.getenv("RUN_GOOGLE_INTEGRATION", "").strip() in {"1", "true", "True", "yes"}


def _live_creds(surface: str, scope_keyword: str):
    """Return real Workspace credentials for ``surface`` or skip with a clear reason.

    Skips unless: opted in via RUN_GOOGLE_INTEGRATION, demo mode is off, and a
    connected token whose scopes include ``scope_keyword`` exists on disk.
    """
    if not _opted_in():
        pytest.skip(f"set RUN_GOOGLE_INTEGRATION=1 to run live Google {surface} tests")

    from tools import DEMO_MODE

    if DEMO_MODE:
        pytest.skip(f"demo mode is on — set DESIR_DEMO=0 to run live Google {surface} tests")

    from tools.google_auth import get_workspace_credentials, granted_scopes

    creds = get_workspace_credentials()
    if creds is None:
        pytest.skip("no Workspace token — run `python run_text.py --connect` first")

    scopes = " ".join(granted_scopes())
    if scope_keyword not in scopes:
        pytest.skip(f"connected token has no {surface} scope (got: {scopes or 'none'})")
    return creds


def require_live_drive():
    return _live_creds("Drive", "drive")


def require_live_gmail():
    return _live_creds("Gmail", "gmail")


def require_live_calendar():
    return _live_creds("Calendar", "calendar")


def gmail_service(creds):
    """Raw Gmail v1 client for test setup/cleanup (sending the fixture mail, etc.)."""
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def calendar_service(creds):
    """Raw Calendar v3 client (used only for emergency cleanup if a test aborts)."""
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


@contextmanager
def live_consent(action_type: str):
    """Open a real consent scope so gated write tools can run during a live test.

    Mirrors what ``ai.agents.consent.gate`` does after a user approves: it activates
    a single-use, action-scoped grant for the duration of the call.
    """
    grant = ConsentGrant(
        action_id=f"integration-{action_type}",
        action_type=action_type,
        token="integration-token",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
    )
    with consent_scope(grant):
        yield
