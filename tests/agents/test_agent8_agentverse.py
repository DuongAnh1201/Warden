"""Tests for agent8 — Agentverse agent (discover + message remote agents)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ai.agents.agent8 import get_agentverse_agent
from tests.agents.conftest import get_tool, run

DEMO_ADDR = "agent1qf4au9zkaaazklxyyj5gxu6c5vvdwu0rwmvwmkrg72c5wsjdnxskxqdgve"


# ── discover_agents ───────────────────────────────────────────────────────────

def test_discover_agents_returns_results(ctx):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "agents": [
            {
                "name": "WeatherAgent",
                "address": DEMO_ADDR,
                "readme": "Provides real-time weather data for any city.",
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    fn = get_tool(get_agentverse_agent, "discover_agents")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        result = run(fn(ctx, "weather"))

    assert "WeatherAgent" in result
    assert DEMO_ADDR in result


def test_discover_agents_empty(ctx):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"agents": []}
    mock_resp.raise_for_status = MagicMock()

    fn = get_tool(get_agentverse_agent, "discover_agents")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        result = run(fn(ctx, "unicorn_capability_xyz"))

    assert "No agents found" in result


def test_discover_agents_http_error(ctx):
    mock_request = MagicMock()
    mock_response = MagicMock(status_code=500, text="Internal Server Error")
    http_error = httpx.HTTPStatusError("500", request=mock_request, response=mock_response)

    fn = get_tool(get_agentverse_agent, "discover_agents")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=http_error):
        result = run(fn(ctx, "weather"))

    assert "Could not search" in result or "error" in result.lower()


def test_discover_agents_network_error(ctx):
    fn = get_tool(get_agentverse_agent, "discover_agents")
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=httpx.RequestError("timeout"),
    ):
        result = run(fn(ctx, "weather"))
    assert "Could not search" in result or "error" in result.lower()


# ── message_agent ─────────────────────────────────────────────────────────────

def test_message_agent_no_redis_blocked(ctx):
    """Without REDIS_URL, returns a clear 'bridge unavailable' message."""
    from unittest.mock import MagicMock
    import config

    orig = config.settings.redis_url
    try:
        config.settings.redis_url = ""
        fn = get_tool(get_agentverse_agent, "message_agent")
        result = run(fn(ctx, address=DEMO_ADDR, message="What's the weather in SF?"))
        assert "Redis" in result or "unavailable" in result.lower()
    finally:
        config.settings.redis_url = orig


def test_message_agent_approved_and_gets_reply(ctx, ledger):
    """With Redis bridge mocked, the full round-trip returns the remote agent's reply."""
    import config

    orig = config.settings.redis_url
    try:
        config.settings.redis_url = "redis://mock"

        with (
            patch("ai.transport.bridge.enqueue_agent_request", new_callable=AsyncMock),
            patch(
                "ai.transport.bridge.await_agent_response",
                new_callable=AsyncMock,
                return_value={"text": "ECHO: What's the weather in SF?", "success": True},
            ),
        ):
            fn = get_tool(get_agentverse_agent, "message_agent")
            result = run(fn(ctx, address=DEMO_ADDR, message="What's the weather in SF?"))

        assert "ECHO" in result or "weather" in result.lower()
    finally:
        config.settings.redis_url = orig


def test_message_agent_timeout(ctx, ledger):
    """Timeout from the remote agent returns a graceful message, not an exception."""
    import config

    orig = config.settings.redis_url
    try:
        config.settings.redis_url = "redis://mock"

        with (
            patch("ai.transport.bridge.enqueue_agent_request", new_callable=AsyncMock),
            patch(
                "ai.transport.bridge.await_agent_response",
                new_callable=AsyncMock,
                side_effect=TimeoutError("30s timeout"),
            ),
        ):
            fn = get_tool(get_agentverse_agent, "message_agent")
            result = run(fn(ctx, address=DEMO_ADDR, message="Hello?"))

        assert "No reply" in result or "offline" in result.lower() or "timeout" in result.lower()
    finally:
        config.settings.redis_url = orig


def test_message_agent_remote_error(ctx, ledger):
    """Remote agent returning success=False is surfaced as an error message."""
    import config

    orig = config.settings.redis_url
    try:
        config.settings.redis_url = "redis://mock"

        with (
            patch("ai.transport.bridge.enqueue_agent_request", new_callable=AsyncMock),
            patch(
                "ai.transport.bridge.await_agent_response",
                new_callable=AsyncMock,
                return_value={"text": "Agent overloaded", "success": False},
            ),
        ):
            fn = get_tool(get_agentverse_agent, "message_agent")
            result = run(fn(ctx, address=DEMO_ADDR, message="Query"))

        assert "error" in result.lower() or "overloaded" in result.lower()
    finally:
        config.settings.redis_url = orig


def test_message_agent_cancelled(ctx, ledger):
    """Cancelling the consent gate returns without sending."""
    import config
    from schemas.consent import ActionDecision, ActionRequest

    async def cancel(req: ActionRequest) -> ActionDecision:
        return ActionDecision(action_id=req.action_id, decision="cancel")

    ctx.deps.auto_approve = False
    ctx.deps.request_approval = cancel

    orig = config.settings.redis_url
    try:
        config.settings.redis_url = "redis://mock"
        fn = get_tool(get_agentverse_agent, "message_agent")
        result = run(fn(ctx, address=DEMO_ADDR, message="Hello"))
        assert "Cancelled" in result or "cancel" in result.lower()
    finally:
        config.settings.redis_url = orig
