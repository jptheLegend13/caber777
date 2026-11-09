"""LEVEL 5 internal model gateway.

This is the single place the platform decides *which* inference backend serves
a request. It exists to make LEVEL 5 independent of any one company's AI API.

Design rules (these are architectural, not preferences):

1. **Internal inference is the production target.** A self-hosted,
   operator-controlled OpenAI-compatible runtime is tried first.
2. **External providers are optional and off by default.** They are used only
   when the operator sets ``LEVEL5_ALLOW_EXTERNAL_MODELS=1``. No external API
   is ever required to run core product intelligence.
3. **No silent fallback to an external model.** When internal inference fails,
   the failure is reported. The gateway never reaches out to a third party to
   paper over an internal fault.
4. **No provider is hard-coded.** Backends are ordered by a declared priority
   and selected by capability; a new backend is a registry entry, not a code
   change in the callers.

The gateway is deliberately transport-shaped: it speaks the OpenAI-compatible
chat protocol, which every self-hosted runtime and every external provider
also speaks, so a backend is just a base URL plus a key policy.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from level5.config import Settings, get_settings

logger = logging.getLogger("level5.gateway")

BackendClass = Literal["internal", "development", "external"]


@dataclass(frozen=True)
class Backend:
    """One inference backend the gateway can route to.

    ``class_`` records the independence posture:
    - ``internal``    — self-hosted / operator-controlled. Production target.
    - ``development`` — the OpenHands dev gateway. A development aid only.
    - ``external``    — a third-party API. Optional, never required.
    """

    name: str
    class_: BackendClass
    base_url: str
    api_key: str = ""
    model: str = ""
    priority: int = 100
    capabilities: frozenset[str] = field(
        default_factory=lambda: frozenset({"tools", "streaming", "json_mode"})
    )
    headers: dict[str, str] = field(default_factory=dict)

    def key_policy(self) -> str:
        """Whether this backend needs a credential to be usable."""
        return "none" if not self.api_key else "api_key"


@dataclass
class GatewayResult:
    text: str
    backend: str
    backend_class: BackendClass
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class NoBackendAvailable(RuntimeError):
    """No backend was permitted and reachable for the request."""


class ModelGateway:
    """Routes bare model calls to an appropriate, permitted backend.

    Instantiate with explicit backends for testing, or let it build them from
    settings with :func:`default_backends`.
    """

    def __init__(
        self,
        backends: list[Backend] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._backends = backends if backends is not None else default_backends(
            self.settings
        )
        self._health: dict[str, tuple[float, bool]] = {}
        self._health_ttl = 60.0

    # -- introspection --------------------------------------------------- #
    def backends(self) -> list[Backend]:
        """Permitted backends, best first. External backends are excluded
        unless the operator enabled them."""
        allowed = [
            b
            for b in self._backends
            if b.class_ != "external" or self.settings.allow_external_models
        ]
        if not self.settings.allow_dev_gateway:
            allowed = [b for b in allowed if b.class_ != "development"]
        return sorted(allowed, key=lambda b: (b.priority, b.name))

    def report(self) -> dict[str, Any]:
        """Describe the gateway's configuration and independence posture."""
        every = sorted(self._backends, key=lambda b: (b.priority, b.name))
        return {
            "independence": {
                "external_models_enabled": self.settings.allow_external_models,
                "dev_gateway_enabled": self.settings.allow_dev_gateway,
                "production_backend_class": "internal",
                "external_fallback_on_internal_failure": False,
            },
            "backends": [
                {
                    "name": b.name,
                    "class": b.class_,
                    "base_url": b.base_url,
                    "model": b.model,
                    "priority": b.priority,
                    "capabilities": sorted(b.capabilities),
                    "key_policy": b.key_policy(),
                    "permitted": b in self.backends(),
                }
                for b in every
            ],
            "permitted_order": [b.name for b in self.backends()],
            "note": (
                "Internal (self-hosted) inference is the production target. "
                "External providers are optional and never used as an automatic "
                "fallback for an internal failure."
            ),
        }

    # -- health ---------------------------------------------------------- #
    def _healthy(self, backend: Backend) -> bool:
        """Cheap reachability probe, cached briefly. Never raises."""
        now = time.monotonic()
        cached = self._health.get(backend.name)
        if cached and now - cached[0] < self._health_ttl:
            return cached[1]
        ok = self._probe(backend)
        self._health[backend.name] = (now, ok)
        return ok

    def _probe(self, backend: Backend) -> bool:
        if not backend.base_url:
            return False
        headers = dict(backend.headers)
        if backend.api_key:
            headers["Authorization"] = f"Bearer {backend.api_key}"
        try:
            response = httpx.get(
                f"{backend.base_url.rstrip('/')}/models", headers=headers, timeout=5.0
            )
            return response.status_code < 400
        except Exception:  # noqa: BLE001 - health must never raise
            return False

    # -- routing --------------------------------------------------------- #
    def route(
        self, required: set[str] | None = None, *, internal_only: bool = False
    ) -> Backend:
        """Pick the best permitted backend that is reachable.

        Class discipline is enforced here, because it is the independence
        guarantee:

        - Internal (self-hosted) backends are preferred.
        - If an internal backend is configured but unreachable, a *development*
          backend may take over as a development aid, but an **external**
          provider never does. The internal failure is reported instead of
          being masked by a third-party API.
        - External providers are considered only when no internal backend is
          configured at all and the operator enabled them.
        - ``internal_only`` restricts the choice to self-hosted backends, which
          is what the independence test uses to prove the internal path works.
        """
        required = required or set()
        permitted = [b for b in self.backends() if required <= b.capabilities]
        if internal_only:
            permitted = [b for b in permitted if b.class_ == "internal"]
        if not permitted:
            raise NoBackendAvailable(
                f"no permitted backend declares capabilities {sorted(required)}"
                + (" (internal-only)" if internal_only else "")
            )

        internal = [b for b in permitted if b.class_ == "internal"]
        development = [b for b in permitted if b.class_ == "development"]
        external = [b for b in permitted if b.class_ == "external"]

        if internal:
            reachable = [b for b in internal if self._healthy(b)]
            if reachable:
                return reachable[0]
            # Internal configured but down: allow a development aid, never an
            # external provider.
            reachable_dev = [b for b in development if self._healthy(b)]
            if reachable_dev:
                logger.warning(
                    "internal runtime unreachable; using development backend %s",
                    reachable_dev[0].name,
                )
                return reachable_dev[0]
            names = ", ".join(b.name for b in internal)
            raise NoBackendAvailable(
                f"internal inference backend is configured but not reachable "
                f"({names}); external fallback is disabled by design"
            )

        # No internal backend configured at all.
        for group in (development, external):
            reachable = [b for b in group if self._healthy(b)]
            if reachable:
                return reachable[0]
        names = ", ".join(b.name for b in permitted)
        raise NoBackendAvailable(
            f"no inference backend is reachable (tried: {names}); start the "
            "self-hosted runtime or configure a backend"
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        required: set[str] | None = None,
    ) -> GatewayResult:
        """Send a chat request to the best permitted backend.

        There is no cross-class fallback: if the selected backend fails, the
        error is raised. The caller decides what to do; the gateway will not
        silently switch to an external provider.
        """
        backend = self.route(required=required)
        url = f"{backend.base_url.rstrip('/')}/chat/completions"
        body: dict[str, Any] = {
            "model": backend.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        headers = {"Content-Type": "application/json", **backend.headers}
        if backend.api_key:
            headers["Authorization"] = f"Bearer {backend.api_key}"
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout) as client:
            response = await client.post(url, json=body, headers=headers)
            if response.status_code >= 400:
                raise NoBackendAvailable(
                    f"backend {backend.name} returned {response.status_code}: "
                    f"{response.text[:300]}"
                )
            payload = response.json()
        text = _extract_text(payload)
        return GatewayResult(
            text=text,
            backend=backend.name,
            backend_class=backend.class_,
            model=str(payload.get("model", backend.model)),
            usage=payload.get("usage") or {},
        )


def _extract_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        )
    return ""


def default_backends(settings: Settings) -> list[Backend]:
    """Build the standard backend list from settings.

    Order encodes intent: the self-hosted runtime first (production), then the
    OpenHands development gateway (development only), then external providers
    (optional, only when enabled).
    """
    backends: list[Backend] = []

    # 1. Self-hosted runtime — the production target.
    if settings.local_llm_base_url:
        backends.append(
            Backend(
                name="local_runtime",
                class_="internal",
                base_url=settings.local_llm_base_url,
                api_key=settings.local_llm_api_key,
                model=settings.local_llm_model,
                priority=10,
                capabilities=frozenset(
                    {"tools", "streaming", "json_mode", "reasoning"}
                ),
            )
        )

    # 2. OpenHands development gateway — development aid only.
    if settings.allow_dev_gateway:
        backends.append(
            Backend(
                name="openhands_dev_gateway",
                class_="development",
                base_url=settings.llm_gateway_url,
                api_key=settings.session_api_key,
                model=settings.llm_model,
                priority=50,
                headers={"X-Session-API-Key": settings.session_api_key}
                if settings.session_api_key
                else {},
            )
        )

    # 3. External providers — optional, keyed, never required.
    external = [
        ("openai", "OPENAI_API_KEY", "OPENAI_MODEL", "https://api.openai.com/v1", "gpt-5"),
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_MODEL",
            "https://api.anthropic.com/v1",
            "claude-sonnet-4-5",
        ),
        (
            "google",
            "GEMINI_API_KEY",
            "GEMINI_MODEL",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "gemini-2.5-pro",
        ),
    ]
    import os

    for idx, (name, key_env, model_env, base_url, default_model) in enumerate(external):
        api_key = os.environ.get(key_env, "").strip()
        if not api_key:
            continue
        backends.append(
            Backend(
                name=name,
                class_="external",
                base_url=base_url,
                api_key=api_key,
                model=os.environ.get(model_env, default_model).strip() or default_model,
                priority=100 + idx,
            )
        )
    return backends


_gateway: ModelGateway | None = None


def get_gateway() -> ModelGateway:
    global _gateway
    if _gateway is None:
        _gateway = ModelGateway()
    return _gateway


def reset_gateway() -> None:
    """Drop the cached gateway (used by tests and on settings reload)."""
    global _gateway
    _gateway = None
