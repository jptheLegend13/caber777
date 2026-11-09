"""Model-agnostic LLM access for LEVEL 5.

Bare (non-agent) model calls - used by request understanding, planning, research
synthesis, the CABER architect and the problem solver - travel over one of two
transports:

1. **OpenAI-compatible gateway** (``{agent_server}/v1/chat/completions``). This
   is the preferred transport when the deployment has populated the gateway's
   model registry. Some Agent Server deployments ship with an *empty* registry
   (``GET /v1/models`` -> ``{"data":[]}``) and answer every request with
   ``404 Profile 'Default' not found``.
2. **ask_agent** (``POST /api/conversations/{id}/ask_agent``). This asks an
   existing, profile-resolved conversation a question and returns the model's
   text. It works on deployments where the gateway does not, because the
   conversation's LLM profile is resolved by the server rather than by name.

:class:`LLMClient` selects a transport (``LEVEL5_LLM_TRANSPORT`` =
``auto`` | ``gateway`` | ``ask_agent``) and, in ``auto`` mode, falls back from
the gateway to ``ask_agent`` on the first gateway failure so a broken gateway
degrades to a working path instead of failing the whole request.

:func:`refresh_managed_llm_key` fetches the short-lived managed API key so a
delegated Agent Server conversation can authenticate with the real model.

No path ever writes credentials to disk or to logs.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from level5.config import Settings, get_settings

logger = logging.getLogger("level5.llm")

# How long to skip the gateway after an observed failure, in seconds.
_GATEWAY_COOLDOWN_S = 300.0


class LLMError(RuntimeError):
    """Raised when the model backend cannot satisfy a request."""


@dataclass
class LLMUsage:
    """Token accounting for a single call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "LLMUsage":
        usage = payload.get("usage") or {}
        return cls(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            model=str(payload.get("model", "")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
        }


@dataclass
class LLMResult:
    text: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    """Async OpenAI-compatible chat client with retry and JSON helpers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.AsyncClient | None = None
        # An empty gateway model registry is a deployment fault, not a
        # transient error. Once observed, skip the gateway for a short window
        # instead of paying three failing round-trips on every call.
        self._gateway_down_until: float = 0.0

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.settings.llm_timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def probe_gateway(self) -> bool:
        """Return True when the OpenAI-compatible gateway can serve models.

        The gateway is only usable when its model registry is populated. An
        empty registry is a deployment fault, not a transient error, so the
        health endpoint reports it rather than silently falling back.
        """
        try:
            client = await self._http()
            response = await client.get(
                f"{self.settings.llm_gateway_url}/models", headers=self._headers()
            )
            if response.status_code >= 400:
                return False
            data = response.json().get("data")
            return bool(data)
        except Exception:  # noqa: BLE001 - health must never raise
            return False

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.session_api_key:
            headers["X-Session-API-Key"] = self.settings.session_api_key
        return headers

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResult:
        """Send a chat request over the configured transport and return the text.

        ``auto`` tries the OpenAI-compatible gateway first and falls back to
        ``ask_agent``. The gateway is the richer transport (real token usage,
        native JSON mode), so it is preferred where it works; ``ask_agent`` is
        the path that works on deployments whose gateway model registry is
        empty.
        """
        transport = (self.settings.llm_transport or "auto").lower()
        order = {
            "gateway": ("gateway",),
            "ask_agent": ("ask_agent",),
        }.get(transport, ("gateway", "ask_agent"))

        # In auto mode, skip the gateway while it is known to be down. An
        # explicit "gateway" transport always attempts it, so a failure is
        # still surfaced to the caller rather than hidden.
        if (
            transport == "auto"
            and len(order) > 1
            and order[0] == "gateway"
            and time.monotonic() < self._gateway_down_until
        ):
            order = order[1:]

        errors: list[str] = []
        for name in order:
            try:
                if name == "gateway":
                    return await self._chat_gateway(
                        messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                    )
                return await self._chat_ask_agent(messages)
            except Exception as exc:  # noqa: BLE001 - try the next transport
                errors.append(f"{name}: {exc}")
                if name == "gateway" and len(order) > 1:
                    self._gateway_down_until = time.monotonic() + _GATEWAY_COOLDOWN_S
                if len(order) > 1:
                    logger.warning("LLM transport %s failed: %s", name, exc)
        raise LLMError("LLM request failed on all transports: " + " | ".join(errors))

    async def _chat_gateway(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResult:
        """Call the OpenAI-compatible gateway, retrying transient faults."""
        url = f"{self.settings.llm_gateway_url}/chat/completions"
        body: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format

        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries):
            try:
                client = await self._http()
                response = await client.post(url, json=body, headers=self._headers())
                if response.status_code >= 400:
                    raise LLMError(
                        f"gateway {response.status_code}: {response.text[:300]}"
                    )
                payload = response.json()
                text = _extract_text(payload)
                return LLMResult(
                    text=text,
                    usage=LLMUsage.from_response(payload),
                    raw=payload,
                )
            except Exception as exc:  # noqa: BLE001 - retried then surfaced
                last_error = exc
                logger.warning("LLM attempt %s failed: %s", attempt + 1, exc)
        raise LLMError(f"LLM request failed after retries: {last_error}")

    async def _chat_ask_agent(self, messages: list[dict[str, Any]]) -> LLMResult:
        """Make a bare model call through the Agent Server's ``ask_agent`` API.

        The server resolves the model from the conversation's LLM profile, so
        this works when the OpenAI-compatible gateway's registry is empty. The
        full message list is rendered into the single ``question`` field; the
        server appends its own agent context, which is why the system prompt is
        passed as data ("You must follow these instructions...") rather than as
        a trusted system role.

        The probe conversation is created with no tools, so this is a plain
        model call and cannot touch the workspace.
        """
        client = await self._http()
        workspace = Path(tempfile.gettempdir()) / "level5-llm-probe"
        workspace.mkdir(parents=True, exist_ok=True)
        create_body: dict[str, Any] = {
            "agent_settings": {
                "agent_kind": "openhands",
                "llm": {
                    "model": self.settings.llm_model_raw,
                    "auth_type": "api_key",
                    "base_url": self.settings.llm_base_url,
                    "usage_id": "level5",
                    "num_retries": 2,
                    "drop_params": True,
                    "native_tool_calling": True,
                },
                "tools": [],
                "include_default_tools": False,
            },
            "workspace": {"kind": "LocalWorkspace", "working_dir": str(workspace)},
            "confirmation_policy": {"kind": "NeverConfirm"},
            "max_iterations": 5,
            "worktree": False,
            "initial_message": {
                "role": "user",
                "content": [{"type": "text", "text": "standby"}],
                "run": False,
            },
        }
        response = await client.post(
            f"{self.settings.agent_server_url}/api/conversations",
            json=create_body,
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise LLMError(
                f"ask_agent: create conversation failed {response.status_code}: "
                f"{response.text[:200]}"
            )
        conversation_id = response.json()["id"]
        try:
            ask = await client.post(
                f"{self.settings.agent_server_url}/api/conversations/"
                f"{conversation_id}/ask_agent",
                json={"question": _render_question(messages)},
                headers=self._headers(),
            )
            if ask.status_code >= 400:
                raise LLMError(
                    f"ask_agent {ask.status_code}: {ask.text[:300]}"
                )
            text = str(ask.json().get("response", ""))
            return LLMResult(text=text, usage=LLMUsage(model=self.settings.llm_model_raw))
        finally:
            # Best-effort cleanup; a leaked probe conversation is harmless.
            try:
                await client.delete(
                    f"{self.settings.agent_server_url}/api/conversations/"
                    f"{conversation_id}",
                    headers=self._headers(),
                )
            except Exception:  # noqa: BLE001 - cleanup must not mask the result
                pass

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], LLMUsage]:
        """Request a JSON object and parse it, tolerating markdown fences."""
        result = await self.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        data = parse_json_loose(result.text)
        if data is None:
            # One repair attempt: ask the model to return strict JSON only.
            repair = messages + [
                {"role": "assistant", "content": result.text[:4000]},
                {
                    "role": "user",
                    "content": "Return ONLY the JSON object. No prose, no code fences.",
                },
            ]
            result = await self.chat(
                repair,
                model=model,
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            data = parse_json_loose(result.text)
        if data is None:
            raise LLMError("model did not return parseable JSON")
        return data, result.usage


def _extract_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        ]
        return "".join(parts)
    return ""


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _render_question(messages: list[dict[str, Any]]) -> str:
    """Flatten a chat message list into the single question ask_agent accepts.

    The system instruction is passed as data, not as a trusted system role: the
    Agent Server wraps ``question`` in its own conversation context, so anything
    phrased as a role would be interpreted loosely. Stating it as an explicit
    instruction keeps the model on task for JSON-producing callers.
    """
    system_parts: list[str] = []
    dialogue: list[str] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in (None, "text")
            )
        text = str(content)
        if role == "system":
            system_parts.append(text)
        elif role == "assistant":
            dialogue.append(f"Assistant: {text}")
        else:
            dialogue.append(text)
    parts: list[str] = []
    if system_parts:
        parts.append(
            "You must follow these instructions exactly for the next reply:\n"
            + "\n\n".join(system_parts)
        )
    parts.extend(dialogue)
    return "\n\n".join(parts).strip() or "(no question)"


def parse_json_loose(text: str) -> dict[str, Any] | None:
    """Parse JSON from model output, stripping code fences and prose."""
    if not text:
        return None
    candidates: list[str] = [text.strip()]
    candidates.extend(match.strip() for match in _FENCE.findall(text))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


async def refresh_managed_llm_key(settings: Settings | None = None) -> str | None:
    """Fetch the short-lived managed LLM key, or ``None`` when unavailable.

    The value is returned to the caller and never logged.
    """
    settings = settings or get_settings()
    if not settings.llm_refresh_url or not settings.session_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                settings.llm_refresh_url,
                headers={"X-Session-API-Key": settings.session_api_key},
            )
            if response.status_code >= 400:
                logger.warning("managed key refresh failed: %s", response.status_code)
                return None
            return response.text.strip()
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("managed key refresh error: %s", exc)
        return None


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return the process-wide LLM client."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
