"""Consent ledger — append-only record of every gated action.

Two backends behind one interface:
  FileLedger   — appends JSON lines to .consent/ledger.jsonl  (local/demo, zero deps)
  RedisLedger  — appends to a Redis Stream  (production; requires REDIS_URL in .env)

get_ledger() returns a singleton: RedisLedger when REDIS_URL is set, else FileLedger.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from schemas.consent import ActionDecision, ActionRequest, LedgerEntry, Outcome


@runtime_checkable
class ConsentLedger(Protocol):
    async def record_request(self, req: ActionRequest) -> None: ...
    async def record_decision(self, d: ActionDecision) -> None: ...
    async def record_outcome(
        self, action_id: str, outcome: Outcome, message: str
    ) -> None: ...
    async def history(self, limit: int = 50) -> list[LedgerEntry]: ...
    async def lookup(self, action_id: str) -> LedgerEntry | None: ...


# ── File-backed ledger ─────────────────────────────────────────────────────────

class FileLedger:
    """JSONL-based ledger stored in .consent/ledger.jsonl (gitignored)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path(".consent/ledger.jsonl")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        # In-memory index: action_id -> LedgerEntry (for history + updates)
        self._index: dict[str, LedgerEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if row.get("type") == "request":
                    req = ActionRequest.model_validate(row["data"])
                    self._index[req.action_id] = LedgerEntry(request=req)
                elif row.get("type") == "decision":
                    d = ActionDecision.model_validate(row["data"])
                    if d.action_id in self._index:
                        self._index[d.action_id].decision = d
                elif row.get("type") == "outcome":
                    aid = row["action_id"]
                    if aid in self._index:
                        entry = self._index[aid]
                        entry.outcome = row["outcome"]
                        entry.result_message = row["message"]
                        entry.resolved_at = datetime.fromisoformat(row["resolved_at"])
            except Exception:  # noqa: BLE001 — malformed line, skip
                continue

    def _append(self, row: dict) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    async def record_request(self, req: ActionRequest) -> None:
        async with self._lock:
            self._index[req.action_id] = LedgerEntry(request=req)
            self._append({"type": "request", "data": req.model_dump(mode="json")})

    async def record_decision(self, d: ActionDecision) -> None:
        async with self._lock:
            if d.action_id in self._index:
                self._index[d.action_id].decision = d
            self._append({"type": "decision", "data": d.model_dump(mode="json")})

    async def record_outcome(
        self, action_id: str, outcome: Outcome, message: str
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self._lock:
            if action_id in self._index:
                entry = self._index[action_id]
                entry.outcome = outcome
                entry.result_message = message
                entry.resolved_at = now
            self._append(
                {
                    "type": "outcome",
                    "action_id": action_id,
                    "outcome": outcome,
                    "message": message,
                    "resolved_at": now.isoformat(),
                }
            )

    async def history(self, limit: int = 50) -> list[LedgerEntry]:
        entries = list(self._index.values())
        entries.sort(key=lambda e: e.request.created_at)
        return entries[-limit:]

    async def lookup(self, action_id: str) -> LedgerEntry | None:
        return self._index.get(action_id)


# ── Redis-backed ledger ────────────────────────────────────────────────────────

class RedisLedger:
    """Redis Streams ledger. Requires `redis[asyncio]` in dependencies."""

    STREAM = "consent:ledger"

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis  # lazy import

        self._redis = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=False,
        )
        # In-process fallback used when Redis is unreachable.
        self._fallback = FileLedger()
        # action_ids whose first write went to the fallback — all subsequent
        # ops for the same id stay there to prevent split-brain inconsistency.
        self._fallback_ids: set[str] = set()

    async def _xadd(self, fields: dict) -> None:
        try:
            await self._redis.xadd(self.STREAM, fields)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "ledger: Redis unavailable (%s) — using file fallback", exc
            )
            raise

    async def record_request(self, req: ActionRequest) -> None:
        try:
            await self._xadd({"type": "request", "data": req.model_dump_json()})
        except Exception:
            self._fallback_ids.add(req.action_id)
            await self._fallback.record_request(req)

    async def record_decision(self, d: ActionDecision) -> None:
        if d.action_id in self._fallback_ids:
            await self._fallback.record_decision(d)
            return
        try:
            await self._xadd({"type": "decision", "data": d.model_dump_json()})
        except Exception:
            self._fallback_ids.add(d.action_id)
            await self._fallback.record_decision(d)

    async def record_outcome(
        self, action_id: str, outcome: Outcome, message: str
    ) -> None:
        if action_id in self._fallback_ids:
            await self._fallback.record_outcome(action_id, outcome, message)
            return
        try:
            await self._xadd(
                {
                    "type": "outcome",
                    "action_id": action_id,
                    "outcome": outcome,
                    "message": message,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception:
            self._fallback_ids.add(action_id)
            await self._fallback.record_outcome(action_id, outcome, message)

    async def history(self, limit: int = 50) -> list[LedgerEntry]:
        try:
            raw = await self._redis.xrevrange(self.STREAM, count=limit * 3)
        except Exception:
            return await self._fallback.history(limit)
        index: dict[str, LedgerEntry] = {}
        for _msg_id, fields in reversed(raw):
            t = fields.get("type")
            if t == "request":
                req = ActionRequest.model_validate_json(fields["data"])
                index.setdefault(req.action_id, LedgerEntry(request=req))
            elif t == "decision":
                d = ActionDecision.model_validate_json(fields["data"])
                if d.action_id in index:
                    index[d.action_id].decision = d
            elif t == "outcome":
                aid = fields["action_id"]
                if aid in index:
                    e = index[aid]
                    e.outcome = fields["outcome"]  # type: ignore[assignment]
                    e.result_message = fields["message"]
                    e.resolved_at = datetime.fromisoformat(fields["resolved_at"])
        # Merge any entries written to the file fallback during a Redis outage.
        fallback_entries = await self._fallback.history(limit)
        for fe in fallback_entries:
            index.setdefault(fe.request.action_id, fe)
        entries = list(index.values())
        entries.sort(key=lambda e: e.request.created_at)
        return entries[-limit:]

    async def lookup(self, action_id: str) -> LedgerEntry | None:
        """Find one ledger row by scanning recent stream entries."""
        if action_id in self._fallback_ids:
            return await self._fallback.lookup(action_id)
        try:
            raw = await self._redis.xrevrange(self.STREAM, count=500)
        except Exception:
            return await self._fallback.lookup(action_id)
        entry: LedgerEntry | None = None
        for _msg_id, fields in reversed(raw):
            t = fields.get("type")
            if t == "request":
                req = ActionRequest.model_validate_json(fields["data"])
                if req.action_id == action_id:
                    entry = LedgerEntry(request=req)
            elif t == "decision" and entry is not None:
                d = ActionDecision.model_validate_json(fields["data"])
                if d.action_id == action_id:
                    entry.decision = d
            elif t == "outcome" and entry is not None:
                if fields.get("action_id") == action_id:
                    entry.outcome = fields["outcome"]  # type: ignore[assignment]
                    entry.result_message = fields["message"]
                    entry.resolved_at = datetime.fromisoformat(fields["resolved_at"])
                    return entry
        # Redis succeeded but the record is missing — it may have been written to the
        # file fallback during a prior Redis outage. Check there before returning None.
        if entry is None:
            entry = await self._fallback.lookup(action_id)
        return entry


# ── Factory ────────────────────────────────────────────────────────────────────

_ledger: ConsentLedger | None = None


def get_ledger() -> ConsentLedger:
    global _ledger
    if _ledger is None:
        from config import settings

        url = getattr(settings, "redis_url", None)
        if url:
            _ledger = RedisLedger(url)
        else:
            _ledger = FileLedger()
    return _ledger
