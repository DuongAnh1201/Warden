"""Schemas for the Gmail agent (read + triage).

Reading and searching the inbox have no side effect. Triage actions (label,
mark read/unread, archive, star, draft, trash) change mailbox state but stay
inside the user's own account — they flow through the consent gate.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class GmailSearchRequest(BaseModel):
    query: str = ""
    """Gmail search query, e.g. 'from:priya is:unread', 'subject:deck', 'newer_than:2d'."""
    max_results: int = 10


class GmailMessageSummary(BaseModel):
    id: str
    thread_id: str = ""
    sender: str = ""
    subject: str = ""
    snippet: str = ""
    date: str = ""
    unread: bool = False


class GmailMessage(BaseModel):
    id: str
    sender: str = ""
    to: str = ""
    subject: str = ""
    date: str = ""
    body: str = ""
    labels: list[str] = Field(default_factory=list)


class GmailTriageRequest(BaseModel):
    """Args for triage actions. Only the fields relevant to the action are used."""

    message_id: str = ""
    label: str = ""
    """Label name/id for add/remove-label actions."""
    # Draft fields
    to: str = ""
    subject: str = ""
    body: str = ""


class GmailResult(BaseModel):
    success: bool
    message: str
