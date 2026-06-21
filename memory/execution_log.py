"""Always-on execution log stored in Redis.

Every tool call — gated or not, success or failure — should produce one entry here.
This is the audit trail that answers "what did the assistant actually do and did it work?"

Key: execution_log:{user_id}  (Redis List, newest-first, capped at 1 000 entries)

Entry schema:
  {
    "log_id":   "hex uuid",
    "tool":     "knowledge_base | email | calendar | communication | search",
    "action":   "read_file | save_knowledge | send_email | …",
    "status":   "success" | "failure",
    "message":  "human-readable result or error",
    "metadata": { … extra fields relevant to this action … },
    "ts":       "ISO 8601 UTC"
  }
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import redis as _redis


class ExecutionLog:
    def __init__(self, redis_url: str) -> None:
        self._r = _redis.from_url(redis_url, decode_responses=True)

    async def log(
        self,
        user_id: str,
        tool: str,
        action: str,
        *,
        success: bool,
        message: str,
        **metadata,
    ) -> None:
        entry = json.dumps(
            {
                "log_id": uuid4().hex,
                "tool": tool,
                "action": action,
                "status": "success" if success else "failure",
                "message": message,
                "metadata": metadata,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            default=str,
        )
        key = f"execution_log:{user_id}"
        await asyncio.to_thread(self._r.lpush, key, entry)
        await asyncio.to_thread(self._r.ltrim, key, 0, 999)

    async def get_recent(self, user_id: str, limit: int = 50) -> list[dict]:
        """Return up to `limit` entries, newest first."""
        key = f"execution_log:{user_id}"
        raw: list[str] = await asyncio.to_thread(self._r.lrange, key, 0, limit - 1)
        return [json.loads(x) for x in raw]


# ── Convenience helper (call from any tool/agent) ─────────────────────────────

async def log_execution(
    deps,
    tool: str,
    action: str,
    *,
    success: bool,
    message: str,
    **metadata,
) -> None:
    """Null-safe wrapper — silently skips if execution_log is not wired."""
    el = getattr(deps, "execution_log", None)
    if el is None:
        return
    try:
        await el.log(
            getattr(deps, "user_id", "default"),
            tool,
            action,
            success=success,
            message=message,
            **metadata,
        )
    except Exception:
        pass  # logging must never crash the tool


# ── Singleton ─────────────────────────────────────────────────────────────────

_log: ExecutionLog | None = None


def get_execution_log() -> ExecutionLog:
    global _log
    if _log is None:
        from config import settings
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL is not set — cannot create ExecutionLog")
        _log = ExecutionLog(settings.redis_url)
    return _log
