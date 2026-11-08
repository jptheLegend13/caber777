"""Tests for the build -> repair -> rebuild cycle.

A generated frontend that does not compile is a real defect. Level 5 must not
report it as delivered, and it must attempt a bounded repair rather than either
ignoring the failure or looping forever.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from level5.models import Project, ProjectStatus, Task, TaskStatus
from level5.orchestrator import Orchestrator
from level5.preview import BuildResult


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run_to_completion(self, *, working_dir, task_prompt, tools, system_prompt, max_iterations, timeout):
        from level5.runtime.agent_server import ExecutionResult

        self.calls.append({"prompt": task_prompt})
        return ExecutionResult(
            conversation_id="conv_repair",
            status="finished",
            iterations=5,
            final_message="Fixed the type errors and the build passes.",
            files_changed=[],
            commands_run=["npm run build"],
        )


def _project(tmp_path: Path) -> Project:
    project = Project(name="app", original_request="build an app")
    project.workspace_path = str(tmp_path)
    # A build script must exist for the build step to be attempted at all.
    (tmp_path / "package.json").write_text(
        '{"name": "app", "scripts": {"build": "vite build"}}', encoding="utf-8"
    )
    return project


@pytest.fixture
def patch_build(monkeypatch):
    """Replace only the process boundary; the orchestrator logic runs for real."""
    outcomes: list[BuildResult] = []

    def fake(workspace, *, timeout=900.0):
        return outcomes.pop(0)

    monkeypatch.setattr("level5.preview.build_web_app", fake)
    return outcomes


async def test_failing_build_dispatches_a_repair_and_rebuilds(tmp_path, patch_build):
    project = _project(tmp_path)
    patch_build.append(
        BuildResult(
            attempted=True,
            succeeded=False,
            package_dir=str(tmp_path),
            command="npm run build",
            output="error TS2345: type mismatch",
        )
    )
    patch_build.append(
        BuildResult(
            attempted=True,
            succeeded=True,
            package_dir=str(tmp_path),
            command="npm run build",
            dist_dir=str(tmp_path / "dist"),
        )
    )
    agent = _FakeAgent()
    await Orchestrator(agent_client=agent)._build_deliverable(project)

    repair_tasks = [t for t in project.task_graph.tasks if t.phase == "repair"]
    assert len(repair_tasks) == 1
    assert repair_tasks[0].agent_role == "debugging_engineer"
    assert repair_tasks[0].status == TaskStatus.SUCCEEDED
    # The compiler output was handed to the repair agent.
    assert "TS2345" in agent.calls[0]["prompt"]

    build_tests = [t for t in project.tests if t.suite == "build"]
    assert [t.status for t in build_tests] == ["failed", "passed"]


async def test_build_failure_is_reported_when_repairs_are_exhausted(tmp_path, patch_build):
    project = _project(tmp_path)
    for _ in range(10):
        patch_build.append(
            BuildResult(
                attempted=True,
                succeeded=False,
                package_dir=str(tmp_path),
                command="npm run build",
                output="error TS1005: still broken",
            )
        )
    agent = _FakeAgent()
    await Orchestrator(agent_client=agent)._build_deliverable(project)

    # max_build_repairs defaults to 2, so two repair rounds then stop.
    repair_tasks = [t for t in project.task_graph.tasks if t.phase == "repair"]
    assert len(repair_tasks) == 2
    assert len(agent.calls) == 2
    assert all(t.status == TaskStatus.FAILED for t in repair_tasks)
    # The failure is stated plainly, not hidden.
    assert any(
        e.kind == "build" and "does not build" in e.message for e in project.events
    )


async def test_successful_build_needs_no_repair(tmp_path, patch_build):
    project = _project(tmp_path)
    patch_build.append(
        BuildResult(
            attempted=True,
            succeeded=True,
            package_dir=str(tmp_path),
            command="npm run build",
            dist_dir=str(tmp_path / "dist"),
        )
    )
    agent = _FakeAgent()
    await Orchestrator(agent_client=agent)._build_deliverable(project)

    assert not [t for t in project.task_graph.tasks if t.phase == "repair"]
    assert agent.calls == []
    assert [t.status for t in project.tests if t.suite == "build"] == ["passed"]


async def test_no_build_script_means_no_build_step(tmp_path, patch_build):
    project = _project(tmp_path)
    patch_build.append(BuildResult(attempted=False, output="no web app found"))
    agent = _FakeAgent()
    await Orchestrator(agent_client=agent)._build_deliverable(project)

    assert agent.calls == []
    assert [t for t in project.tests if t.suite == "build"] == []
