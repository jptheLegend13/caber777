"""Tests for Agent Server event pagination.

The server caps a page at 100 events and hands back an opaque ``next_page_id``
cursor. Paging on a timestamp instead silently duplicates or skips events that
share a timestamp (common inside one agent step), so the client must follow the
cursor. These tests drive the real pagination loop against a simulated server
transport (the network boundary only).
"""

from __future__ import annotations

import httpx
import pytest

from level5.runtime.agent_server import AgentServerClient


def _client_with(handler) -> AgentServerClient:
    client = AgentServerClient()
    client._client = httpx.AsyncClient(
        base_url="http://agent-server.test",
        transport=httpx.MockTransport(handler),
    )
    return client


def _event(index: int, timestamp: str = "2026-01-01T00:00:00") -> dict:
    return {"id": f"evt-{index}", "timestamp": timestamp, "kind": "ActionEvent"}


@pytest.mark.asyncio
async def test_get_events_returns_cursor():
    seen_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json={"items": [_event(1)], "next_page_id": "p2"})

    client = _client_with(handler)
    events, cursor = await client.get_events("conv-1", limit=100)
    assert [e["id"] for e in events] == ["evt-1"]
    assert cursor == "p2"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_all_events_follows_page_id_cursor():
    pages = {
        None: {"items": [_event(i) for i in range(100)], "next_page_id": "p2"},
        "p2": {"items": [_event(i) for i in range(100, 150)], "next_page_id": None},
    }
    requested_cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("page_id")
        requested_cursors.append(cursor)
        return httpx.Response(200, json=pages[cursor])

    client = _client_with(handler)
    events = await client.get_all_events("conv-1")
    assert len(events) == 150
    assert len({e["id"] for e in events}) == 150
    assert requested_cursors == [None, "p2"]
    await client.aclose()


@pytest.mark.asyncio
async def test_get_all_events_stops_on_short_page_without_cursor():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_event(1)], "next_page_id": None})

    client = _client_with(handler)
    events = await client.get_all_events("conv-1")
    assert [e["id"] for e in events] == ["evt-1"]
    await client.aclose()


@pytest.mark.asyncio
async def test_get_all_events_deduplicates_repeated_boundary_events():
    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("page_id")
        if cursor is None:
            return httpx.Response(
                200, json={"items": [_event(1), _event(2)], "next_page_id": "p2"}
            )
        return httpx.Response(200, json={"items": [_event(2), _event(3)], "next_page_id": None})

    client = _client_with(handler)
    events = await client.get_all_events("conv-1")
    assert [e["id"] for e in events] == ["evt-1", "evt-2", "evt-3"]
    await client.aclose()


@pytest.mark.asyncio
async def test_get_events_tolerates_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client_with(handler)
    events, cursor = await client.get_events("conv-1")
    assert events == []
    assert cursor is None
    await client.aclose()
