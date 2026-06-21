"""Redis bridge — cross-process request-response between FastAPI and the uAgent.

FastAPI side  : enqueue_agent_request() → await_agent_response()
uAgent side   : pop_outbound_request()  → post_agent_response()

All keys use the prefix  desir:agent:  to avoid collisions.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

OUTBOUND_KEY = "desir:agent:outbound"
RESPONSE_PREFIX = "desir:agent:response:"
RESPONSE_TTL = 120  # seconds before an uncollected response is evicted


def _redis():
    from config import settings
    import redis.asyncio as aioredis
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=35,      # must exceed max blpop timeout (30 s) to avoid race
        retry_on_timeout=True,
    )


async def enqueue_agent_request(address: str, text: str, correlation_id: str) -> None:
    """FastAPI side: push a send-task to Redis for the uAgent to pick up."""
    r = _redis()
    await r.rpush(OUTBOUND_KEY, json.dumps({
        "address": address,
        "text": text,
        "correlation_id": correlation_id,
    }))
    logger.info("[bridge] enqueued → %s (corr=%s)", address[:20], correlation_id[:8])
    await r.aclose()


async def await_agent_response(correlation_id: str, timeout: float = 30.0) -> dict:
    """FastAPI side: block until the uAgent posts a response for correlation_id."""
    r = _redis()
    key = f"{RESPONSE_PREFIX}{correlation_id}"
    logger.info("[bridge] waiting for response corr=%s (timeout=%ss)", correlation_id[:8], timeout)
    result = await r.blpop(key, timeout=int(timeout))
    await r.aclose()
    if result is None:
        raise TimeoutError(
            f"No response from remote agent within {timeout}s "
            f"(correlation_id={correlation_id})"
        )
    _, payload = result
    data = json.loads(payload)
    logger.info("[bridge] response received corr=%s success=%s", correlation_id[:8], data.get("success"))
    return data


async def pop_outbound_request(r) -> dict | None:
    """uAgent side: non-blocking pop of one outbound task."""
    item = await r.lpop(OUTBOUND_KEY)
    if item is None:
        return None
    return json.loads(item)


async def post_agent_response(r, correlation_id: str, text: str, success: bool = True) -> None:
    """uAgent side: write the response so FastAPI can collect it."""
    key = f"{RESPONSE_PREFIX}{correlation_id}"
    await r.rpush(key, json.dumps({"text": text, "success": success}))
    await r.expire(key, RESPONSE_TTL)
    logger.info("[bridge] posted response corr=%s success=%s", correlation_id[:8], success)
