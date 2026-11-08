"""Tests for verification honesty.

The directive forbids declaring a feature complete merely because files were
generated. These tests pin the rule that an acceptance criterion is satisfied
only when a succeeded task actually addresses it.
"""

from __future__ import annotations

from level5.models import (
    AcceptanceCriterion,
    Project,
    Task,
    TaskStatus,
)
from level5.orchestrator import Orchestrator


def _orchestrator() -> Orchestrator:
    return Orchestrator.__new__(Orchestrator)


def _task(title: str, objective: str = "", criteria: list[str] | None = None) -> Task:
    task = Task(title=title, objective=objective)
    task.acceptance_criteria = criteria or []
    task.status = TaskStatus.SUCCEEDED
    return task


class TestMatchingTask:
    def test_matches_task_whose_criteria_address_the_statement(self):
        orch = _orchestrator()
        tasks = [
            _task(
                "Authentication, JWT tokens and RBAC enforcement",
                "Implement authentication and role-based access control.",
                ["Users can register and log in with JWT tokens"],
            ),
            _task("Analytics dashboard", "Build the analytics dashboard."),
        ]
        owner = orch._matching_task(
            "Users can authenticate and receive a JWT token", tasks
        )
        assert owner is not None
        assert "Authentication" in owner.title

    def test_returns_none_when_no_task_addresses_the_criterion(self):
        orch = _orchestrator()
        tasks = [_task("Analytics dashboard", "Build the analytics dashboard.")]
        owner = orch._matching_task(
            "The system enforces payment settlement reconciliation", tasks
        )
        assert owner is None

    def test_returns_none_for_empty_candidate_list(self):
        orch = _orchestrator()
        assert orch._matching_task("Anything at all", []) is None

    def test_stopwords_do_not_create_false_matches(self):
        orch = _orchestrator()
        tasks = [_task("Build the thing", "with the user and their data")]
        owner = orch._matching_task("with that this from have", tasks)
        assert owner is None

    def test_picks_the_best_overlapping_task(self):
        orch = _orchestrator()
        tasks = [
            _task("Database schema", "Design the database schema and migrations."),
            _task(
                "Database schema, ORM models and migrations",
                "Design the database schema, ORM models and Alembic migrations.",
                ["The schema covers users, tasks and audit events"],
            ),
        ]
        owner = orch._matching_task(
            "A database schema with ORM models and migrations covers all entities",
            tasks,
        )
        assert owner is not None
        assert owner.title.startswith("Database schema, ORM models")


class TestVerificationHonesty:
    async def test_unaddressed_criterion_is_not_marked_satisfied(self):
        project = Project(name="p", original_request="x")
        project.specification.acceptance_criteria = [
            AcceptanceCriterion(statement="Users can authenticate with JWT tokens"),
            AcceptanceCriterion(
                statement="Payments settle through the reconciliation ledger"
            ),
        ]
        project.task_graph.tasks = [
            _task(
                "Authentication, JWT tokens and RBAC",
                "Implement authentication with JWT tokens.",
                ["Users authenticate and receive a JWT"],
            )
        ]
        orch = _orchestrator()
        # _verify only emits; stub the emitter to keep the test focused.
        orch._emit = _noop_emit  # type: ignore[method-assign]
        await orch._verify(project)

        criteria = project.specification.acceptance_criteria
        assert criteria[0].satisfied is True
        assert criteria[0].evidence
        assert criteria[1].satisfied is False
        assert "no task produced evidence" in criteria[1].evidence

    async def test_no_succeeded_tasks_means_no_satisfied_criteria(self):
        project = Project(name="p", original_request="x")
        project.specification.acceptance_criteria = [
            AcceptanceCriterion(statement="The application is deployable")
        ]
        failed = _task("Deployment configuration", "Write deployment config.")
        failed.status = TaskStatus.FAILED
        project.task_graph.tasks = [failed]
        orch = _orchestrator()
        orch._emit = _noop_emit  # type: ignore[method-assign]
        await orch._verify(project)
        assert project.specification.acceptance_criteria[0].satisfied is False


async def _noop_emit(*args, **kwargs) -> None:  # pragma: no cover - test helper
    return None
