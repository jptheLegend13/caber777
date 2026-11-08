"""Model-agnostic LLM access for LEVEL 5.

Two complementary paths are supported:

1. :class:`LLMClient` makes *bare* model calls through an OpenAI-compatible
   gateway. Inside the OpenHands sandbox this is the Agent Server's own
   ``/v1`` gateway, which resolves the operator-configured LLM profile.
2. :func:`refresh_managed_llm_key` fetches the short-lived managed API key so a
   delegated Agent Server conversation can authenticate with the real model.

Neither path ever writes credentials to disk or to logs.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from level5.config import Settings, get_settings

logger = logging.getLogger("level5.llm")


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

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.settings.llm_timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

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
        """Send a chat completion request and return the assistant text."""
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
