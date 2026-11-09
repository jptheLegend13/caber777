"""Self-hosted inference runtime control for LEVEL 5.

LEVEL 5's production target is an inference runtime that the operator controls:
an OpenAI-compatible server (vLLM, llama.cpp's ``llama-server``, Ollama, TGI,
or any equivalent) running an open-weight model on hardware we own. This module
owns that runtime's lifecycle from LEVEL 5's side:

- discover which runtime binaries are actually installed on this host,
- start / stop / health-check the runtime as a managed process,
- load, version and select models from a local model registry,
- report the runtime's real state so the rest of the platform never assumes
  inference is available when it is not.

Nothing here downloads a model or spends money on its own. Starting a runtime
requires a model that is already present on disk; when it is not, the call
reports exactly what is missing instead of pretending.

This module never talks to an external model provider. It only manages a local
process listening on a local port.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from level5.config import Settings, get_settings

logger = logging.getLogger("level5.runtime.local")


class RuntimeError_(RuntimeError):
    """A self-hosted runtime operation failed."""


# Runtimes we know how to launch. Each entry maps a discovered executable to
# the command shape that serves an OpenAI-compatible API. ``{model}``,
# ``{port}`` and ``{ctx}`` are substituted at launch.
_RUNTIME_COMMANDS: dict[str, list[str]] = {
    "llama-server": ["llama-server", "-m", "{model}", "--port", "{port}", "-c", "{ctx}"],
    "vllm": [
        "python",
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        "{model}",
        "--port",
        "{port}",
    ],
    "ollama": ["ollama", "serve"],
}


@dataclass
class LocalModel:
    """A model file present on this host, with the metadata we can prove."""

    name: str
    path: str
    size_bytes: int
    format: str  # gguf | safetensors | ollama | unknown
    version: str = ""
    # Rights/consent provenance is operator-supplied metadata, never inferred.
    license: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "format": self.format,
            "version": self.version,
            "license": self.license,
            "source": self.source,
        }


@dataclass
class RuntimeState:
    """Observed state of the self-hosted runtime."""

    running: bool
    url: str = ""
    engine: str = ""
    model: str = ""
    detail: str = ""
    pid: int | None = None
    started_at: float | None = None


@dataclass
class ModelRegistry:
    """Local model registry backed by a JSON file on disk.

    The registry records where each model file is and the operator's declared
    provenance for it. It does not infer a licence and does not download
    anything.
    """

    path: Path
    models: dict[str, LocalModel] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "ModelRegistry":
        registry = cls(path=path)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return registry
            for name, entry in (raw.get("models") or {}).items():
                if not isinstance(entry, dict):
                    continue
                registry.models[name] = LocalModel(
                    name=name,
                    path=str(entry.get("path", "")),
                    size_bytes=int(entry.get("size_bytes", 0)),
                    format=str(entry.get("format", "unknown")),
                    version=str(entry.get("version", "")),
                    license=str(entry.get("license", "")),
                    source=str(entry.get("source", "")),
                )
        return registry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"models": {n: m.as_dict() for n, m in self.models.items()}}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register(self, model: LocalModel) -> None:
        self.models[model.name] = model
        self.save()

    def get(self, name: str) -> LocalModel | None:
        return self.models.get(name)

    def present(self) -> list[LocalModel]:
        """Registered models whose file actually exists on disk."""
        return [m for m in self.models.values() if m.path and Path(m.path).exists()]


def _detect_engine() -> tuple[str, str] | None:
    """Return ``(engine, executable)`` for the first installed runtime, or None."""
    for engine, argv in _RUNTIME_COMMANDS.items():
        exe = argv[0]
        if engine == "vllm":
            # vLLM is launched as a module, so the interpreter must import it.
            if shutil.which("python") and _module_available("vllm"):
                return engine, "python"
            continue
        found = shutil.which(exe)
        if found:
            return engine, found
    return None


def _module_available(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class LocalInferenceRuntime:
    """Manages a self-hosted OpenAI-compatible inference server."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._process: subprocess.Popen[bytes] | None = None
        self._state = RuntimeState(running=False)
        self.registry = ModelRegistry.load(self.settings.local_models_file)

    # -- discovery ------------------------------------------------------- #
    def engine_available(self) -> tuple[str, str] | None:
        return _detect_engine()

    def status(self) -> dict[str, Any]:
        """Report the runtime's real state plus what this host can support."""
        detected = self.engine_available()
        models = self.registry.present()
        healthy = self._probe_health()
        return {
            "engine": detected[0] if detected else "",
            "engine_installed": detected is not None,
            "managed_process_running": self._process is not None
            and self._process.poll() is None,
            "serving": healthy,
            "url": self.settings.local_llm_base_url,
            "models_registered": len(self.registry.models),
            "models_present": [m.as_dict() for m in models],
            "configured_model": self.settings.local_llm_model,
            "note": (
                "A self-hosted runtime is required for inference without an "
                "external provider. Install llama.cpp, vLLM or Ollama and "
                "register a model file to enable it."
                if detected is None
                else "Runtime binary detected; register a model and start it."
            ),
        }

    def _probe_health(self) -> bool:
        """True when an OpenAI-compatible server answers on the local URL."""
        if not self.settings.local_llm_base_url:
            return False
        try:
            response = httpx.get(
                f"{self.settings.local_llm_base_url}/models", timeout=3.0
            )
            return response.status_code < 400
        except Exception:  # noqa: BLE001 - health must never raise
            return False

    # -- lifecycle ------------------------------------------------------- #
    def start(self, model_name: str | None = None) -> RuntimeState:
        """Start the managed runtime serving a registered model.

        Raises :class:`RuntimeError_` with a precise reason when the runtime
        cannot be started (no engine, no model file, already serving).
        """
        if self._probe_health():
            self._state = RuntimeState(
                running=True,
                url=self.settings.local_llm_base_url,
                engine=(self.engine_available() or ("external", ""))[0],
                model=self.settings.local_llm_model,
                detail="a server is already answering on the configured URL",
            )
            return self._state

        detected = self.engine_available()
        if detected is None:
            raise RuntimeError_(
                "no self-hosted inference engine is installed; install "
                "llama.cpp (llama-server), vLLM or Ollama"
            )
        engine, exe = detected

        name = model_name or self.settings.local_llm_model
        model = self.registry.get(name) if name else None
        if model is None or not Path(model.path).exists():
            raise RuntimeError_(
                f"model {name!r} is not registered or its file is missing; "
                f"register it with the model registry first"
            )

        argv = [
            part.format(
                model=model.path,
                port=self.settings.local_llm_port,
                ctx=self.settings.local_llm_context,
            )
            for part in _RUNTIME_COMMANDS[engine]
        ]
        if argv[0] == "python":
            argv[0] = exe
        logger.info("starting %s runtime for model %s", engine, name)
        self._process = subprocess.Popen(  # noqa: S603 - argv is constructed above
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + self.settings.local_llm_start_timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError_(
                    f"{engine} exited during startup with code "
                    f"{self._process.returncode}"
                )
            if self._probe_health():
                self._state = RuntimeState(
                    running=True,
                    url=self.settings.local_llm_base_url,
                    engine=engine,
                    model=name,
                    pid=self._process.pid,
                    started_at=time.time(),
                    detail="started by LEVEL 5",
                )
                return self._state
            time.sleep(1.0)
        self.stop()
        raise RuntimeError_(
            f"{engine} did not become healthy within "
            f"{self.settings.local_llm_start_timeout:.0f}s"
        )

    def stop(self) -> RuntimeState:
        """Stop the managed runtime process if LEVEL 5 started one."""
        if self._process is not None and self._process.poll() is None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                self._process.wait(timeout=10)
            except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
                try:
                    self._process.kill()
                except Exception:  # noqa: BLE001 - best effort
                    pass
        self._process = None
        self._state = RuntimeState(running=False, detail="stopped")
        return self._state

    @property
    def state(self) -> RuntimeState:
        return self._state


_runtime: LocalInferenceRuntime | None = None


def get_local_runtime() -> LocalInferenceRuntime:
    global _runtime
    if _runtime is None:
        _runtime = LocalInferenceRuntime()
    return _runtime
