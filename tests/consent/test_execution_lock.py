"""Tests for tools/execution_lock.py — the fail-closed wrapper guardrail."""
from __future__ import annotations

import asyncio

import pytest

from tests.consent.conftest import fresh_grant, run
from tools.execution_lock import ConsentError, consent_scope, require_consent


def test_require_consent_blocks_without_active_grant():
    with pytest.raises(ConsentError, match="no active consent grant"):
        require_consent("email.send")


def test_require_consent_succeeds_inside_scope():
    grant = fresh_grant()
    with consent_scope(grant):
        token = require_consent("email.send")
    assert token == "test-token"
    assert grant.consumed is True


def test_require_consent_is_single_use():
    grant = fresh_grant()
    with consent_scope(grant):
        require_consent("email.send")
        with pytest.raises(ConsentError, match="already consumed"):
            require_consent("email.send")


def test_require_consent_rejects_wrong_action_type():
    grant = fresh_grant(action_type="calendar.create")
    with consent_scope(grant):
        with pytest.raises(ConsentError, match="consent was granted for 'calendar.create'"):
            require_consent("email.send")


def test_require_consent_rejects_expired_grant():
    grant = fresh_grant(expired=True)
    with consent_scope(grant):
        with pytest.raises(ConsentError, match="has expired"):
            require_consent("email.send")


def test_consent_scope_does_not_leak_after_exit():
    grant = fresh_grant()
    with consent_scope(grant):
        require_consent("email.send")
    with pytest.raises(ConsentError, match="no active consent grant"):
        require_consent("email.send")


def test_grant_propagates_through_asyncio_to_thread():
    """Mirrors agent tools: gate opens scope, execute runs sync wrapper in a thread."""

    async def _run():
        grant = fresh_grant(action_type="email.send", token="thread-token")
        with consent_scope(grant):
            return await asyncio.to_thread(require_consent, "email.send")

    assert run(_run()) == "thread-token"
