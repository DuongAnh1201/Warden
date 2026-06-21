"""Knowledge base sub-agent — graph-structured knowledge, save only on request.

Storage:
  - Redis GraphKnowledge (Phase 4) when ctx.deps.knowledge is set.
    Nodes = topics/concepts.  Edges = typed relationships between them.
    Retrieval uses semantic search + 1-hop graph traversal.
  - File-backed fallback when no GraphKnowledge is wired.

Every tool call (success or failure) is written to the ExecutionLog so there
is always an audit trail of what the assistant actually did.
"""
import asyncio

from pydantic_ai import Agent, RunContext

from ai.agents.consent import gate
from ai.agents.deps import OrchestratorDeps
from ai.prompts import load_prompt
from memory.execution_log import log_execution
from schemas.agent5 import KnowledgeBaseResult

_knowledge_base_agent: Agent | None = None


def get_knowledge_base_agent() -> Agent:
    global _knowledge_base_agent
    if _knowledge_base_agent is None:
        from config import settings
        from observability.phoenix import get_agent_instrumentation

        _knowledge_base_agent = Agent(
            model=settings.ai_model,
            name="knowledge_base_agent",
            system_prompt=load_prompt("knowledge_base_agent"),
            output_type=KnowledgeBaseResult,
            deps_type=OrchestratorDeps,
            capabilities=get_agent_instrumentation(),
        )

        # ── Save (create / overwrite) ──────────────────────────────────────────

        @_knowledge_base_agent.tool
        async def save_knowledge(
            ctx: RunContext[OrchestratorDeps],
            label: str,
            content: str,
            node_type: str = "fact",
        ) -> str:
            """Save a piece of knowledge as a graph node.

            Call this ONLY when the user explicitly asks to save something.
            `label` is the topic or concept name.
            `node_type` must be one of: person, project, preference, fact, event, task, other.
            If a node with the same label already exists it is overwritten.
            """
            knowledge = ctx.deps.knowledge

            async def _execute() -> str:
                if knowledge is not None:
                    node = await knowledge.upsert_node(
                        ctx.deps.user_id, label, content, node_type
                    )
                    return f"Saved [{node.node_type}] '{node.label}' (id={node.node_id[:8]})."
                from tools.knowledge_base import create_new_file as _create
                result = await asyncio.to_thread(_create, label, content)
                return result.message

            try:
                result = await gate(
                    ctx,
                    action_type="knowledge.create",
                    agent="knowledge_base_agent",
                    summary=f"Save knowledge node '{label}' ({node_type})",
                    payload={"label": label, "content": content, "node_type": node_type},
                    execute=_execute,
                )
                await log_execution(ctx.deps, "knowledge_base", "save_knowledge",
                                    success=True, message=result, label=label)
                return result
            except Exception as exc:
                await log_execution(ctx.deps, "knowledge_base", "save_knowledge",
                                    success=False, message=str(exc), label=label)
                raise

        # ── Append context to existing node ───────────────────────────────────

        @_knowledge_base_agent.tool
        async def add_to_knowledge(
            ctx: RunContext[OrchestratorDeps],
            label: str,
            additional_content: str,
        ) -> str:
            """Append new information to an existing knowledge node without overwriting it.

            Use this when the user wants to add facts to a topic that already exists.
            """
            knowledge = ctx.deps.knowledge

            async def _execute() -> str:
                if knowledge is not None:
                    node = await knowledge.append_to_node(
                        ctx.deps.user_id, label, additional_content
                    )
                    if node is None:
                        # Node didn't exist — create it instead.
                        node = await knowledge.upsert_node(
                            ctx.deps.user_id, label, additional_content
                        )
                        return f"Created new node '{label}' (did not exist)."
                    return f"Added context to '{label}'."
                from tools.knowledge_base import add_context as _add
                result = await asyncio.to_thread(_add, label, additional_content)
                return result.message

            try:
                result = await gate(
                    ctx,
                    action_type="knowledge.add_context",
                    agent="knowledge_base_agent",
                    summary=f"Append context to knowledge node '{label}'",
                    payload={"label": label, "additional_content": additional_content},
                    execute=_execute,
                )
                await log_execution(ctx.deps, "knowledge_base", "add_to_knowledge",
                                    success=True, message=result, label=label)
                return result
            except Exception as exc:
                await log_execution(ctx.deps, "knowledge_base", "add_to_knowledge",
                                    success=False, message=str(exc), label=label)
                raise

        # ── Link two nodes ────────────────────────────────────────────────────

        @_knowledge_base_agent.tool
        async def link_knowledge(
            ctx: RunContext[OrchestratorDeps],
            source_label: str,
            relation: str,
            target_label: str,
        ) -> str:
            """Create a directed relationship between two existing knowledge nodes.

            Example: link_knowledge("Project Alpha", "has_deadline", "July 15 2025")
            """
            knowledge = ctx.deps.knowledge
            if knowledge is None:
                return "Graph relationships require Redis KnowledgeStore (not configured)."

            async def _execute() -> str:
                src = await knowledge.get_node_by_label(ctx.deps.user_id, source_label)
                tgt = await knowledge.get_node_by_label(ctx.deps.user_id, target_label)
                if src is None:
                    return f"Source node '{source_label}' not found."
                if tgt is None:
                    return f"Target node '{target_label}' not found."
                await knowledge.add_edge(ctx.deps.user_id, src.node_id, relation, tgt.node_id)
                return f"Linked '{source_label}' --[{relation}]--> '{target_label}'."

            try:
                result = await gate(
                    ctx,
                    action_type="knowledge.update",
                    agent="knowledge_base_agent",
                    summary=f"Link '{source_label}' --[{relation}]--> '{target_label}'",
                    payload={"source": source_label, "relation": relation, "target": target_label},
                    execute=_execute,
                )
                await log_execution(ctx.deps, "knowledge_base", "link_knowledge",
                                    success=True, message=result)
                return result
            except Exception as exc:
                await log_execution(ctx.deps, "knowledge_base", "link_knowledge",
                                    success=False, message=str(exc))
                raise

        # ── Retrieve: semantic search + graph traversal ───────────────────────

        @_knowledge_base_agent.tool
        async def recall_knowledge(
            ctx: RunContext[OrchestratorDeps],
            query: str,
        ) -> str:
            """Retrieve relevant knowledge for a query using semantic search and graph traversal.

            Returns assembled context: matched nodes + their 1-hop neighbors.
            Use this whenever the user asks about something that might be stored.
            """
            knowledge = ctx.deps.knowledge
            try:
                if knowledge is not None:
                    context = await knowledge.get_context(ctx.deps.user_id, query)
                    if not context:
                        await log_execution(ctx.deps, "knowledge_base", "recall_knowledge",
                                            success=True, message="No results found", query=query)
                        return "No relevant knowledge found for this query."
                    await log_execution(ctx.deps, "knowledge_base", "recall_knowledge",
                                        success=True, message="Returned graph context", query=query)
                    return context

                # file fallback
                from tools.knowledge_base import read_file as _read
                result = await asyncio.to_thread(_read, query)
                await log_execution(ctx.deps, "knowledge_base", "recall_knowledge",
                                    success=result.success, message=result.message, query=query)
                return result.context if result.success else result.message

            except Exception as exc:
                await log_execution(ctx.deps, "knowledge_base", "recall_knowledge",
                                    success=False, message=str(exc), query=query)
                raise

        # ── Retrieve: exact topic lookup ───────────────────────────────────────

        @_knowledge_base_agent.tool
        async def get_topic(
            ctx: RunContext[OrchestratorDeps],
            label: str,
        ) -> str:
            """Fetch a knowledge node by its exact label (case-insensitive).

            Use this when the user refers to a specific named topic or concept.
            """
            knowledge = ctx.deps.knowledge
            try:
                if knowledge is not None:
                    node = await knowledge.get_node_by_label(ctx.deps.user_id, label)
                    if node is None:
                        await log_execution(ctx.deps, "knowledge_base", "get_topic",
                                            success=False, message=f"'{label}' not found", label=label)
                        return f"No knowledge node found for '{label}'."
                    neighbors = await knowledge.get_neighbors(ctx.deps.user_id, node.node_id)
                    parts = [f"[{node.node_type.upper()}] {node.label}\n{node.content}"]
                    for rel, nb in neighbors:
                        parts.append(f"  → {rel}: {nb.label} — {nb.content}")
                    result = "\n".join(parts)
                    await log_execution(ctx.deps, "knowledge_base", "get_topic",
                                        success=True, message=f"Found '{label}'", label=label)
                    return result

                from tools.knowledge_base import read_file as _read
                r = await asyncio.to_thread(_read, label)
                await log_execution(ctx.deps, "knowledge_base", "get_topic",
                                    success=r.success, message=r.message, label=label)
                return r.context if r.success else r.message

            except Exception as exc:
                await log_execution(ctx.deps, "knowledge_base", "get_topic",
                                    success=False, message=str(exc), label=label)
                raise

    return _knowledge_base_agent
