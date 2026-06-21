"""Tests for agent3 — Web search agent (Serper API)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ai.agents.agent3 import get_search_agent
from tests.agents.conftest import get_tool, run


def test_search_web_no_api_key(ctx):
    """Returns empty list silently when no API key is configured."""
    ctx.deps.search_api_key = ""
    fn = get_tool(get_search_agent, "search_web")
    result = run(fn(ctx, "latest AI news"))
    assert result == []


def test_search_web_returns_results(ctx):
    """Happy path: Serper returns organic results."""
    ctx.deps.search_api_key = "fake-key"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "organic": [
            {"title": "AI is great", "link": "https://example.com", "snippet": "..."},
            {"title": "More AI news", "link": "https://example2.com", "snippet": "..."},
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    fn = get_tool(get_search_agent, "search_web")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        result = run(fn(ctx, "AI news"))

    assert len(result) == 2
    assert result[0]["title"] == "AI is great"


def test_search_web_403_returns_empty(ctx):
    """403 from Serper (bad/expired key) returns [] and does not raise."""
    ctx.deps.search_api_key = "bad-key"

    mock_request = MagicMock()
    mock_response = MagicMock(status_code=403, text='{"message":"Unauthorized."}')
    http_error = httpx.HTTPStatusError("403", request=mock_request, response=mock_response)

    fn = get_tool(get_search_agent, "search_web")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=http_error):
        result = run(fn(ctx, "query"))

    assert result == []


def test_search_web_network_error_returns_empty(ctx):
    """Network failure returns [] and does not raise."""
    ctx.deps.search_api_key = "some-key"
    fn = get_tool(get_search_agent, "search_web")
    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        side_effect=httpx.RequestError("timeout"),
    ):
        result = run(fn(ctx, "query"))
    assert result == []


def test_search_web_empty_organic(ctx):
    """Serper returns 200 but no organic results."""
    ctx.deps.search_api_key = "ok-key"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"organic": []}
    mock_resp.raise_for_status = MagicMock()

    fn = get_tool(get_search_agent, "search_web")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        result = run(fn(ctx, "obscure topic"))
    assert result == []
