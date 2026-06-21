from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from ai.prompts import load_prompt
from tools.ledger import ConsentLedger, get_ledger
from schemas.consent import ActionDecision, ActionRequest

_TOM_HISTORY = load_prompt("tombio")


@dataclass
class OrchestratorDeps:
    # ── User identity ──────────────────────────────────────────────────────────
    user_id: str = field(default="default")
    """Unique identifier for the current user. Used to namespace all Redis data."""

    history_context: dict = field(default_factory=dict)
    preferred_pronouns: str = field(default="Sir")
    name: str = field(default="Khoi")
    email_address: str = field(default="khoiduong2913@gmail.com")
    tom_history_context: str = field(default=_TOM_HISTORY)
    search_api_key: str = field(default="")
    calendar_event_ids: dict = field(default_factory=dict)

    # ── Graph knowledge + execution log (Phase 4) ──────────────────────────────
    knowledge: object | None = field(default=None)
    """GraphKnowledge instance. None falls back to file-backed knowledge base.
    Save only on explicit user request; retrieval uses semantic + graph traversal."""

    execution_log: object | None = field(default=None)
    """ExecutionLog instance. When set, every tool call logs its outcome to Redis.
    Always-on: logs both successes and failures."""

    # ── Consent gate ───────────────────────────────────────────────────────────
    request_approval: Callable[[ActionRequest], Awaitable[ActionDecision]] | None = (
        field(default=None)
    )
    """Async callback set by the session/UI layer.

    Receives an ActionRequest, presents it to the user (console, WebSocket, voice),
    and returns the user's ActionDecision. When None and auto_approve is False,
    the gate denies every action by default.
    """

    ledger: ConsentLedger = field(default_factory=get_ledger)
    """Append-only consent ledger. Defaults to FileLedger unless REDIS_URL is set."""

    auto_approve: bool = field(default=False)
    """When True, all gated actions are auto-approved without prompting.
    Only for smoke tests and the demo 'Try as Guest' persona. Still writes to the ledger.
    """

    # ── Google Workspace ─────────────────────────────────────────────────────────
    workspace_creds: Any = field(default=None)
    """Google OAuth credentials from the user's Workspace connect flow (Drive,
    Gmail, Calendar). None until the user opts in and completes the grant; while
    None, workspace-backed tools (e.g. Google Calendar) run in demo mode.
    See docs/workspace-integration/."""
