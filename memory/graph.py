"""Graph-structured knowledge base backed by Redis.

Nodes  — topics / concepts (person, project, preference, fact, event, task).
Edges  — typed relationships between nodes ("has_deadline", "involves", "related_to", …).

Key layout (no user data leaks between namespaces):
  kgnode:{user_id}:{node_id}   → Hash  (user_id, node_id, label, content, node_type, embedding)
  kgedge:{user_id}:{node_id}   → Set   of "{relation}:{target_node_id}" strings
  kglabel:{user_id}            → Hash  of "{label_lower} → node_id" (exact-match index)

RediSearch index "graph_nodes" (prefix "kgnode:") provides:
  - Vector KNN on the embedding field
  - Tag filter on user_id so searches are always per-user
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import redis as _redis
from redis.commands.search.field import TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

VECTOR_DIM = 1536
INDEX_NAME = "graph_nodes"
NODE_PREFIX = "kgnode:"


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class GraphNode:
    node_id: str
    user_id: str
    label: str
    content: str
    node_type: str  # person | project | preference | fact | event | task | other
    score: float = 0.0  # populated during search


# ── Store ─────────────────────────────────────────────────────────────────────

class GraphKnowledge:
    def __init__(self, redis_url: str, openai_api_key: str) -> None:
        # Vectors are raw bytes — do NOT use decode_responses=True.
        self._r = _redis.from_url(redis_url, decode_responses=False)
        self._openai_key = openai_api_key
        self._index_ready = False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _node_key(self, user_id: str, node_id: str) -> bytes:
        return f"kgnode:{user_id}:{node_id}".encode()

    def _edge_key(self, user_id: str, node_id: str) -> bytes:
        return f"kgedge:{user_id}:{node_id}".encode()

    def _label_key(self, user_id: str) -> bytes:
        return f"kglabel:{user_id}".encode()

    def _embed(self, text: str) -> bytes:
        from openai import OpenAI
        vec = (
            OpenAI(api_key=self._openai_key)
            .embeddings.create(model="text-embedding-3-small", input=text)
            .data[0]
            .embedding
        )
        return struct.pack(f"{len(vec)}f", *vec)

    def _ensure_index(self) -> None:
        if self._index_ready:
            return
        try:
            self._r.ft(INDEX_NAME).info()
        except Exception:
            self._r.ft(INDEX_NAME).create_index(
                [
                    TagField("user_id"),
                    TagField("node_type"),
                    TextField("label"),
                    TextField("content"),
                    VectorField(
                        "embedding",
                        "FLAT",
                        {"TYPE": "FLOAT32", "DIM": VECTOR_DIM, "DISTANCE_METRIC": "COSINE"},
                    ),
                ],
                definition=IndexDefinition(prefix=[NODE_PREFIX], index_type=IndexType.HASH),
            )
        self._index_ready = True

    def _decode(self, raw: dict, key: bytes) -> str:
        val = raw.get(key, b"")
        return val.decode() if isinstance(val, bytes) else str(val)

    # ── Nodes ─────────────────────────────────────────────────────────────────

    async def upsert_node(
        self,
        user_id: str,
        label: str,
        content: str,
        node_type: str = "fact",
    ) -> GraphNode:
        """Create a new node or overwrite an existing one with the same label."""
        await asyncio.to_thread(self._ensure_index)

        # Reuse existing node_id if label already exists.
        label_key = self._label_key(user_id)
        existing_id_raw = await asyncio.to_thread(
            self._r.hget, label_key, label.lower().encode()
        )
        node_id = existing_id_raw.decode() if existing_id_raw else uuid4().hex
        now = datetime.now(timezone.utc).isoformat()

        embedding = await asyncio.to_thread(self._embed, f"{label}: {content}")

        await asyncio.to_thread(
            self._r.hset,
            self._node_key(user_id, node_id),
            mapping={
                b"node_id":   node_id.encode(),
                b"user_id":   user_id.encode(),
                b"label":     label.encode(),
                b"content":   content.encode(),
                b"node_type": node_type.encode(),
                b"updated_at": now.encode(),
                b"embedding":  embedding,
            },
        )
        await asyncio.to_thread(
            self._r.hset, label_key, label.lower().encode(), node_id.encode()
        )
        return GraphNode(node_id=node_id, user_id=user_id, label=label,
                         content=content, node_type=node_type)

    async def append_to_node(
        self, user_id: str, label: str, additional_content: str
    ) -> GraphNode | None:
        """Append text to an existing node's content. Returns None if node not found."""
        existing = await self.get_node_by_label(user_id, label)
        if existing is None:
            return None
        merged = f"{existing.content.rstrip()}\n{additional_content}"
        return await self.upsert_node(user_id, label, merged, existing.node_type)

    async def get_node_by_label(self, user_id: str, label: str) -> GraphNode | None:
        """Exact lookup by label (case-insensitive)."""
        label_key = self._label_key(user_id)
        node_id_raw = await asyncio.to_thread(
            self._r.hget, label_key, label.lower().encode()
        )
        if not node_id_raw:
            return None
        return await self._load_node(user_id, node_id_raw.decode())

    async def _load_node(self, user_id: str, node_id: str) -> GraphNode | None:
        raw = await asyncio.to_thread(self._r.hgetall, self._node_key(user_id, node_id))
        if not raw:
            return None
        return GraphNode(
            node_id=self._decode(raw, b"node_id"),
            user_id=self._decode(raw, b"user_id"),
            label=self._decode(raw, b"label"),
            content=self._decode(raw, b"content"),
            node_type=self._decode(raw, b"node_type"),
        )

    # ── Edges ─────────────────────────────────────────────────────────────────

    async def add_edge(
        self, user_id: str, source_id: str, relation: str, target_id: str
    ) -> None:
        """Add a directed edge: source --[relation]--> target."""
        edge_key = self._edge_key(user_id, source_id)
        member = f"{relation}:{target_id}".encode()
        await asyncio.to_thread(self._r.sadd, edge_key, member)

    async def get_neighbors(
        self, user_id: str, node_id: str
    ) -> list[tuple[str, GraphNode]]:
        """Return [(relation, neighbor_node)] for all outgoing edges."""
        edge_key = self._edge_key(user_id, node_id)
        members_raw = await asyncio.to_thread(self._r.smembers, edge_key)
        result = []
        for m in members_raw:
            text = m.decode() if isinstance(m, bytes) else m
            if ":" not in text:
                continue
            relation, target_id = text.split(":", 1)
            node = await self._load_node(user_id, target_id)
            if node:
                result.append((relation, node))
        return result

    # ── Search & context assembly ─────────────────────────────────────────────

    async def search(
        self, user_id: str, query: str, top_k: int = 5
    ) -> list[GraphNode]:
        """Return the top-k semantically closest nodes for this user."""
        embedding = await asyncio.to_thread(self._embed, query)
        await asyncio.to_thread(self._ensure_index)

        q = (
            Query(f"(@user_id:{{{user_id}}})=>[KNN {top_k} @embedding $vec AS score]")
            .sort_by("score")
            .return_fields("node_id", "label", "content", "node_type", "score")
            .dialect(2)
        )
        results = await asyncio.to_thread(
            self._r.ft(INDEX_NAME).search,
            q,
            query_params={"vec": embedding},
        )

        nodes = []
        for doc in results.docs:
            def _d(attr: str) -> str:
                val = getattr(doc, attr, "")
                return val.decode() if isinstance(val, bytes) else str(val)
            nodes.append(GraphNode(
                node_id=_d("node_id"),
                user_id=user_id,
                label=_d("label"),
                content=_d("content"),
                node_type=_d("node_type"),
                score=float(_d("score") or 0),
            ))
        return nodes

    async def get_context(self, user_id: str, query: str, top_k: int = 4) -> str:
        """
        Semantic search + 1-hop graph traversal → assembled context string.

        Returned format is ready to inject directly into a model prompt.
        """
        anchor_nodes = await self.search(user_id, query, top_k=top_k)
        if not anchor_nodes:
            return ""

        seen: set[str] = set()
        sections: list[str] = []

        for node in anchor_nodes:
            if node.node_id in seen:
                continue
            seen.add(node.node_id)
            sections.append(f"[{node.node_type.upper()}] {node.label}\n{node.content}")

            # Pull in 1-hop neighbors for relationship context.
            for relation, neighbor in await self.get_neighbors(user_id, node.node_id):
                if neighbor.node_id not in seen:
                    seen.add(neighbor.node_id)
                    sections.append(
                        f"  → {relation}: [{neighbor.node_type.upper()}] "
                        f"{neighbor.label} — {neighbor.content}"
                    )

        return "\n\n".join(sections)


# ── Singleton ─────────────────────────────────────────────────────────────────

_graph: GraphKnowledge | None = None


def get_graph_knowledge() -> GraphKnowledge:
    global _graph
    if _graph is None:
        from config import settings
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL is not set — cannot create GraphKnowledge")
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set — needed for embeddings")
        _graph = GraphKnowledge(settings.redis_url, settings.openai_api_key)
    return _graph
