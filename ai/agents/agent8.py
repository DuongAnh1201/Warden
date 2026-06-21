"""Agentverse sub-agent — discover and message agents on the Fetch.ai network.

Tools:
  discover_agents(capability)  — search Agentverse for agents by keyword
  message_agent(address, msg)  — send a request to any agent and await the reply
                                  (goes through the consent gate)
"""
from __future__ import annotations

import logging
import uuid

from pydantic_ai import Agent, RunContext

from ai.agents.consent import gate
from ai.agents.deps import OrchestratorDeps
from ai.prompts import load_prompt

logger = logging.getLogger(__name__)

_agentverse_agent: Agent | None = None


def get_agentverse_agent() -> Agent:
    global _agentverse_agent
    if _agentverse_agent is None:
        from config import settings
        from observability.phoenix import get_agent_instrumentation

        _agentverse_agent = Agent(
            model=settings.ai_model,
            name="agentverse_agent",
            system_prompt=load_prompt("agentverse_agent"),
            deps_type=OrchestratorDeps,
            capabilities=get_agent_instrumentation(),
        )

        # ── Discovery ─────────────────────────────────────────────────────────

        @_agentverse_agent.tool
        async def discover_agents(ctx: RunContext[OrchestratorDeps], capability: str) -> str:
            """Search Agentverse for agents matching a capability keyword.
            Returns a list of agent names, addresses, and descriptions.
            """
            import httpx

            api_key = ctx.deps.agentverse_api_key if hasattr(ctx.deps, "agentverse_api_key") else ""
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://agentverse.ai/v1/almanac/agents",
                        params={"search": capability, "limit": 5},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except Exception as exc:
                logger.warning("[agent8] discover_agents failed: %s", exc)
                return f"Could not search Agentverse: {exc}"

            agents = data.get("agents", data) if isinstance(data, dict) else data
            if not agents:
                return f"No agents found matching '{capability}' on Agentverse."

            lines = []
            for a in agents[:5]:
                name = a.get("name", "unknown")
                addr = a.get("address", a.get("agent_address", "?"))
                desc = a.get("readme", a.get("description", ""))[:120]
                lines.append(f"• {name}\n  address: {addr}\n  {desc}")
            return "\n\n".join(lines)

        # ── Messaging ─────────────────────────────────────────────────────────

        @_agentverse_agent.tool
        async def message_agent(
            ctx: RunContext[OrchestratorDeps],
            address: str,
            message: str,
        ) -> str:
            """Send a message to a remote Agentverse agent and return its reply.
            Requires consent — the user must approve before the message is sent.
            address: the agent's Fetch.ai address (starts with 'agent1...')
            message: the request to send
            """
            from config import settings

            if not settings.redis_url:
                return (
                    "Agent messaging requires Redis (REDIS_URL not set). "
                    "The uAgent bridge is unavailable."
                )

            correlation_id = str(uuid.uuid4())

            async def _execute() -> str:
                from ai.transport.bridge import enqueue_agent_request, await_agent_response
                await enqueue_agent_request(address, message, correlation_id)
                logger.info("[agent8] sent to %s (corr=%s), waiting for reply…",
                            address[:24], correlation_id[:8])
                try:
                    result = await await_agent_response(correlation_id, timeout=30.0)
                except TimeoutError:
                    return f"No reply from {address[:24]} within 30 s — the agent may be offline."
                if not result.get("success"):
                    return f"Remote agent returned an error: {result.get('text', 'unknown error')}"
                reply = result["text"]
                logger.info("[agent8] reply from %s: %s", address[:24], reply[:120])
                return reply

            return await gate(
                ctx,
                action_type="agent.message",
                agent="agentverse_agent",
                summary=f"Message agent {address[:24]}… — '{message[:60]}'",
                payload={"address": address, "message": message, "correlation_id": correlation_id},
                execute=_execute,
            )

    return _agentverse_agent
