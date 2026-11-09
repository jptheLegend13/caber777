"""Tests for the self-benchmarking summary."""

from __future__ import annotations

from level5.benchmarks import summarise
from level5.models import (
    AcceptanceCriterion,
    Artifact,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TestResult,
)


def _project() -> Project:
    project = Project(name="bench", original_request="x")
    project.status = ProjectStatus.DELIVERED
    a = Task(title="A")
    b = Task(title="B")
    c = Task(title="C")
    a.status = TaskStatus.SUCCEEDED
    b.status = TaskStatus.SUCCEEDED
    c.status = TaskStatus.FAILED
    project.task_graph.tasks = [a, b, c]
    project.tests = [
        TestResult(suite="s", name="t1", status="passed"),
        TestResult(suite="s", name="t2", status="failed"),
    ]
    project.specification.acceptance_criteria = [
        AcceptanceCriterion(statement="one", satisfied=True),
        AcceptanceCriterion(statement="two", satisfied=False),
    ]
    project.artifacts = [Artifact(name="f", kind="file", path="f")]
    project.conversation_ids = ["c1", "c2"]
    return project


def test_summarise_counts_and_rates():
    summary = summarise(_project())
    assert summary["tasks_total"] == 3
    assert summary["tasks_succeeded"] == 2
    assert summary["tasks_failed"] == 1
    assert summary["task_success_rate"] == round(2 / 3, 4)
    assert summary["tests_total"] == 2
    assert summary["test_pass_rate"] == 0.5
    assert summary["criteria_rate"] == 0.5
    assert summary["artifacts"] == 1
    assert summary["agent_conversations"] == 2
    assert summary["duration_seconds"] >= 0


def test_summarise_handles_empty_project():
    summary = summarise(Project(name="empty", original_request="x"))
    assert summary["tasks_total"] == 0
    assert summary["task_success_rate"] is None
    assert summary["test_pass_rate"] is None
    assert summary["criteria_rate"] is None


def test_summarise_reports_model_and_module():
    summary = summarise(_project())
    assert "model" in summary
    assert summary["caber_module"] in ("A", "B", "C", "P")
