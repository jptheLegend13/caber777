"""Tests for LLM transport selection and gateway cooldown."""

from __future__ import annotations

import time

import pytest

from level5.llm.client import LLMClient, LLMResult, _GATEWAY_COOLDOWN_S
from level5.config import Settings


def _client(transport: str = "auto") -> LLMClient:
    client = LLMClient(Settings())
    client.settings.llm_transport = transport
    return client


class TestGatewayCooldown:
    async def test_gateway_failure_arms_cooldown_and_falls_back(self, monkeypatch):
        client = _client("auto")
        calls: list[str] = []

        async def boom(*a, **k):
            calls.append("gateway")
            raise RuntimeError("gateway 404: Profile 'Default' not found")

        async def ask(messages):
            calls.append("ask_agent")
            return LLMResult(text="ok")

        monkeypatch.setattr(client, "_chat_gateway", boom)
        monkeypatch.setattr(client, "_chat_ask_agent", ask)

        first = await client.chat([{"role": "user", "content": "hi"}])
        assert first.text == "ok"
        assert calls == ["gateway", "ask_agent"]
        assert client._gateway_down_until > time.monotonic()

        # The second call must not pay the failing gateway round-trip again.
        calls.clear()
        second = await client.chat([{"role": "user", "content": "hi"}])
        assert second.text == "ok"
        assert calls == ["ask_agent"]

    async def test_explicit_gateway_transport_always_attempts_it(self, monkeypatch):
        client = _client("gateway")
        client._gateway_down_until = time.monotonic() + _GATEWAY_COOLDOWN_S
        attempted = {"n": 0}

        async def boom(*a, **k):
            attempted["n"] += 1
            raise RuntimeError("gateway down")

        monkeypatch.setattr(client, "_chat_gateway", boom)
        with pytest.raises(Exception):
            await client.chat([{"role": "user", "content": "hi"}])
        # An explicit choice is honoured, so the failure is surfaced, not hidden.
        assert attempted["n"] == 1

    async def test_cooldown_expiry_retries_the_gateway(self, monkeypatch):
        client = _client("auto")
        client._gateway_down_until = time.monotonic() - 1  # already expired
        calls: list[str] = []

        async def gateway(*a, **k):
            calls.append("gateway")
            return LLMResult(text="from gateway")

        async def ask(messages):
            calls.append("ask_agent")
            return LLMResult(text="from ask_agent")

        monkeypatch.setattr(client, "_chat_gateway", gateway)
        monkeypatch.setattr(client, "_chat_ask_agent", ask)
        result = await client.chat([{"role": "user", "content": "hi"}])
        assert result.text == "from gateway"
        assert calls == ["gateway"]
