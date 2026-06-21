"""Gmail sub-agent — read and triage the user's inbox.

Reads (search/read) have no side effect and run directly. Triage actions
(mark read/unread, archive, star, draft, trash) change mailbox state and flow
through the consent gate, exactly like the calendar and knowledge agents.
"""
import asyncio

from pydantic_ai import Agent, RunContext

from ai.agents.consent import gate
from ai.agents.deps import OrchestratorDeps
from ai.prompts import load_prompt
from schemas.agent6 import GmailResult, GmailSearchRequest, GmailTriageRequest
from tools.gmail import LABEL_INBOX, LABEL_STARRED, LABEL_UNREAD

_gmail_agent: Agent | None = None


def get_gmail_agent() -> Agent:
    global _gmail_agent
    if _gmail_agent is None:
        from config import settings

        _gmail_agent = Agent(
            model=settings.ai_model,
            name="gmail_agent",
            system_prompt=load_prompt("gmail_agent"),
            output_type=GmailResult,
            deps_type=OrchestratorDeps,
        )

        # ── Reads (no side effect, not gated) ────────────────────────────────────

        @_gmail_agent.tool
        async def search_inbox(
            ctx: RunContext[OrchestratorDeps], request: GmailSearchRequest
        ) -> str:
            """Search the user's inbox with a Gmail query (e.g. 'from:priya is:unread')."""
            from tools.gmail import search_messages
            return await asyncio.to_thread(
                search_messages, request.query, ctx.deps.workspace_creds, request.max_results
            )

        @_gmail_agent.tool
        async def read_email(ctx: RunContext[OrchestratorDeps], message_id: str) -> str:
            """Read a single email's full content by message id."""
            from tools.gmail import read_message
            return await asyncio.to_thread(read_message, message_id, ctx.deps.workspace_creds)

        # ── Triage (state-changing, gated) ───────────────────────────────────────

        @_gmail_agent.tool
        async def mark_read(
            ctx: RunContext[OrchestratorDeps], request: GmailTriageRequest
        ) -> str:
            """Mark a message as read (removes the UNREAD label)."""
            from tools.gmail import modify_labels

            async def _execute() -> str:
                return await asyncio.to_thread(
                    modify_labels,
                    request.message_id,
                    ctx.deps.workspace_creds,
                    remove=[LABEL_UNREAD],
                    summary="Mark read",
                )

            return await gate(
                ctx,
                action_type="gmail.modify",
                agent="gmail_agent",
                summary=f"Mark message {request.message_id} as read",
                payload={"message_id": request.message_id, "op": "mark_read"},
                execute=_execute,
            )

        @_gmail_agent.tool
        async def mark_unread(
            ctx: RunContext[OrchestratorDeps], request: GmailTriageRequest
        ) -> str:
            """Mark a message as unread (adds the UNREAD label)."""
            from tools.gmail import modify_labels

            async def _execute() -> str:
                return await asyncio.to_thread(
                    modify_labels,
                    request.message_id,
                    ctx.deps.workspace_creds,
                    add=[LABEL_UNREAD],
                    summary="Mark unread",
                )

            return await gate(
                ctx,
                action_type="gmail.modify",
                agent="gmail_agent",
                summary=f"Mark message {request.message_id} as unread",
                payload={"message_id": request.message_id, "op": "mark_unread"},
                execute=_execute,
            )

        @_gmail_agent.tool
        async def archive_email(
            ctx: RunContext[OrchestratorDeps], request: GmailTriageRequest
        ) -> str:
            """Archive a message (removes it from the inbox; reversible)."""
            from tools.gmail import modify_labels

            async def _execute() -> str:
                return await asyncio.to_thread(
                    modify_labels,
                    request.message_id,
                    ctx.deps.workspace_creds,
                    remove=[LABEL_INBOX],
                    summary="Archive",
                )

            return await gate(
                ctx,
                action_type="gmail.modify",
                agent="gmail_agent",
                summary=f"Archive message {request.message_id}",
                payload={"message_id": request.message_id, "op": "archive"},
                execute=_execute,
            )

        @_gmail_agent.tool
        async def star_email(
            ctx: RunContext[OrchestratorDeps], request: GmailTriageRequest
        ) -> str:
            """Star a message (adds the STARRED label)."""
            from tools.gmail import modify_labels

            async def _execute() -> str:
                return await asyncio.to_thread(
                    modify_labels,
                    request.message_id,
                    ctx.deps.workspace_creds,
                    add=[LABEL_STARRED],
                    summary="Star",
                )

            return await gate(
                ctx,
                action_type="gmail.modify",
                agent="gmail_agent",
                summary=f"Star message {request.message_id}",
                payload={"message_id": request.message_id, "op": "star"},
                execute=_execute,
            )

        @_gmail_agent.tool
        async def create_draft(
            ctx: RunContext[OrchestratorDeps], request: GmailTriageRequest
        ) -> str:
            """Create a draft reply/message. A draft is NOT sent."""
            from tools.gmail import create_draft as _create_draft

            async def _execute() -> str:
                return await asyncio.to_thread(
                    _create_draft,
                    request.to,
                    request.subject,
                    request.body,
                    ctx.deps.workspace_creds,
                )

            return await gate(
                ctx,
                action_type="gmail.draft",
                agent="gmail_agent",
                summary=f"Create draft to {request.to} — subject '{request.subject}'",
                payload={"to": request.to, "subject": request.subject, "body": request.body},
                execute=_execute,
            )

        @_gmail_agent.tool
        async def trash_email(
            ctx: RunContext[OrchestratorDeps], request: GmailTriageRequest
        ) -> str:
            """Move a message to Trash."""
            from tools.gmail import trash_message

            async def _execute() -> str:
                return await asyncio.to_thread(
                    trash_message, request.message_id, ctx.deps.workspace_creds
                )

            return await gate(
                ctx,
                action_type="gmail.trash",
                agent="gmail_agent",
                summary=f"Move message {request.message_id} to Trash",
                payload={"message_id": request.message_id, "op": "trash"},
                execute=_execute,
            )

    return _gmail_agent
