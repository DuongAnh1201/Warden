"""Shared fixtures for agent tool tests."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import pytest

from ai.agents.deps import OrchestratorDeps
from observability.kill_switch import reset_kill_switch
from tools.ledger import FileLedger

# Keep the evaluator from freezing the session during unit tests.
os.environ.setdefault("CONSENT_EVAL_ENABLED", "0")


@dataclass
class Ctx:
    """Minimal stand-in for pydantic_ai RunContext[OrchestratorDeps]."""
    deps: OrchestratorDeps


@pytest.fixture(autouse=True)
def _reset_kill_switch():
    reset_kill_switch()
    yield
    reset_kill_switch()


@pytest.fixture
def ledger(tmp_path):
    return FileLedger(path=tmp_path / "ledger.jsonl")


@pytest.fixture
def deps(ledger):
    return OrchestratorDeps(
        user_id="test_user",
        ledger=ledger,
        auto_approve=True,
    )


@pytest.fixture
def ctx(deps):
    return Ctx(deps=deps)


def get_tool(agent_getter, name: str):
    """Return the raw async callable for a named tool on a pydantic-ai agent."""
    agent = agent_getter()
    for ts in agent.toolsets:
        tools = getattr(ts, "tools", {})
        if name in tools:
            return tools[name].function
    raise KeyError(f"Tool '{name}' not found")


def run(coro):
    return asyncio.run(coro)
