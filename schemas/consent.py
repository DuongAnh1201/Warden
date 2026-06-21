"""Consent-gate schemas.

Every gated action flows through these three models:
  ActionRequest  → raised by a tool, presented to the user
  ActionDecision → the user's approve / cancel / revise response
  LedgerEntry    → the durable record: request + decision + outcome
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ActionType = Literal[
    "email.send",
    "email.notification",
    "email.register_domain",
    "calendar.create",
    "calendar.update",
    "calendar.delete",
    "comms.imessage",
    "comms.call",
    "knowledge.create",
    "knowledge.update",
    "knowledge.add_context",
    # Gmail triage (state-changing, gated). Reads/searches are not gated — they
    # have no side effect. See docs/workspace-integration/.
    "gmail.modify",
    "gmail.draft",
    "gmail.trash",
    # Google Drive (state-changing, gated). list/read are not gated — no side effect.
    "drive.upload",
    "drive.update",
    "drive.share",
    "drive.delete",
    # Workspace connection lifecycle (auditable in the ledger).
    "workspace.connect",
    "workspace.upgrade_scope",
    "workspace.revoke",
    # Contact management
    "contact.register",
    # Agentverse agent messaging
    "agent.message",
]

Decision = Literal["approve", "cancel", "revise"]
Outcome = Literal["executed", "failed", "cancelled", "pending"]


class ActionRequest(BaseModel):
    """A consequential action awaiting the user's decision."""

    action_id: str = Field(default_factory=lambda: uuid4().hex)
    action_type: ActionType
    agent: str
    summary: str
    """One-line, voice-friendly description shown to the user."""
    payload: dict[str, Any]
    """The concrete args needed to execute — stored verbatim in the ledger."""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ActionDecision(BaseModel):
    """The user's response to an ActionRequest."""

    action_id: str
    decision: Decision
    revision_note: str = ""
    """Populated when decision == 'revise'; guidance for the agent to re-draft."""
    consent_token: str = ""
    """The Consent_Token minted on approval (HMAC over ts|action_id|transcript).
    Appended to the ledger as cryptographic proof, and required by the execution
    lock before any side effect runs. Empty for cancel/revise."""
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class LedgerEntry(BaseModel):
    """One fully-resolved row in the consent ledger."""

    request: ActionRequest
    decision: ActionDecision | None = None
    outcome: Outcome = "pending"
    result_message: str = ""
    resolved_at: datetime | None = None
