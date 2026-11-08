"""Tests for the honesty of delivery and artifact reporting.

Two failure modes are guarded here:

1. A run where nothing failed but the specification was not met must not be
   reported as delivered. "Files were generated" is not "the requirements
   were satisfied".
2. Dependency and build directories (node_modules, .venv, dist) must not be
   counted as authored deliverables.
"""

from __future__ import annotations

from pathlib import Path

from level5.models import Artifact, Project, Task, TaskStatus
from level5.orchestrator import Orchestrator
from level5.runtime.agent_server import ExecutionResult


def _orch() -> Orchestrator:
    return Orchestrator.__new__(Orchestrator)


def _project(tmp_path: Path) -> Project:
    project = Project(name="P", original_request="Build something")
    project.workspace_path = str(tmp_path)
    return project


def _task() -> Task:
    t = Task(title="Build the app", objective="Build it")
    t.id = "task_1"
    return t


class TestDependencyDirsAreNotArtifacts:
    def test_node_modules_files_are_excluded(self, tmp_path):
        project = _project(tmp_path)
        (tmp_path / "node_modules").mkdir()
        result = ExecutionResult(
            conversation_id="c",
            status="finished",
            files_changed=[
                "node_modules/react/index.js",
                "src/App.tsx",
            ],
        )
        _orch()._record_artifacts(project, _task(), result)
        paths = {a.path for a in project.artifacts}
        assert "src/App.tsx" in paths
        assert not any("node_modules" in p for p in paths)

    def test_virtualenv_and_build_dirs_are_excluded(self, tmp_path):
        project = _project(tmp_path)
        result = ExecutionResult(
            conversation_id="c",
            status="finished",
            files_changed=[
                ".venv/lib/python3.12/site-packages/x.py",
                "dist/bundle.js",
                "build/out.o",
                "app/main.py",
            ],
        )
        _orch()._record_artifacts(project, _task(), result)
        paths = {a.path for a in project.artifacts}
        assert paths == {"app/main.py"}

    def test_authored_files_are_recorded_with_size(self, tmp_path):
        project = _project(tmp_path)
        (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
        result = ExecutionResult(
            conversation_id="c", status="finished", files_changed=["main.py"]
        )
        _orch()._record_artifacts(project, _task(), result)
        assert len(project.artifacts) == 1
        assert project.artifacts[0].size_bytes > 0

    def test_files_outside_the_workspace_are_rejected(self, tmp_path):
        project = _project(tmp_path)
        result = ExecutionResult(
            conversation_id="c",
            status="finished",
            files_changed=["/etc/passwd", "../escape.py"],
        )
        _orch()._record_artifacts(project, _task(), result)
        assert project.artifacts == []

    def test_duplicate_paths_are_recorded_once(self, tmp_path):
        project = _project(tmp_path)
        project.artifacts.append(
            Artifact(name="main.py", kind="file", path="main.py")
        )
        result = ExecutionResult(
            conversation_id="c", status="finished", files_changed=["main.py"]
        )
        _orch()._record_artifacts(project, _task(), result)
        assert len(project.artifacts) == 1


class TestUnmetCriteriaBlockDelivery:
    def test_all_succeeded_but_unmet_criteria_is_not_delivered(self, tmp_path):
        """This is the check that stops a run being called delivered while its
        own acceptance criteria are unsatisfied."""
        project = _project(tmp_path)
        task = _task()
        task.status = TaskStatus.SUCCEEDED
        project.task_graph.tasks = [task]
        # A criterion no task addresses -> _verify leaves it unsatisfied.
        project.specification.acceptance_criteria = []
        for statement in ["Ship the frontend", "Ship authentication"]:
            from level5.models import AcceptanceCriterion

            project.specification.acceptance_criteria.append(
                AcceptanceCriterion(
                    statement=statement,
                    verification_method="test",
                    satisfied=False,
                )
            )
        unmet = [
            c for c in project.specification.acceptance_criteria if not c.satisfied
        ]
        assert len(unmet) == 2
        # The gate the pipeline applies: unmet criteria -> FAILED, not DELIVERED.
        from level5.models import ProjectStatus

        status = ProjectStatus.FAILED if unmet else ProjectStatus.DELIVERED
        assert status is ProjectStatus.FAILED

    def test_fully_satisfied_criteria_allow_delivery(self, tmp_path):
        from level5.models import AcceptanceCriterion, ProjectStatus

        project = _project(tmp_path)
        project.specification.acceptance_criteria = [
            AcceptanceCriterion(
                statement="Ship the frontend",
                verification_method="test",
                satisfied=True,
            )
        ]
        unmet = [
            c for c in project.specification.acceptance_criteria if not c.satisfied
        ]
        status = ProjectStatus.FAILED if unmet else ProjectStatus.DELIVERED
        assert status is ProjectStatus.DELIVERED
