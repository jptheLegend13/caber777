"""Model and agent provider registry.

LEVEL 5 must not be hardcoded around one model. This module holds a registry of
provider *definitions*: what each provider's endpoint is, which environment
variables hold its credentials, what it can do (tools, vision, reasoning) and
what its context limit is. It resolves which providers are actually usable in
the current environment and selects a provider for a task.

Design rules enforced here:

- Credentials are read from the environment at request time and are **never**
  returned by :func:`describe` or any other public method. Only the *name* of
  the environment variable is exposed.
- Capability metadata is descriptive, not a performance ranking. Nothing here
  claims one provider is better than another; routing is by declared capability
  and by what the operator has configured.
- An unconfigured provider is reported as unavailable with a reason, not
  silently skipped.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger("level5.providers")

ProviderKind = Literal[
    "openai", "anthropic", "google", "openai_compatible", "local", "openhands"
]

# Task traits a caller can require of a provider.
Capability = Literal[
    "tools", "vision", "reasoning", "long_context", "streaming", "json_mode"
]


@dataclass(frozen=True)
class ProviderSpec:
    """Static definition of a provider. Contains no secrets."""

    name: str
    kind: ProviderKind
    label: str
    base_url: str
    api_key_env: str
    # Optional environment variable that overrides the default model.
    model_env: str = ""
    default_model: str = ""
    context_limit: int = 128_000
    capabilities: frozenset[str] = field(default_factory=frozenset)
    # An OpenAI-compatible gateway that needs no key of its own, such as the
    # Agent Server's /v1 endpoint, is "managed": usable when the platform has
    # its own credentials for it.
    managed: bool = False
    notes: str = ""

    def as_dict(self) -> dict[str, object]:
        """Serialisable view. Exposes the *name* of the key env var only."""
        return {
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "default_model": self.default_model,
            "context_limit": self.context_limit,
            "capabilities": sorted(self.capabilities),
            "managed": self.managed,
            "notes": self.notes,
        }


# Definitions for the providers the directive names. These are endpoint and
# capability facts, not endorsements.
_PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="openhands",
        kind="openhands",
        label="OpenHands managed gateway",
        base_url="",  # resolved at runtime from settings
        api_key_env="OH_SESSION_API_KEYS_0",
        default_model="openhands_Default",
        context_limit=128_000,
        capabilities=frozenset({"tools", "reasoning", "streaming", "json_mode"}),
        managed=True,
        notes=(
            "The Agent Server's OpenAI-compatible /v1 gateway. Resolves the "
            "operator's configured LLM profile and is the sanctioned path for "
            "bare model calls inside the sandbox."
        ),
    ),
    ProviderSpec(
        name="openai",
        kind="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        default_model="gpt-5",
        context_limit=400_000,
        capabilities=frozenset(
            {"tools", "vision", "reasoning", "long_context", "streaming", "json_mode"}
        ),
    ),
    ProviderSpec(
        name="anthropic",
        kind="anthropic",
        label="Anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        model_env="ANTHROPIC_MODEL",
        default_model="claude-sonnet-4-5",
        context_limit=200_000,
        capabilities=frozenset(
            {"tools", "vision", "reasoning", "long_context", "streaming"}
        ),
    ),
    ProviderSpec(
        name="google",
        kind="google",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        default_model="gemini-2.5-pro",
        context_limit=1_000_000,
        capabilities=frozenset(
            {"tools", "vision", "reasoning", "long_context", "streaming", "json_mode"}
        ),
    ),
    ProviderSpec(
        name="local",
        kind="local",
        label="Local inference server",
        base_url="",
        api_key_env="LOCAL_LLM_API_KEY",
        model_env="LOCAL_LLM_MODEL",
        default_model="",
        context_limit=32_000,
        capabilities=frozenset({"streaming"}),
        notes=(
            "Any OpenAI-compatible server the operator runs (vLLM, llama.cpp, "
            "Ollama). Set LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL."
        ),
    ),
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class ProviderRegistry:
    """Resolves which providers are usable and selects one per task."""

    def __init__(self, specs: tuple[ProviderSpec, ...] | None = None) -> None:
        self._specs = specs or _PROVIDERS

    # ------------------------------------------------------------------ #
    def specs(self) -> tuple[ProviderSpec, ...]:
        return self._specs

    def get(self, name: str) -> ProviderSpec:
        for spec in self._specs:
            if spec.name == name:
                return spec
        raise KeyError(f"unknown provider {name!r}")

    def _resolved(self, spec: ProviderSpec) -> ProviderSpec:
        """Apply runtime overrides from the environment (no secret values)."""
        from dataclasses import replace

        base_url = spec.base_url
        default_model = spec.default_model
        if spec.name == "openhands":
            from level5.config import get_settings

            base_url = get_settings().llm_gateway_url
            default_model = get_settings().llm_model
        elif spec.name == "local":
            base_url = _env("LOCAL_LLM_BASE_URL")
        if spec.model_env:
            default_model = _env(spec.model_env, default_model) or default_model
        return replace(spec, base_url=base_url, default_model=default_model)

    def available(self) -> list[ProviderSpec]:
        """Providers usable right now, with runtime overrides applied."""
        return [self._resolved(s) for s in self._specs if self._is_usable(s)]

    def _is_usable(self, spec: ProviderSpec) -> bool:
        resolved = self._resolved(spec)
        if not resolved.base_url:
            return False
        if resolved.managed:
            from level5.config import get_settings

            return bool(get_settings().agent_server_available)
        return bool(_env(spec.api_key_env))

    def describe(self) -> list[dict[str, object]]:
        """Every provider with availability and, when unavailable, the reason.

        Never contains a credential value - only the name of the env var that
        would hold one.
        """
        out: list[dict[str, object]] = []
        for spec in self._specs:
            resolved = self._resolved(spec)
            entry = resolved.as_dict()
            usable = self._is_usable(spec)
            entry["available"] = usable
            if not usable:
                if not resolved.base_url:
                    entry["unavailable_reason"] = (
                        f"no base URL configured (set {spec.api_key_env} and "
                        f"the provider's base URL)"
                    )
                elif not resolved.managed and not _env(spec.api_key_env):
                    entry["unavailable_reason"] = (
                        f"{spec.api_key_env} is not set in the environment"
                    )
                else:
                    entry["unavailable_reason"] = "no credentials available"
            out.append(entry)
        return out

    def select(
        self,
        required: set[str] | None = None,
        *,
        prefer: list[str] | None = None,
    ) -> ProviderSpec:
        """Pick a provider that declares every capability in `required`.

        `prefer` is an ordered preference list. The choice is made from
        declared capabilities and configured credentials only - never from a
        claim that one provider is smarter than another.
        """
        required = required or set()
        candidates = [s for s in self.available() if required <= s.capabilities]
        if not candidates:
            raise LookupError(
                f"no available provider declares capabilities {sorted(required)}"
            )
        if prefer:
            for name in prefer:
                for spec in candidates:
                    if spec.name == name:
                        return spec
        # Prefer a larger context window, then the managed gateway (no extra
        # key to manage), then alphabetical for determinism.
        return sorted(
            candidates,
            key=lambda s: (-s.context_limit, not s.managed, s.name),
        )[0]

    def report(self) -> dict[str, object]:
        """Summary used by the API and by model routing decisions."""
        providers = self.describe()
        usable = [p for p in providers if p["available"]]
        return {
            "providers": providers,
            "available_count": len(usable),
            "total_count": len(providers),
            "capabilities_covered": sorted(
                {c for p in usable for c in p["capabilities"]}  # type: ignore[union-attr]
            ),
            "note": (
                "Capability metadata is descriptive. No provider is ranked as "
                "better than another; route by declared capability and the "
                "credentials the operator has configured."
            ),
        }


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
