"""Calendar sub-agent."""
import asyncio

from pydantic_ai import Agent, RunContext

from ai.agents.consent import gate
from ai.agents.deps import OrchestratorDeps
from schemas.agent2 import CalendarResult, CalendarRequest
from ai.prompts import load_prompt

_calendar_agent: Agent | None = None


def get_calendar_agent() -> Agent:
    global _calendar_agent
    if _calendar_agent is None:
        from config import settings

        _calendar_agent = Agent(
            model=settings.ai_model,
            name="calendar_agent",
            system_prompt=load_prompt("calendar_agent"),
            output_type=CalendarResult,
        )

        @_calendar_agent.tool
        async def list_calendars(ctx: RunContext[OrchestratorDeps]) -> str:
            """List all available Google Calendars."""
            from tools.calendar import calendars as _list
            try:
                return await asyncio.to_thread(_list, ctx.deps.workspace_creds)
            except RuntimeError as e:
                return f"Failed to list calendars. Reason: {e}"

        @_calendar_agent.tool
        async def check_freebusy(
            ctx: RunContext[OrchestratorDeps],
            req: CalendarRequest,
        ) -> str:
            """Check free/busy slots for a calendar within a time range."""
            from tools.calendar import freebusy_check as _freebusy
            if not req.start or not req.end:
                return "Start and end time are required for free/busy check. Do not retry."
            try:
                return await asyncio.to_thread(_freebusy, req, ctx.deps.workspace_creds)
            except RuntimeError as e:
                return f"Failed to check free/busy. Do not retry. Reason: {e}"

        @_calendar_agent.tool
        async def create_calendar_event(
            ctx: RunContext[OrchestratorDeps],
            req: CalendarRequest,
        ) -> str:
            """Create a calendar event on macOS."""
            from tools.calendar import create_calendar_event as _create

            async def _execute() -> str:
                output = await asyncio.to_thread(_create, req, ctx.deps.workspace_creds)
                return output or f"Successfully scheduled '{req.title}' at {req.start}."

            return await gate(
                ctx,
                action_type="calendar.create",
                agent="calendar_agent",
                summary=f"Create calendar event '{req.title}' at {req.start}",
                payload=req.model_dump(mode="json"),
                execute=_execute,
            )

        @_calendar_agent.tool
        async def update_calendar_event(
            ctx: RunContext[OrchestratorDeps],
            req: CalendarRequest,
        ) -> str:
            """Update an existing calendar event by its ID."""
            if not req.id:
                ids = ctx.deps.calendar_event_ids
                return f"No event ID provided. Known events: {ids or 'none saved yet'}. Do not retry."

            from tools.calendar import create_calendar_update as _update

            async def _execute() -> str:
                output = await asyncio.to_thread(_update, req, ctx.deps.workspace_creds)
                return output or f"Event '{req.id}' updated."

            return await gate(
                ctx,
                action_type="calendar.update",
                agent="calendar_agent",
                summary=f"Update calendar event '{req.id}' — new title: '{req.title}'",
                payload=req.model_dump(mode="json"),
                execute=_execute,
            )

        @_calendar_agent.tool
        async def delete_calendar_event(
            ctx: RunContext[OrchestratorDeps],
            req: CalendarRequest,
        ) -> str:
            """Delete a calendar event by its ID."""
            if not req.id:
                ids = ctx.deps.calendar_event_ids
                return f"No event ID provided. Known events: {ids or 'none saved yet'}. Do not retry."

            from tools.calendar import create_calendar_delete as _delete

            async def _execute() -> str:
                output = await asyncio.to_thread(_delete, req, ctx.deps.workspace_creds)
                return output or f"Event '{req.id}' deleted."

            return await gate(
                ctx,
                action_type="calendar.delete",
                agent="calendar_agent",
                summary=f"Delete calendar event '{req.id}' ('{req.title}')",
                payload=req.model_dump(mode="json"),
                execute=_execute,
            )

    return _calendar_agent
