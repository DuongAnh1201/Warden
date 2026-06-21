from typing import Literal
from pydantic import BaseModel


class OrchestratorResult(BaseModel):
    intent: Literal[
        "email", "calendar", "search", "communication", "knowledge",
        "gmail", "drive", "agentverse", "unknown"
    ]
    response: str
    """Human-readable reply shown to the user."""
