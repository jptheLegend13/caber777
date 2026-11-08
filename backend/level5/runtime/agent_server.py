"""Client for the OpenHands Agent Server.

This is LEVEL 5's execution substrate. Every unit of real work - writing
files, running builds, executing tests - happens inside an Agent Server
conversation that owns its own workspace. The client creates conversations,
streams their events, and reports terminal state plus concrete evidence
(files created, commands run).

It talks to the server's documented REST API rather than reimplementing agent
execution, so LEVEL 5 benefits from the SDK's sandboxing, tool execution and
security model.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from level5.config import Settings, get_settings
from level5.llm.client import refresh_managed_llm_key

logger = logging.getLogger("level5.runtime")

TERMINAL_STATUSES = {"finished", "error", "stopped", "idle"}


class AgentServerError(RuntimeError):
    """Raised when the Agent Server rejects or fails an operation."""


@dataclass
class ConversationHandle:
    id: str
    workspace_path: str
    status: str = "running"


@dataclass
class ExecutionResult:
    """Outcome of one agent conversation, with verifiable evidence."""

    conversation_id: str
    status: str
    iterations: int = 0
    final_message: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "finished" and not self.error


class AgentServerClient:
    """Async REST client for the Agent Server."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.settings.agent_server_url,
                timeout=httpx.Timeout(60.0, read=600.0),
                headers={"X-Session-API-Key": self.settings.session_api_key},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def healthy(self) -> dict[str, Any] | None:
        """Return server identity, or ``None`` when unreachable."""
        try:
            client = await self._http()
            response = await client.get("/")
            if response.status_code == 200:
                return response.json()
        except Exception as exc:  # noqa: BLE001 - health probe
            logger.debug("agent server health failed: %s", exc)
        return None

    async def _build_agent_settings(
        self, *, tools: list[str], system_prompt: str | None
    ) -> dict[str, Any]:
        """Assemble a self-contained agent settings payload.

        The managed LLM key is fetched fresh for each conversation so long
        sessions never hold a stale credential.
        """
        api_key = await refresh_managed_llm_key(self.settings)
        llm: dict[str, Any] = {
            "model": self.settings.llm_model_raw,
            "auth_type": "api_key",
            "base_url": self.settings.llm_base_url,
            "usage_id": "level5",
            "num_retries": 3,
            "stream": True,
            "drop_params": True,
            "native_tool_calling": True,
            "caching_prompt": True,
        }
        if api_key:
            llm["api_key"] = api_key

        settings: dict[str, Any] = {
            "agent_kind": "openhands",
            "llm": llm,
            "tools": [{"name": name, "params": {}} for name in tools],
            "include_default_tools": False,
        }
        if system_prompt:
            settings["agent_context"] = {
                "system_prompt_suffix": system_prompt,
            }
        return settings

    async def create_conversation(
        self,
        *,
        working_dir: str,
        initial_message: str,
        tools: list[str] | None = None,
        system_prompt: str | None = None,
        max_iterations: int | None = None,
        runtime: str | None = None,
        run: bool = True,
        conversation_id: str | None = None,
    ) -> ConversationHandle:
        """Start a conversation bound to ``working_dir`` and send the task."""
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        tools = tools or ["terminal", "file_editor", "task_tracker"]
        agent_settings = await self._build_agent_settings(
            tools=tools, system_prompt=system_prompt
        )
        body: dict[str, Any] = {
            "agent_settings": agent_settings,
            "workspace": {"kind": "LocalWorkspace", "working_dir": working_dir},
            "confirmation_policy": {"kind": "NeverConfirm"},
            "max_iterations": max_iterations or self.settings.default_max_iterations,
            "stuck_detection": True,
            "worktree": False,
            "initial_message": {
                "role": "user",
                "content": [{"type": "text", "text": initial_message}],
                "run": run,
            },
        }
        if conversation_id:
            body["conversation_id"] = conversation_id
        chosen_runtime = runtime or self.settings.conversation_runtime
        if chosen_runtime in ("local", "docker"):
            body["conversation_runtime"] = chosen_runtime
        if self.settings.default_max_budget:
            body["max_budget_per_run"] = self.settings.default_max_budget

        client = await self._http()
        response = await client.post("/api/conversations", json=body)
        if response.status_code >= 400:
            raise AgentServerError(
                f"create conversation failed {response.status_code}: {response.text[:500]}"
            )
        payload = response.json()
        return ConversationHandle(
            id=payload["id"],
            workspace_path=working_dir,
            status=payload.get("execution_status", "running"),
        )

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        client = await self._http()
        response = await client.get(f"/api/conversations/{conversation_id}")
        if response.status_code >= 400:
            raise AgentServerError(
                f"get conversation failed {response.status_code}: {response.text[:300]}"
            )
        return response.json()

    async def get_events(
        self, conversation_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        client = await self._http()
        response = await client.get(
            f"/api/conversations/{conversation_id}/events/search",
            params={"limit": min(limit, 100), "sort_order": "TIMESTAMP"},
        )
        if response.status_code >= 400:
            return []
        payload = response.json()
        return payload.get("items") or payload.get("events") or []

    async def send_message(self, conversation_id: str, text: str, *, run: bool = True) -> None:
        client = await self._http()
        response = await client.post(
            f"/api/conversations/{conversation_id}/events",
            json={
                "role": "user",
                "content": [{"type": "text", "text": text}],
                "run": run,
            },
        )
        if response.status_code >= 400:
            raise AgentServerError(
                f"send message failed {response.status_code}: {response.text[:300]}"
            )

    async def interrupt(self, conversation_id: str) -> None:
        client = await self._http()
        await client.post(f"/api/conversations/{conversation_id}/interrupt")

    async def run_to_completion(
        self,
        *,
        working_dir: str,
        task_prompt: str,
        tools: list[str] | None = None,
        system_prompt: str | None = None,
        max_iterations: int | None = None,
        runtime: str | None = None,
        poll_interval: float = 3.0,
        timeout: float = 1800.0,
    ) -> ExecutionResult:
        """Create a conversation and wait for it to reach a terminal state."""
        handle = await self.create_conversation(
            working_dir=working_dir,
            initial_message=task_prompt,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            runtime=runtime,
        )
        return await self.wait_for_completion(
            handle.id, poll_interval=poll_interval, timeout=timeout
        )

    async def wait_for_completion(
        self,
        conversation_id: str,
        *,
        poll_interval: float = 3.0,
        timeout: float = 1800.0,
    ) -> ExecutionResult:
        """Poll a conversation until it finishes, then collect evidence."""
        deadline = asyncio.get_event_loop().time() + timeout
        status = "running"
        while asyncio.get_event_loop().time() < deadline:
            try:
                data = await self.get_conversation(conversation_id)
                status = data.get("execution_status", "running")
            except AgentServerError as exc:
                logger.warning("poll failed: %s", exc)
                await asyncio.sleep(poll_interval)
                continue
            if status in TERMINAL_STATUSES:
                # Give the server a moment to flush the final events.
                await asyncio.sleep(1.0)
                break
            await asyncio.sleep(poll_interval)
        return await self.collect_result(conversation_id, status)

    async def collect_result(
        self, conversation_id: str, status: str | None = None
    ) -> ExecutionResult:
        """Read the event stream and extract actions, files and commands."""
        if status is None:
            data = await self.get_conversation(conversation_id)
            status = data.get("execution_status", "unknown")
        events = await self.get_events(conversation_id, limit=100)

        actions: list[dict[str, Any]] = []
        files: set[str] = set()
        commands: list[str] = []
        final_message = ""
        error: str | None = None

        for event in events:
            kind = event.get("kind")
            if kind == "ActionEvent":
                tool = event.get("tool_name") or event.get("action", {}).get("kind")
                action = event.get("action") or {}
                actions.append({"tool": tool, "id": event.get("id")})
                args = action.get("args") or {}
                path = args.get("path")
                if path:
                    files.add(path)
                command = args.get("command")
                if command:
                    commands.append(command)
            elif kind == "MessageEvent" and event.get("source") == "agent":
                message = event.get("llm_message") or {}
                content = message.get("content") or []
                text = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
                if text:
                    final_message = text
            elif kind == "ConversationErrorEvent":
                error = event.get("detail") or event.get("code") or "conversation error"

        if status == "error" and not error:
            error = "agent conversation ended in error"

        return ExecutionResult(
            conversation_id=conversation_id,
            status=status,
            iterations=len(actions),
            final_message=final_message,
            actions=actions,
            files_changed=sorted(files),
            commands_run=commands,
            error=error,
        )

    async def stream_events(
        self, conversation_id: str, *, poll_interval: float = 2.0
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield new events as a conversation progresses (polling adapter)."""
        seen: set[str] = set()
        while True:
            try:
                events = await self.get_events(conversation_id, limit=100)
            except Exception:  # noqa: BLE001 - transient
                events = []
            for event in events:
                event_id = event.get("id", "")
                if event_id and event_id not in seen:
                    seen.add(event_id)
                    yield event
            try:
                data = await self.get_conversation(conversation_id)
            except Exception:  # noqa: BLE001 - transient
                await asyncio.sleep(poll_interval)
                continue
            if data.get("execution_status") in TERMINAL_STATUSES:
                await asyncio.sleep(1.0)
                for event in await self.get_events(conversation_id, limit=100):
                    event_id = event.get("id", "")
                    if event_id and event_id not in seen:
                        seen.add(event_id)
                        yield event
                return
            await asyncio.sleep(poll_interval)


_client: AgentServerClient | None = None


def get_agent_client() -> AgentServerClient:
    global _client
    if _client is None:
        _client = AgentServerClient()
    return _client
