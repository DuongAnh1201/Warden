"""Shared fixtures for consent-gate tests."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from ai.agents.deps import OrchestratorDeps
from schemas.consent import ActionDecision, ActionRequest
from tools.execution_lock import ConsentGrant
from tools.ledger import FileLedger


@dataclass
class FakeRunContext:
    """Minimal stand-in for pydantic_ai RunContext[OrchestratorDeps]."""

    deps: OrchestratorDeps


@pytest.fixture
def ledger(tmp_path):
    """Isolated JSONL ledger — never touches .consent/ledger.jsonl."""
    return FileLedger(path=tmp_path / "ledger.jsonl")


def approval(decision: str, *, revision_note: str = "") -> Callable[[ActionRequest], Awaitable[ActionDecision]]:
    """Build an async approver that always returns the same decision."""

    async def _approve(req: ActionRequest) -> ActionDecision:
        return ActionDecision(
            action_id=req.action_id,
            decision=decision,  # type: ignore[arg-type]
            revision_note=revision_note,
        )

    return _approve


def run(coro):
    """Run an async test helper from a sync pytest function."""
    return asyncio.run(coro)


def fresh_grant(
    action_id: str = "test-action-id",
    action_type: str = "email.send",
    token: str = "test-token",
    *,
    ttl_seconds: int = 300,
    expired: bool = False,
) -> ConsentGrant:
    """Build a ConsentGrant for lock tests."""
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(seconds=1) if expired else now + timedelta(seconds=ttl_seconds)
    return ConsentGrant(
        action_id=action_id,
        action_type=action_type,
        token=token,
        expires_at=expires_at,
    )
