"""Build OrchestratorDeps for text, WebSocket, and CLI sessions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ai.agents.deps import OrchestratorDeps
from tools.ledger import ConsentLedger, get_ledger
from schemas.consent import ActionDecision, ActionRequest


GUEST_PERSONA = {
    "user_id": "guest",
    "name": "Guest",
    "preferred_pronouns": "there",
    "email_address": "guest@moneypenny.demo",
}


async def build_orchestrator_deps(
    *,
    user_id: str = "default",
    guest: bool = False,
    auto_approve: bool = False,
    request_approval: (
        Callable[[ActionRequest], Awaitable[ActionDecision]] | None
    ) = None,
    ledger: ConsentLedger | None = None,
    history: list[dict[str, str]] | None = None,
) -> OrchestratorDeps:
    """Assemble deps shared by run_text.py and the WebSocket server."""
    from config import settings

    persona = GUEST_PERSONA if guest else {}
    resolved_user_id = persona.get("user_id", user_id)

    knowledge = None
    execution_log = None
    if settings.redis_url:
        try:
            from memory.execution_log import get_execution_log

            execution_log = get_execution_log(user_id=resolved_user_id)
        except Exception:  # noqa: BLE001
            execution_log = None
        if settings.openai_api_key:
            try:
                from memory.graph import get_graph_knowledge

                knowledge = get_graph_knowledge(user_id=resolved_user_id)
            except Exception:  # noqa: BLE001
                knowledge = None

    workspace_creds = None
    if not guest:
        try:
            from tools.google_auth import get_workspace_credentials

            workspace_creds = get_workspace_credentials()
        except Exception:  # noqa: BLE001
            workspace_creds = None

    return OrchestratorDeps(
        user_id=resolved_user_id,
        name=persona.get("name", ""),
        preferred_pronouns=persona.get("preferred_pronouns", "Sir"),
        email_address=persona.get("email_address", ""),
        history_context={"turns": history if history is not None else []},
        knowledge=knowledge,
        execution_log=execution_log,
        ledger=ledger or get_ledger(),
        auto_approve=auto_approve,
        request_approval=request_approval,
        workspace_creds=workspace_creds,
        search_api_key=settings.serper_api_key or "",
    )
