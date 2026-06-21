from pydantic_ai import Agent, RunContext

from ai.prompts import load_prompt
from ai.agents.deps import OrchestratorDeps
from schemas.orchestrator import OrchestratorResult

_orchestrator: Agent | None = None


def get_orchestrator() -> Agent:
    global _orchestrator
    if _orchestrator is None:
        from config import settings
        from observability.phoenix import get_agent_instrumentation

        _orchestrator = Agent(
            model=settings.ai_model,
            name="orchestrator",
            system_prompt=load_prompt("orchestrator"),
            output_type=OrchestratorResult,
            deps_type=OrchestratorDeps,
            capabilities=get_agent_instrumentation(),
        )

        # ── Dynamic context: inject user identity + bio at runtime ───────────────

        @_orchestrator.system_prompt
        async def inject_user_context(ctx: RunContext[OrchestratorDeps]) -> str:
            parts: list[str] = []
            if ctx.deps.name:
                parts.append(f"User's name: {ctx.deps.name} (address them as {ctx.deps.preferred_pronouns}).")
            if ctx.deps.email_address:
                parts.append(f"User's email: {ctx.deps.email_address}.")
            if ctx.deps.user_history_context:
                parts.append(f"## Soul\n{ctx.deps.user_history_context}")
                parts.append(f"## User Background\n{ctx.deps.user_history_context}")
            turns = (ctx.deps.history_context or {}).get("turns", [])
            if turns:
                history_lines = "\n".join(
                    f"User: {t['user']}\nAssistant: {t['assistant']}" for t in turns[-10:]
                )
                parts.append(f"## Conversation so far\n{history_lines}")
            return "\n".join(parts)

        # ── Sub-agent delegation tools ─────────────────────────────────────────

        @_orchestrator.tool
        async def delegate_email(
            ctx: RunContext[OrchestratorDeps],
            to: str,
            subject: str,
            body: str,
            email_type: str = "user_request",
            link: str = "",
        ) -> str:
            """Delegate an email-sending request to the email sub-agent.
            email_type must be 'notification' (styled HTML) or 'user_request' (plain text).
            """
            from ai.agents.agent1 import get_email_agent
            prompt = f"Send a {email_type} email to {to} with subject '{subject}': {body}"
            if link:
                prompt += f"\nLink: {link}"
            result = await get_email_agent().run(prompt, deps=ctx.deps)
            return result.output.message

        @_orchestrator.tool
        async def delegate_search(
            ctx: RunContext[OrchestratorDeps],
            query: str,
        ) -> str:
            """Delegate a web search to the search sub-agent."""
            from ai.agents.agent3 import get_search_agent
            result = await get_search_agent().run(query, deps=ctx.deps)
            return result.output.summary

        @_orchestrator.tool
        async def delegate_communication(
            ctx: RunContext[OrchestratorDeps],
            recipient: str,
            action: str,
            message: str = "",
        ) -> str:
            """Delegate an iMessage or phone call to the communication sub-agent."""
            from ai.agents.agent4 import get_communication_agent
            prompt = (
                f"Call {recipient}"
                if action == "call"
                else f"Send iMessage to {recipient}: {message}"
            )
            result = await get_communication_agent().run(prompt, deps=ctx.deps)
            return result.output.message

        @_orchestrator.tool
        async def delegate_gmail(ctx, request: str) -> str:
            """Delegate an inbox request to the Gmail sub-agent.
            Use for reading/searching the user's email and for triage (mark read,
            archive, star, draft, trash). Does NOT send email — for sending, use
            delegate_email. Pass the full user request as-is.
            """
            from ai.agents.agent6 import get_gmail_agent
            result = await get_gmail_agent().run(request, deps=ctx.deps)
            return result.output.message

        @_orchestrator.tool
        async def delegate_drive(ctx, request: str) -> str:
            """Delegate a Google Drive request to the Drive sub-agent.
            Use for searching/reading the user's files and for writes (create,
            update, share, delete). Pass the full user request as-is.
            """
            from ai.agents.agent7 import get_drive_agent
            result = await get_drive_agent().run(request, deps=ctx.deps)
            return result.output.message

        @_orchestrator.tool
        async def delegate_knowledge_base(
            ctx: RunContext[OrchestratorDeps],
            request: str,
        ) -> str:
            """Delegate a knowledge base operation to the knowledge base sub-agent.
            Use for saving, retrieving, updating, or linking information.
            Pass the full user request as-is.
            """
            from ai.agents.agent5 import get_knowledge_base_agent
            result = await get_knowledge_base_agent().run(request, deps=ctx.deps)
            return result.output.message

        @_orchestrator.tool
        async def delegate_agentverse(
            ctx: RunContext[OrchestratorDeps],
            request: str,
        ) -> str:
            """Discover or message another AI agent on the Fetch.ai Agentverse network.
            Use when the user wants to contact, query, or delegate a task to an external agent.
            Pass the full user request as-is.
            """
            from ai.agents.agent8 import get_agentverse_agent
            result = await get_agentverse_agent().run(request, deps=ctx.deps)
            return result.output if isinstance(result.output, str) else str(result.output)

    return _orchestrator
