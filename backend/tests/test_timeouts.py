"""Tests for terminal-state reporting in the Agent Server client.

A failure must always carry a concrete cause and the conversation id, so a
post-mortem is possible. A conversation that never finishes must be reported
as a timeout, not left as an anonymous "running".
"""

from __future__ import annotations

import pytest

from level5.config import Settings
from level5.runtime.agent_server import AgentServerClient


def _client() -> AgentServerClient:
    return AgentServerClient(Settings())


class TestWaitForCompletion:
    async def test_timeout_names_a_cause_and_conversation(self, monkeypatch):
        client = _client()

        async def still_running(conversation_id: str) -> dict:
            return {"execution_status": "running"}

        async def no_events(conversation_id: str, **kwargs) -> list:
            return []

        monkeypatch.setattr(client, "get_conversation", still_running)
        monkeypatch.setattr(client, "get_all_events", no_events)

        result = await client.wait_for_completion(
            "conv_timeout", poll_interval=0.01, timeout=0.05
        )
        assert result.status == "timeout"
        assert result.error and "time limit" in result.error
        assert "conv_timeout" in result.error
        assert result.retryable is True

    async def test_finished_conversation_has_no_error(self, monkeypatch):
        client = _client()

        async def finished(conversation_id: str) -> dict:
            return {"execution_status": "finished"}

        async def no_events(conversation_id: str, **kwargs) -> list:
            return []

        monkeypatch.setattr(client, "get_conversation", finished)
        monkeypatch.setattr(client, "get_all_events", no_events)

        result = await client.wait_for_completion(
            "conv_ok", poll_interval=0.01, timeout=1.0
        )
        assert result.status == "finished"
        assert result.error is None
        assert result.succeeded


class TestCollectResult:
    async def test_stopped_conversation_names_a_cause(self, monkeypatch):
        client = _client()

        async def no_events(conversation_id: str, **kwargs) -> list:
            return []

        monkeypatch.setattr(client, "get_all_events", no_events)
        result = await client.collect_result("conv_stop", "stopped")
        assert result.status == "stopped"
        assert result.error and "stopped" in result.error
        assert result.retryable is False

    async def test_unknown_state_still_names_a_cause(self, monkeypatch):
        client = _client()

        async def no_events(conversation_id: str, **kwargs) -> list:
            return []

        monkeypatch.setattr(client, "get_all_events", no_events)
        result = await client.collect_result("conv_weird", "quarantined")
        assert result.error and "quarantined" in result.error

    async def test_error_state_reads_the_terminal_error_event(self, monkeypatch):
        client = _client()

        async def no_events(conversation_id: str, **kwargs) -> list:
            return []

        async def terminal(conversation_id: str) -> dict:
            return {
                "code": "LLMBadRequestError",
                "detail": "context length exceeded",
                "classification": {"retryable": False},
            }

        monkeypatch.setattr(client, "get_all_events", no_events)
        monkeypatch.setattr(client, "last_error", terminal)
        result = await client.collect_result("conv_err", "error")
        assert "LLMBadRequestError" in result.error
        assert "context length exceeded" in result.error
        assert result.retryable is False
