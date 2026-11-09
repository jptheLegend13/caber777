"""Sandboxed Python execution for generated models and prototypes.

One execution path is shared by the problem-solving intelligence and the
innovation-to-prototype engine so both are tested by the same code. A generated
script runs in a dedicated subdirectory with a minimal environment and a hard
timeout; its stdout, stderr and exit code are captured verbatim.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SAFE_ENV = {"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"}


@dataclass
class ComputationResult:
    """Outcome of running a generated script."""

    script: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    duration_s: float = 0.0
    parsed: dict[str, Any] | None = None
    files: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def parse_json_block(text: str) -> dict[str, Any] | None:
    """Return the first JSON object embedded in ``text``, or ``None``."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def run_python_script(
    script: str,
    workspace: Path,
    *,
    timeout: float = 120.0,
    subdir: str = "models",
    filename: str = "model.py",
) -> ComputationResult:
    """Execute ``script`` in an isolated subdirectory and capture its result.

    The script is written under ``workspace/subdir`` and run there with a
    minimal environment and a hard timeout. ``result.files`` lists the script
    itself plus any files the run created (relative paths), so a caller can
    surface real artifacts.
    """
    models_dir = workspace / subdir
    models_dir.mkdir(parents=True, exist_ok=True)
    script_path = models_dir / filename
    script_path.write_text(script, encoding="utf-8")

    before = _snapshot(models_dir)
    loop = asyncio.get_event_loop()
    start = loop.time()
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        cwd=str(models_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_SAFE_ENV,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        stdout, stderr = await proc.communicate()
    duration = loop.time() - start
    out_text = stdout.decode("utf-8", "replace")
    err_text = stderr.decode("utf-8", "replace")
    created = sorted(str(p.relative_to(models_dir)) for p in _snapshot(models_dir) - before)
    files = [filename, *created]
    return ComputationResult(
        script=script,
        stdout=out_text,
        stderr=err_text,
        exit_code=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        duration_s=round(duration, 3),
        parsed=parse_json_block(out_text),
        files=files,
    )


def _snapshot(directory: Path) -> set[Path]:
    try:
        return {p for p in directory.rglob("*") if p.is_file()}
    except OSError:  # pragma: no cover - best effort
        return set()
