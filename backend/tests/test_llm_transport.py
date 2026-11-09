"""Tests for LLM transport selection, the gateway probe and cooldown."""

from __future__ import annotations

import time

import pytest

from level5.config import Settings
from level5.llm.client import _GATEWAY_COOLDOWN_S, LLMClient, LLMError, LLMResult


def _client(transport: str = "auto", *, gateway_ok: bool = True) -> LLMClient:
    client = LLMClient(Settings())
    client.settings.llm_transport = transport
    # Cache the probe so tests never touch the network; a real deployment
    # probes once and caches the verdict the same way.
    client._gateway_probed = True
    client._gateway_ok = gateway_ok
    return client


class TestGatewayCooldown:
    async def test_gateway_failure_arms_cooldown_and_falls_back(self, monkeypatch):
        client = _client("auto")
        calls: list[str] = []

        async def boom(*a, **k):
            calls.append("gateway")
            raise RuntimeError("gateway 500: upstream error")

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


class TestGatewayProbe:
    async def test_empty_registry_skips_the_gateway(self, monkeypatch):
        """A gateway with no models must not be attempted at all."""
        client = LLMClient(Settings())
        client.settings.llm_transport = "auto"
        calls: list[str] = []

        async def empty_probe() -> bool:
            return False

        async def gateway(*a, **k):
            calls.append("gateway")
            return LLMResult(text="should not happen")

        async def ask(messages):
            calls.append("ask_agent")
            return LLMResult(text="ok")

        monkeypatch.setattr(client, "probe_gateway", empty_probe)
        monkeypatch.setattr(client, "_chat_gateway", gateway)
        monkeypatch.setattr(client, "_chat_ask_agent", ask)

        result = await client.chat([{"role": "user", "content": "hi"}])
        assert result.text == "ok"
        assert calls == ["ask_agent"]

    async def test_probe_is_cached(self, monkeypatch):
        client = LLMClient(Settings())
        probes = {"n": 0}

        async def probe() -> bool:
            probes["n"] += 1
            return False

        monkeypatch.setattr(client, "probe_gateway", probe)
        await client._gateway_usable()
        await client._gateway_usable()
        assert probes["n"] == 1


class TestLLMErrorTransience:
    def test_network_fault_is_transient(self):
        assert LLMError("connection reset").transient is True

    def test_5xx_and_429_are_transient(self):
        assert LLMError("gateway 500", status_code=500).transient is True
        assert LLMError("gateway 429", status_code=429).transient is True

    def test_404_is_not_transient(self):
        assert LLMError("gateway 404", status_code=404).transient is False
