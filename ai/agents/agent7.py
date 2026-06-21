"""Google Drive sub-agent — read and write files.

Reads (list/read) have no side effect and run directly. Writes (upload, update,
share, delete) change Drive state and flow through the consent gate, exactly like
the calendar and gmail agents.
"""
import asyncio

from pydantic_ai import Agent, RunContext

from ai.agents.consent import gate
from ai.agents.deps import OrchestratorDeps
from ai.prompts import load_prompt
from schemas.agent7 import DriveFileRequest, DriveResult, DriveSearchRequest

_drive_agent: Agent | None = None


def get_drive_agent() -> Agent:
    global _drive_agent
    if _drive_agent is None:
        from config import settings
        from observability.phoenix import get_agent_instrumentation

        _drive_agent = Agent(
            model=settings.ai_model,
            name="drive_agent",
            system_prompt=load_prompt("drive_agent"),
            output_type=DriveResult,
            deps_type=OrchestratorDeps,
            capabilities=get_agent_instrumentation(),
        )

        # ── Reads (no side effect, not gated) ────────────────────────────────────

        @_drive_agent.tool
        async def search_drive(
            ctx: RunContext[OrchestratorDeps], request: DriveSearchRequest
        ) -> str:
            """List/search the user's Drive files."""
            from tools.google_drive import list_files
            return await asyncio.to_thread(
                list_files, request.query, ctx.deps.workspace_creds, request.max_results
            )

        @_drive_agent.tool
        async def read_drive_file(ctx: RunContext[OrchestratorDeps], file_id: str) -> str:
            """Read a Drive file's text content by id."""
            from tools.google_drive import read_file
            return await asyncio.to_thread(read_file, file_id, ctx.deps.workspace_creds)

        # ── Writes (state-changing, gated) ───────────────────────────────────────

        @_drive_agent.tool
        async def create_drive_file(
            ctx: RunContext[OrchestratorDeps], request: DriveFileRequest
        ) -> str:
            """Create a new file in Drive."""
            from tools.google_drive import upload_file

            async def _execute() -> str:
                return await asyncio.to_thread(
                    upload_file,
                    request.name,
                    request.content,
                    ctx.deps.workspace_creds,
                    request.mime_type,
                    request.folder_id,
                )

            return await gate(
                ctx,
                action_type="drive.upload",
                agent="drive_agent",
                summary=f"Create Drive file '{request.name}'",
                payload={"name": request.name, "mime_type": request.mime_type},
                execute=_execute,
            )

        @_drive_agent.tool
        async def update_drive_file(
            ctx: RunContext[OrchestratorDeps], request: DriveFileRequest
        ) -> str:
            """Overwrite an existing Drive file's content."""
            from tools.google_drive import update_file

            async def _execute() -> str:
                return await asyncio.to_thread(
                    update_file,
                    request.file_id,
                    request.content,
                    ctx.deps.workspace_creds,
                    request.mime_type,
                )

            return await gate(
                ctx,
                action_type="drive.update",
                agent="drive_agent",
                summary=f"Update Drive file {request.file_id}",
                payload={"file_id": request.file_id},
                execute=_execute,
            )

        @_drive_agent.tool
        async def share_drive_file(
            ctx: RunContext[OrchestratorDeps], request: DriveFileRequest
        ) -> str:
            """Share a Drive file with someone (external data egress)."""
            from tools.google_drive import share_file

            async def _execute() -> str:
                return await asyncio.to_thread(
                    share_file,
                    request.file_id,
                    request.email,
                    request.role,
                    ctx.deps.workspace_creds,
                )

            return await gate(
                ctx,
                action_type="drive.share",
                agent="drive_agent",
                summary=f"Share Drive file {request.file_id} with {request.email} as {request.role}",
                payload={"file_id": request.file_id, "email": request.email, "role": request.role},
                execute=_execute,
            )

        @_drive_agent.tool
        async def delete_drive_file(
            ctx: RunContext[OrchestratorDeps], request: DriveFileRequest
        ) -> str:
            """Move a Drive file to Trash."""
            from tools.google_drive import delete_file

            async def _execute() -> str:
                return await asyncio.to_thread(
                    delete_file, request.file_id, ctx.deps.workspace_creds, True
                )

            return await gate(
                ctx,
                action_type="drive.delete",
                agent="drive_agent",
                summary=f"Move Drive file {request.file_id} to Trash",
                payload={"file_id": request.file_id},
                execute=_execute,
            )

    return _drive_agent
