"""Tests that physical tool wrappers fail closed without gate consent."""
from __future__ import annotations

import asyncio

import pytest

from tests.consent.conftest import fresh_grant, run
from tools.execution_lock import ConsentError, consent_scope
from tools.sending_email import send_user_email


def test_send_user_email_blocked_without_consent():
    with pytest.raises(ConsentError, match="no active consent grant"):
        send_user_email("priya@example.com", "Hi", "body", api_key="")


def test_send_user_email_succeeds_inside_consent_scope():
    grant = fresh_grant(action_type="email.send")

    async def _run():
        with consent_scope(grant):
            return await asyncio.to_thread(
                send_user_email,
                "priya@example.com",
                "Hi",
                "body",
                "",
            )

    assert run(_run()) == "ok"
