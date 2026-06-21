"""Google Search sub-agent."""
import logging

import httpx
from pydantic_ai import Agent, RunContext

from ai.agents.deps import OrchestratorDeps
from ai.prompts import load_prompt
from schemas.agent3 import SearchResult

logger = logging.getLogger(__name__)

_search_agent: Agent | None = None


def get_search_agent() -> Agent:
    global _search_agent
    if _search_agent is None:
        from config import settings
        from observability.phoenix import get_agent_instrumentation

        _search_agent = Agent(
            model=settings.ai_model,
            name="search_agent",
            system_prompt=load_prompt("search_agent"),
            output_type=SearchResult,
            deps_type=OrchestratorDeps,
            capabilities=get_agent_instrumentation(),
        )

        @_search_agent.tool
        async def search_web(ctx: RunContext[OrchestratorDeps], query: str) -> list[dict]:
            """Live web search via Serper API. Returns empty list when unavailable."""
            if not ctx.deps.search_api_key:
                logger.info("search_web: no SERPER_API_KEY configured — skipping")
                return []
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        "https://google.serper.dev/search",
                        headers={"X-API-KEY": ctx.deps.search_api_key},
                        json={"q": query, "num": 10},
                    )
                    resp.raise_for_status()
                    return resp.json().get("organic", [])
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "search_web: Serper API returned %s — check SERPER_API_KEY. (%s)",
                    e.response.status_code,
                    e.response.text[:120],
                )
                return []
            except httpx.RequestError as e:
                logger.warning("search_web: request failed — %s", e)
                return []

    return _search_agent
