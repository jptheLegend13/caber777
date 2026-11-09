"""LEVEL 5 runtime configuration.

Values are read from the environment so the same code runs inside the
OpenHands sandbox (where an Agent Server is already listening) and on a
developer machine that points at a remote Agent Server.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


class Settings:
    """Process-wide configuration for the LEVEL 5 backend."""

    def __init__(self) -> None:
        # OpenHands Agent Server -------------------------------------------------
        self.agent_server_url: str = _env(
            "LEVEL5_AGENT_SERVER_URL",
            _env("OH_INTERNAL_SERVER_URL", "http://127.0.0.1:60000"),
        ).rstrip("/")
        # Session API key used to authenticate against the Agent Server.
        self.session_api_key: str = _session_api_key()
        # Managed LLM key refresh (OpenHands cloud). Empty when unavailable.
        self.llm_refresh_url: str = _env("OH_LLM_API_KEY_REFRESH_URL", "")

        # LLM gateway ------------------------------------------------------------
        # The Agent Server exposes an OpenAI-compatible gateway for its stored
        # LLM profile. That is the sanctioned way to make bare model calls.
        self.llm_gateway_url: str = _env(
            "LEVEL5_LLM_GATEWAY_URL", f"{self.agent_server_url}/v1"
        )
        self.llm_model: str = _env("LEVEL5_LLM_MODEL", "openhands_Default")
        self.llm_timeout: float = float(_env("LEVEL5_LLM_TIMEOUT", "300"))
        self.llm_max_retries: int = int(_env("LEVEL5_LLM_MAX_RETRIES", "3"))
        # Transport for bare (non-agent) model calls:
        #   auto      - try the OpenAI-compatible gateway, fall back to ask_agent
        #   gateway   - OpenAI-compatible gateway only
        #   ask_agent - Agent Server ask_agent API only
        # Deployments with an empty gateway model registry need ask_agent.
        self.llm_transport: str = _env("LEVEL5_LLM_TRANSPORT", "auto")
        self.max_attachment_bytes: int = int(
            _env("LEVEL5_MAX_ATTACHMENT_BYTES", str(25 * 1024 * 1024))
        )

        # Model used by delegated agent conversations (provider/model form) and
        # the proxy those conversations authenticate against.
        self.llm_model_raw: str = _env(
            "LEVEL5_AGENT_LLM_MODEL", "openhands/deepseek-v4.1-flash"
        )
        self.llm_base_url: str = _env(
            "LEVEL5_AGENT_LLM_BASE_URL", "https://llm-proxy.app.all-hands.dev/"
        )

        # Workspaces / storage ---------------------------------------------------
        self.data_dir: Path = Path(_env("LEVEL5_DATA_DIR", str(_default_data_dir())))
        self.projects_dir: Path = self.data_dir / "projects"
        self.db_path: Path = self.data_dir / "level5.db"

        # Execution --------------------------------------------------------------
        # Docker runtime for agent conversations. "local" runs in-process; the
        # Agent Server default is used when unset.
        self.conversation_runtime: str = _env("LEVEL5_CONVERSATION_RUNTIME", "local")
        # Iterations a single agent conversation may take. A task that scaffolds
        # an entire application (frontend, backend, config, docs) needs well
        # over a hundred tool calls; 120 truncated real work mid-task. Raise via
        # LEVEL5_MAX_ITERATIONS. Cost is bounded by LEVEL5_MAX_BUDGET_USD.
        self.default_max_iterations: int = int(
            _env("LEVEL5_MAX_ITERATIONS", "400")
        )
        # Bounded build->repair->rebuild cycles. A failing build is a real
        # defect, so it is repaired, but a project that cannot be fixed must be
        # reported as such rather than looping.
        self.max_build_repairs: int = int(_env("LEVEL5_MAX_BUILD_REPAIRS", "2"))
        self.default_max_budget: float | None = _optional_float(
            _env("LEVEL5_MAX_BUDGET_USD", "")
        )
        # Parallelism for independent task-graph nodes.
        self.max_parallel_tasks: int = int(_env("LEVEL5_MAX_PARALLEL", "3"))

        # Research ---------------------------------------------------------------
        self.research_enabled: bool = _env("LEVEL5_RESEARCH_ENABLED", "1") == "1"
        self.research_max_sources: int = int(_env("LEVEL5_RESEARCH_MAX_SOURCES", "8"))
        self.research_timeout: float = float(_env("LEVEL5_RESEARCH_TIMEOUT", "60"))

        # Server -----------------------------------------------------------------
        self.host: str = _env("LEVEL5_HOST", "0.0.0.0")
        self.port: int = int(_env("LEVEL5_PORT", "8000"))
        self.cors_origins: list[str] = _env(
            "LEVEL5_CORS_ORIGINS", "*"
        ).split(",")

    @property
    def agent_server_available(self) -> bool:
        return bool(self.session_api_key)


def _default_data_dir() -> Path:
    env = os.environ.get("LEVEL5_DATA_DIR")
    if env:
        return Path(env)
    home = Path.home()
    if (home / "workspace").exists():
        return home / "workspace" / "level5-data"
    return Path("./.level5-data").resolve()


def _optional_float(value: str) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _session_api_key() -> str:
    """Resolve the Agent Server session key without logging its value."""
    for name in ("SESSION_API_KEY", "OH_SESSION_API_KEYS_0", "LEVEL5_SESSION_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value.strip()
    key_file = Path.home() / ".oh_session_key"
    if key_file.exists():
        return key_file.read_text().strip()
    return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    return settings
