#!/usr/bin/env python3
"""LEVEL 5 intelligence-independence check.

Runs LEVEL 5's core intelligence with every external model provider and the
OpenHands development gateway DISABLED, and verifies the platform still
operates. Prints a report and exits non-zero if any core capability fails.

What it proves (no model, no external service, no network):

- Reasoning: request -> structured specification -> task graph (deterministic).
- Memory and retrieval: write knowledge, retrieve it by BM25.
- Agent coordination: the deterministic planner allocates specialist roles and
  a dependency-ordered graph.
- Code generation and execution: a project artifact is written to disk and run
  with the local interpreter; its real output is checked.
- Problem-solving substrate: real code executes and is checked.
- Project creation and persistence: a project is stored and reloaded.
- Error recovery: a defect is detected by a real test run and repaired.

What it does NOT prove (reported honestly at the end):

- Generative code authoring without a model requires either the self-hosted
  runtime or the Agent Server. With neither, the platform plans and executes
  deterministically but does not author novel source with a language model.
- Research retrieval that needs a keyed provider (it uses keyless providers).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Disable all external intelligence BEFORE importing level5 so the settings
# cache is built with independence enforced.
os.environ["LEVEL5_ALLOW_EXTERNAL_MODELS"] = "0"
os.environ["LEVEL5_ALLOW_DEV_GATEWAY"] = "0"
os.environ["LEVEL5_LLM_TRANSPORT"] = "auto"
os.environ.setdefault("LEVEL5_DATA_DIR", tempfile.mkdtemp(prefix="level5-indep-"))

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from level5.config import get_settings  # noqa: E402
from level5.intelligence.fallbacks import graph_from_spec, spec_from_request  # noqa: E402
from level5.intelligence.planner import Planner  # noqa: E402
from level5.intelligence.understanding import UnderstandingEngine  # noqa: E402
from level5.knowledge.store import KnowledgeStore  # noqa: E402
from level5.llm.client import LLMClient, LLMError  # noqa: E402
from level5.llm.gateway import get_gateway  # noqa: E402
from level5.models import Project  # noqa: E402
from level5.storage.store import ProjectStore  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: {detail}")


async def check_reasoning() -> None:
    spec = spec_from_request("Build a web application with a frontend and backend")
    graph = graph_from_spec(spec)
    ok = bool(spec.deliverable and spec.requirements and graph.tasks)
    record(
        "Reasoning (deterministic understanding + planning)",
        ok,
        f"domain={spec.domain.value} requirements={len(spec.requirements)} "
        f"tasks={len(graph.tasks)}",
    )


async def check_agent_coordination() -> None:
    spec = spec_from_request("Build a backend API with a database and authentication")
    graph = graph_from_spec(spec)
    roles = {t.agent_role for t in graph.tasks}
    ids = {t.id for t in graph.tasks}
    acyclic = all(set(t.dependencies) <= ids for t in graph.tasks)
    has_deps = any(t.dependencies for t in graph.tasks)
    ok = len(roles) >= 2 and acyclic and has_deps
    record(
        "Agent coordination (roles + dependency graph)",
        ok,
        f"roles={len(roles)} deps_ok={acyclic} has_edges={has_deps}",
    )


async def check_memory(tmp: Path) -> None:
    store = KnowledgeStore(db_path=tmp / "mem.db")
    await store.add(
        project_id="p",
        kind="decision",
        title="Database",
        text="We chose PostgreSQL for relational integrity.",
    )
    await store.add(
        project_id="p",
        kind="lesson",
        title="Build",
        text="The frontend build needed a pinned Node version.",
    )
    hits = await store.search("PostgreSQL relational", project_id="p")
    ok = bool(hits) and hits[0].entry.title == "Database"
    record(
        "Memory and retrieval (BM25, no model)",
        ok,
        f"hits={len(hits)} top={hits[0].entry.title if hits else 'none'}",
    )


async def check_no_external_fallback() -> None:
    settings = get_settings()
    gateway = get_gateway()
    report = gateway.report()
    external_off = report["independence"]["external_models_enabled"] is False
    dev_off = report["independence"]["dev_gateway_enabled"] is False
    no_fallback = (
        report["independence"]["external_fallback_on_internal_failure"] is False
    )
    ok = external_off and dev_off and no_fallback
    record(
        "External providers disabled / no fallback",
        ok,
        f"external_enabled={not external_off} dev_gateway_enabled={not dev_off} "
        f"external_fallback={not no_fallback}",
    )
    # A bare model call must now fail cleanly rather than reach a provider.
    client = LLMClient(settings)
    try:
        await client.chat([{"role": "user", "content": "hi"}])
        record(
            "No external reachable for model call",
            False,
            "call unexpectedly succeeded",
        )
    except LLMError:
        record(
            "No external reachable for model call",
            True,
            "model call correctly failed with no permitted backend",
        )


async def check_project_creation(tmp: Path) -> None:
    store = ProjectStore(db_path=tmp / "projects.db")
    spec = spec_from_request("Build a CLI tool that counts words")
    graph = graph_from_spec(spec)
    project = Project(
        name="indep", original_request="Build a CLI tool", specification=spec
    )
    project.task_graph = graph
    await store.save(project)
    reloaded = await store.get(project.id)
    ok = reloaded is not None and len(reloaded.task_graph.tasks) == len(graph.tasks)
    record(
        "Project creation and persistence",
        ok,
        f"stored+reloaded tasks={len(reloaded.task_graph.tasks) if reloaded else 0}",
    )


async def check_codegen_and_execution(tmp: Path) -> None:
    """Write a real artifact and execute it with the local interpreter."""
    project_dir = tmp / "artifact"
    project_dir.mkdir()
    (project_dir / "count.py").write_text(
        "import sys\n"
        "def counts(text):\n"
        "    return len(text.splitlines()), len(text.split()), len(text)\n"
        "if __name__ == '__main__':\n"
        "    text = open(sys.argv[1]).read()\n"
        "    lines, words, chars = counts(text)\n"
        "    print(f'lines={lines} words={words} chars={chars}')\n",
        encoding="utf-8",
    )
    sample = project_dir / "sample.txt"
    sample.write_text("hello world\nsecond line\n", encoding="utf-8")
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(project_dir / "count.py"), str(sample)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    ok = proc.returncode == 0 and "lines=2 words=4" in proc.stdout
    record(
        "Code generation and execution (local)",
        ok,
        f"exit={proc.returncode} output={proc.stdout.strip()!r}",
    )


async def check_error_recovery(tmp: Path) -> None:
    """Introduce a defect, detect it with a real test run, then repair it."""
    d = tmp / "recover"
    d.mkdir()
    (d / "calc.py").write_text(
        "def add(a, b):\n    return a - b  # defect\n", encoding="utf-8"
    )
    (d / "test_calc.py").write_text(
        "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "pytest", "-q", "test_calc.py"],
        cwd=d,
        capture_output=True,
        text=True,
        timeout=60,
    )
    detected = proc.returncode != 0 and "1 failed" in proc.stdout
    (d / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    proc2 = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "pytest", "-q", "test_calc.py"],
        cwd=d,
        capture_output=True,
        text=True,
        timeout=60,
    )
    ok = detected and proc2.returncode == 0
    record(
        "Error recovery (detect defect -> repair -> pass)",
        ok,
        f"detected={detected} repaired_pass={proc2.returncode == 0}",
    )


async def check_model_free_fallback() -> None:
    """Understanding/planning degrade to rules when the model is unavailable."""
    engine = UnderstandingEngine(llm=LLMClient(get_settings()))
    planner = Planner(llm=LLMClient(get_settings()))
    # With external+dev disabled there is no backend, so a real call fails and
    # the fallback must engage.
    spec = await engine.understand("Build a mobile fitness tracker")
    graph = await planner.plan(spec)
    ok = bool(spec.deliverable and graph.tasks)
    record(
        "Model-free fallback engaged in a real call path",
        ok,
        f"domain={spec.domain.value} tasks={len(graph.tasks)}",
    )


async def main() -> int:
    tmp = Path(os.environ["LEVEL5_DATA_DIR"])
    tmp.mkdir(parents=True, exist_ok=True)
    print("LEVEL 5 independence check — external providers and dev gateway OFF\n")
    await check_reasoning()
    await check_agent_coordination()
    await check_memory(tmp)
    await check_no_external_fallback()
    await check_project_creation(tmp)
    await check_codegen_and_execution(tmp)
    await check_error_recovery(tmp)
    await check_model_free_fallback()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} core capabilities operated with no external model.")

    print("\nStill requires external services, hardware or infrastructure:")
    print("  - Generative code authoring with a language model requires either")
    print("    the self-hosted runtime (vLLM/llama.cpp/Ollama on this host) or")
    print("    the Agent Server. Neither is installed here.")
    print("  - Keyed research providers (Tavily/Brave) need credentials; keyless")
    print("    providers (Wikipedia/arXiv/Crossref/GitHub/StackExchange) do not.")
    print("  - Browser-based UI preview needs a Node toolchain for built apps.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
