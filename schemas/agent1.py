"""Schemas for the Email agent."""

from typing import Literal
from pydantic import BaseModel


class EmailAgentResult(BaseModel):
    message: str


class EmailDraft(BaseModel):
    """A pending email awaiting the user's approval (the consent-gate primitive).

    When ``OrchestratorDeps.request_email_approval`` is set, the email agent builds
    one of these and hands it to that callback instead of sending directly.
    """

    email_type: Literal["notification", "user_request"]
    to: str
    subject: str
    body: str
    link: str = ""


class SpokenEmailDraftExtraction(BaseModel):
    is_email_intent: bool = False
    is_complete: bool = False
    email_type: Literal["notification", "user_request", "unknown"] = "unknown"
    to: str = ""
    subject: str = ""
    body: str = ""
    link: str = ""
    reason: str = ""
