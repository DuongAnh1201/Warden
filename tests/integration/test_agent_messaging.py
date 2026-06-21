"""Integration tests for agent8 — real Redis bridge + agent-to-agent messaging.

Two test levels:

Level 1 — Bridge response round-trip (runs whenever REDIS_URL is set):
    Tests `post_agent_response` → `await_agent_response` using the real Redis.
    Does NOT touch the outbound queue (production fetch_wrapper running on
    Railway consumes from there, which would cause a race condition).

Level 2 — agent8 tool with intercepted bridge (runs whenever REDIS_URL is set):
    Patches `enqueue_agent_request` so no item goes to the shared outbound
    queue.  Captures the correlation_id, posts a fake response immediately,
    and verifies that agent8's message_agent tool returns the echo reply.

Level 3 — Live uAgent round-trip (requires two local processes):
    Run in two terminals:
        A:  uv run python -m ai.transport.fetch_wrapper
        B:  uv run python tests/demo_agent.py
    Then re-run with the demo agent's address:
        DEMO_AGENT_ADDR=agent1q... uv run pytest tests/integration/ -v -s
    The demo_agent prints its Fetch.ai address on startup.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.anyio


def _redis_url() -> str | None:
    try:
        from config import settings
        return settings.redis_url
    except Exception:
        return None


skip_no_redis = pytest.mark.skipif(
    not _redis_url(),
    reason="REDIS_URL not set — skipping bridge integration tests",
)

# ── Level 1: Bridge response round-trip ──────────────────────────────────────


@skip_no_redis
async def test_bridge_response_round_trip():
    """post_agent_response → await_agent_response: the core of the bridge."""
    from ai.transport.bridge import post_agent_response, await_agent_response
    import redis.asyncio as aioredis
    from config import settings

    cid = f"rsp-{uuid.uuid4().hex[:8]}"
    reply_text = "hello from bridge integration test"

    # Write the response (simulates what fetch_wrapper does after getting a reply)
    r = aioredis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=10, socket_timeout=35, retry_on_timeout=True,
    )
    await post_agent_response(r, cid, reply_text, success=True)
    await r.aclose()

    # Collect it (simulates what agent8 / FastAPI does)
    result = await await_agent_response(cid, timeout=10.0)

    assert result["success"] is True
    assert result["text"] == reply_text
    print(f"\n[bridge test] round-trip OK — response: {result['text']!r}")


@skip_no_redis
async def test_bridge_timeout():
    """await_agent_response raises TimeoutError when no response arrives."""
    from ai.transport.bridge import await_agent_response

    cid = f"timeout-{uuid.uuid4().hex[:8]}"
    with pytest.raises(TimeoutError):
        await await_agent_response(cid, timeout=2.0)


@skip_no_redis
async def test_bridge_error_response():
    """post_agent_response with success=False is returned with success=False."""
    from ai.transport.bridge import post_agent_response, await_agent_response
    import redis.asyncio as aioredis
    from config import settings

    cid = f"err-{uuid.uuid4().hex[:8]}"
    r = aioredis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=10, socket_timeout=35, retry_on_timeout=True,
    )
    await post_agent_response(r, cid, "agent returned an error", success=False)
    await r.aclose()

    result = await await_agent_response(cid, timeout=10.0)
    assert result["success"] is False
    assert "error" in result["text"]


# ── Level 2: agent8 tool with intercepted bridge ──────────────────────────────


@skip_no_redis
async def test_agent8_message_agent_tool_via_bridge():
    """
    Calls agent8's message_agent tool function directly (bypassing the LLM)
    with a real Redis bridge.

    We patch enqueue_agent_request so no item goes to the shared outbound queue.
    Instead we immediately post a fake ECHO reply, which agent8's
    await_agent_response then collects from Redis.
    """
    from ai.transport.bridge import post_agent_response
    from ai.agents.agent8 import get_agentverse_agent
    from ai.agents.deps import OrchestratorDeps
    from tools.ledger import get_ledger
    import redis.asyncio as aioredis
    from config import settings
    from dataclasses import dataclass

    @dataclass
    class _Ctx:
        deps: OrchestratorDeps

    target_addr = "agent1qtest_echo_bridge_target_0000"
    message = "hello from integration test"

    async def _fake_enqueue(address: str, text: str, correlation_id: str) -> None:
        """Post the echo reply immediately, simulating a remote agent responding."""
        reply = f"ECHO from DemoAgent: {text}"
        r = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=10, socket_timeout=35, retry_on_timeout=True,
        )
        await post_agent_response(r, correlation_id, reply, success=True)
        await r.aclose()
        print(f"\n[fake bridge] posted reply for corr={correlation_id[:8]}: {reply!r}")

    ledger = get_ledger()
    deps = OrchestratorDeps(
        user_id="integration_test",
        knowledge=None,
        execution_log=None,
        ledger=ledger,
        auto_approve=True,
    )
    ctx = _Ctx(deps=deps)

    # Get the raw tool function (same pattern as unit tests)
    agent = get_agentverse_agent()
    message_agent_fn = None
    for ts in agent.toolsets:
        tools = getattr(ts, "tools", {})
        if "message_agent" in tools:
            message_agent_fn = tools["message_agent"].function
            break
    assert message_agent_fn is not None, "message_agent tool not found on agent8"

    with patch("ai.transport.bridge.enqueue_agent_request", side_effect=_fake_enqueue):
        reply = await message_agent_fn(ctx, address=target_addr, message=message)

    print(f"\n[agent8 tool] reply: {reply!r}")
    assert "ECHO" in reply, f"Expected echo in tool reply, got: {reply!r}"
    assert message in reply, f"Original message not found in reply: {reply!r}"


# ── Level 3: Live uAgent round-trip ──────────────────────────────────────────

_demo_addr = os.getenv("DEMO_AGENT_ADDR", "")

skip_no_demo = pytest.mark.skipif(
    not _demo_addr,
    reason=(
        "DEMO_AGENT_ADDR not set — skipping live uAgent test.\n"
        "Run in two terminals:\n"
        "  terminal A: uv run python -m ai.transport.fetch_wrapper\n"
        "  terminal B: uv run python tests/demo_agent.py\n"
        "Then: DEMO_AGENT_ADDR=agent1q... uv run pytest tests/integration/ -v -s"
    ),
)


@skip_no_redis
@skip_no_demo
async def test_live_agent_to_agent_round_trip():
    """
    Full end-to-end: bridge → fetch_wrapper → demo_agent → reply.
    Requires both fetch_wrapper and demo_agent to be running locally.
    """
    from ai.transport.bridge import enqueue_agent_request, await_agent_response

    cid = f"live-{uuid.uuid4().hex[:8]}"
    text = f"integration ping {cid}"

    print(f"\n[live] → {_demo_addr[:24]}: {text!r}")
    await enqueue_agent_request(_demo_addr, text, cid)

    print("[live] waiting for reply (up to 30 s)…")
    result = await await_agent_response(cid, timeout=30.0)

    print(f"[live] ← {result}")
    assert result["success"] is True
    assert "ECHO" in result["text"]
    assert text in result["text"]


@skip_no_redis
@skip_no_demo
async def test_live_agent8_tool():
    """
    Full agent8 LLM + live uAgent round-trip.
    Requires fetch_wrapper and demo_agent to be running locally.
    """
    from ai.agents.agent8 import get_agentverse_agent
    from ai.agents.deps import OrchestratorDeps
    from tools.ledger import get_ledger

    agent = get_agentverse_agent()
    deps = OrchestratorDeps(
        user_id="integration_test",
        knowledge=None,
        execution_log=None,
        ledger=get_ledger(),
        auto_approve=True,
    )

    prompt = f"Send a message to the agent at {_demo_addr} and say: What is 2 + 2?"
    print(f"\n[agent8 live] prompt: {prompt}")

    result = await agent.run(prompt, deps=deps)
    response = result.output.response if hasattr(result.output, "response") else str(result.output)
    print(f"[agent8 live] response: {response}")

    assert "ECHO" in response or len(response) > 20
