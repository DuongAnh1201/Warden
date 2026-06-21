"""Tests that physical tool wrappers fail closed without gate consent."""
from __future__ import annotations

import asyncio

import pytest

from tests.consent.conftest import fresh_grant, run
from tools.execution_lock import ConsentError, consent_scope
from tools.gmail import send_message


def test_send_message_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        send_message("priya@example.com", "Hi", "body")


def test_send_message_succeeds_inside_consent_scope():
    grant = fresh_grant(action_type="email.send")

    async def _run():
        with consent_scope(grant):
            return await asyncio.to_thread(
                send_message,
                "priya@example.com",
                "Hi",
                "body",
            )

    # Demo mode (no creds) simulates the send and returns without raising.
    assert "priya@example.com" in run(_run())
