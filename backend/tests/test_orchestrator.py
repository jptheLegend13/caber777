"""Tests for orchestrator scheduling logic and problem-solver execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from level5.models import Project, ProjectStatus, Task, TaskStatus
from level5.orchestrator import Orchestrator, _derive_name


class _FakeAgent:
    """A stand-in that records calls and creates a real file in the workspace.

    It replaces only the network boundary (the Agent Server conversation); the
    orchestrator's scheduling, evidence recording and reporting run for real.
    """

    def __init__(self, *, fail_tasks: set[str] | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_tasks = fail_tasks or set()
        self.counter = 0

    async def run_to_completion(self, *, working_dir, task_prompt, tools, system_prompt, max_iterations, timeout):
        from level5.runtime.agent_server import ExecutionResult

        self.counter += 1
        self.calls.append({"dir": working_dir, "prompt": task_prompt, "tools": tools})
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        name = f"artifact_{self.counter}.txt"
        Path(working_dir, name).write_text("real output", encoding="utf-8")
        if any(marker in task_prompt for marker in self.fail_tasks):
            return ExecutionResult(
                conversation_id=f"conv_{self.counter}",
                status="error",
                error="simulated failure",
            )
        return ExecutionResult(
            conversation_id=f"conv_{self.counter}",
            status="finished",
            iterations=3,
            final_message="Created the artifact and ran its test.",
            files_changed=[name],
            commands_run=["pytest -q"],
        )


def _project(tmp_path, tasks: list[Task]) -> Project:
    project = Project(name="orch-test", original_request="test")
    project.workspace_path = str(tmp_path / "ws")
    project.task_graph.tasks = tasks
    return project


async def test_execute_runs_all_tasks_and_delivers(tmp_path):
    a = Task(title="A", agent_role="backend_engineer")
    b = Task(title="B", agent_role="testing_engineer", dependencies=[a.id])
    project = _project(tmp_path, [a, b])
    agent = _FakeAgent()
    orch = Orchestrator(agent_client=agent)

    await orch.execute(project)

    assert project.status == ProjectStatus.DELIVERED
    assert a.status == TaskStatus.SUCCEEDED
    assert b.status == TaskStatus.SUCCEEDED
    assert len(agent.calls) == 2
    assert len(project.artifacts) >= 3  # two task files + the report
    assert (Path(project.workspace_path) / "LEVEL5_REPORT.md").exists()


async def test_dependency_order_is_respected(tmp_path):
    a = Task(title="First", agent_role="backend_engineer")
    b = Task(title="Second", agent_role="testing_engineer", dependencies=[a.id])
    project = _project(tmp_path, [a, b])
    agent = _FakeAgent()
    await Orchestrator(agent_client=agent).execute(project)

    first_prompt = agent.calls[0]["prompt"]
    second_prompt = agent.calls[1]["prompt"]
    assert "First" in first_prompt
    assert "ALREADY COMPLETED" in second_prompt
    assert "First" in second_prompt


async def test_failed_task_skips_dependents(tmp_path):
    a = Task(title="WillFail", agent_role="backend_engineer")
    b = Task(title="DependsOnFail", agent_role="testing_engineer", dependencies=[a.id])
    project = _project(tmp_path, [a, b])
    agent = _FakeAgent(fail_tasks={"WillFail"})
    await Orchestrator(agent_client=agent).execute(project)

    assert a.status == TaskStatus.FAILED
    assert b.status == TaskStatus.SKIPPED
    assert project.status == ProjectStatus.FAILED


async def test_failed_task_records_error(tmp_path):
    a = Task(title="WillFail", agent_role="backend_engineer")
    project = _project(tmp_path, [a])
    agent = _FakeAgent(fail_tasks={"WillFail"})
    await Orchestrator(agent_client=agent).execute(project)
    assert a.error == "simulated failure"
    assert any(e.kind == "task_failed" for e in project.events)


async def test_verification_marks_criteria(tmp_path):
    a = Task(title="Build it", agent_role="backend_engineer",
             acceptance_criteria=["The app runs"])
    project = _project(tmp_path, [a])
    project.specification.acceptance_criteria = [
        __import__("level5.models", fromlist=["AcceptanceCriterion"]).AcceptanceCriterion(
            statement="The app runs"
        )
    ]
    await Orchestrator(agent_client=_FakeAgent()).execute(project)
    assert project.specification.acceptance_criteria[0].satisfied is True


def test_derive_name_uses_first_line():
    assert _derive_name("Build a CRM\nwith more detail") == "Build a CRM"


class TestProblemSolverExecution:
    """The model runner executes real Python and captures real output."""

    async def test_runs_a_real_script_and_parses_json(self, tmp_path):
        from level5.intelligence.problem_solving import ProblemSolver

        solver = ProblemSolver.__new__(ProblemSolver)  # skip LLM wiring
        solver.timeout = 30.0
        script = (
            "import json\n"
            "result = {'sum': sum(range(101)), 'checked': True}\n"
            "print(json.dumps(result))\n"
        )
        result = await solver._run_model(script, tmp_path)
        assert result.succeeded, result.stderr
        assert result.parsed == {"sum": 5050, "checked": True}
        assert (tmp_path / "models" / "model.py").exists()

    async def test_reports_failure_with_real_stderr(self, tmp_path):
        from level5.intelligence.problem_solving import ProblemSolver

        solver = ProblemSolver.__new__(ProblemSolver)
        solver.timeout = 30.0
        result = await solver._run_model("raise ValueError('boom')\n", tmp_path)
        assert result.succeeded is False
        assert "boom" in result.stderr

    async def test_timeout_is_enforced(self, tmp_path):
        from level5.intelligence.problem_solving import ProblemSolver

        solver = ProblemSolver.__new__(ProblemSolver)
        solver.timeout = 2.0
        result = await solver._run_model("import time\ntime.sleep(30)\n", tmp_path)
        assert result.timed_out is True
        assert result.succeeded is False
