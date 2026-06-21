"""Tests for agent5 — Knowledge base agent (graph + file storage)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai.agents.agent5 import get_knowledge_base_agent
from tests.agents.conftest import get_tool, run


def _node(label: str, content: str, node_type: str = "fact", node_id: str = "node-001"):
    n = MagicMock()
    n.label = label
    n.content = content
    n.node_type = node_type
    n.node_id = node_id
    return n


def _mock_knowledge():
    k = AsyncMock()
    k.upsert_node = AsyncMock(return_value=_node("Wi-Fi Password", "Sunshine2024"))
    k.append_to_node = AsyncMock(return_value=_node("Board Meeting", "Agenda: TBD"))
    k.get_node_by_label = AsyncMock(return_value=None)
    k.get_neighbors = AsyncMock(return_value=[])
    k.add_edge = AsyncMock()
    k.get_context = AsyncMock(return_value="")
    return k


# ── save_knowledge ────────────────────────────────────────────────────────────

def test_save_knowledge_with_graph(ctx):
    k = _mock_knowledge()
    saved = _node("Wi-Fi Password", "Sunshine2024", node_id="abc12345")
    k.upsert_node = AsyncMock(return_value=saved)
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "save_knowledge")
    result = run(fn(ctx, label="Wi-Fi Password", content="Sunshine2024"))

    assert "Wi-Fi Password" in result or "abc12345" in result or "Saved" in result
    k.upsert_node.assert_called_once()


def test_save_knowledge_file_fallback(ctx):
    ctx.deps.knowledge = None
    mock_result = MagicMock(message="Created Wi-Fi Password.md", success=True)

    fn = get_tool(get_knowledge_base_agent, "save_knowledge")
    with patch("tools.knowledge_base.create_new_file", return_value=mock_result):
        result = run(fn(ctx, label="Wi-Fi Password", content="Sunshine2024"))
    assert isinstance(result, str) and len(result) > 0


# ── add_to_knowledge ──────────────────────────────────────────────────────────

def test_add_to_knowledge_appends(ctx):
    k = _mock_knowledge()
    updated = _node("Board Meeting", "Agenda: TBD\nQ3 review added")
    k.append_to_node = AsyncMock(return_value=updated)
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "add_to_knowledge")
    result = run(fn(ctx, label="Board Meeting", additional_content="Q3 review added"))

    assert "added" in result.lower() or "Board Meeting" in result
    k.append_to_node.assert_called_once()


def test_add_to_knowledge_creates_if_missing(ctx):
    """When append returns None (node didn't exist), creates a new node instead."""
    k = _mock_knowledge()
    k.append_to_node = AsyncMock(return_value=None)
    new_node = _node("New Topic", "First entry")
    k.upsert_node = AsyncMock(return_value=new_node)
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "add_to_knowledge")
    result = run(fn(ctx, label="New Topic", additional_content="First entry"))

    assert "New Topic" in result or "Created" in result or "created" in result.lower()
    k.upsert_node.assert_called_once()


# ── link_knowledge ────────────────────────────────────────────────────────────

def test_link_knowledge_approved(ctx, ledger):
    k = _mock_knowledge()
    src = _node("Dr. Chen", "dentist", node_id="src-001")
    tgt = _node("Dentist Appointment", "June 25", node_id="tgt-001")
    k.get_node_by_label = AsyncMock(side_effect=[src, tgt])
    k.add_edge = AsyncMock()
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "link_knowledge")
    result = run(fn(ctx,
        source_label="Dr. Chen",
        relation="appointment_with",
        target_label="Dentist Appointment",
    ))

    assert "Dr. Chen" in result or "Dentist" in result or "Linked" in result
    k.add_edge.assert_called_once()


def test_link_knowledge_source_not_found(ctx):
    k = _mock_knowledge()
    k.get_node_by_label = AsyncMock(return_value=None)
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "link_knowledge")
    result = run(fn(ctx,
        source_label="Ghost Node",
        relation="relates_to",
        target_label="Something",
    ))

    assert "not found" in result.lower() or "Ghost Node" in result


def test_link_knowledge_no_graph(ctx):
    ctx.deps.knowledge = None
    fn = get_tool(get_knowledge_base_agent, "link_knowledge")
    result = run(fn(ctx,
        source_label="A",
        relation="connects",
        target_label="B",
    ))
    assert "Redis" in result or "not configured" in result


# ── recall_knowledge ──────────────────────────────────────────────────────────

def test_recall_knowledge_found(ctx):
    k = _mock_knowledge()
    k.get_context = AsyncMock(return_value="[FACT] Wi-Fi Password\nSunshine2024")
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "recall_knowledge")
    result = run(fn(ctx, query="Wi-Fi password"))

    assert "Sunshine2024" in result or "Wi-Fi" in result


def test_recall_knowledge_not_found_graph(ctx):
    k = _mock_knowledge()
    k.get_context = AsyncMock(return_value="")
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "recall_knowledge")
    result = run(fn(ctx, query="something obscure"))

    assert "No relevant" in result or "not found" in result.lower()


def test_recall_knowledge_file_fallback(ctx):
    ctx.deps.knowledge = None
    mock_result = MagicMock(success=False, message="Not found.", context="")

    fn = get_tool(get_knowledge_base_agent, "recall_knowledge")
    with patch("tools.knowledge_base.read_file", return_value=mock_result):
        result = run(fn(ctx, query="anything"))
    assert isinstance(result, str)


# ── get_topic ─────────────────────────────────────────────────────────────────

def test_get_topic_returns_content(ctx):
    k = _mock_knowledge()
    node = _node("Board Meeting", "Next: July 1")
    k.get_node_by_label = AsyncMock(return_value=node)
    k.get_neighbors = AsyncMock(return_value=[])
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "get_topic")
    result = run(fn(ctx, label="Board Meeting"))

    assert "Board Meeting" in result or "July 1" in result


def test_get_topic_with_neighbors(ctx):
    k = _mock_knowledge()
    node = _node("Project Alpha", "Main project", node_id="p-001")
    neighbor = _node("Alice", "Lead engineer")
    k.get_node_by_label = AsyncMock(return_value=node)
    k.get_neighbors = AsyncMock(return_value=[("lead_by", neighbor)])
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "get_topic")
    result = run(fn(ctx, label="Project Alpha"))

    assert "Project Alpha" in result
    assert "Alice" in result or "lead_by" in result


def test_get_topic_not_found(ctx):
    k = _mock_knowledge()
    k.get_node_by_label = AsyncMock(return_value=None)
    ctx.deps.knowledge = k

    fn = get_tool(get_knowledge_base_agent, "get_topic")
    result = run(fn(ctx, label="ghost"))

    assert "not found" in result.lower() or "ghost" in result.lower()
