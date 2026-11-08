"""Tests for resuming a run without losing completed work.

Section 15 requires unfinished work to resume after a restart. The failure this
guards against is silent: re-planning on resume replaces the task graph and
discards every recorded result, so the run appears to continue but has started
over from scratch.
"""

from __future__ import annotations

from level5.models import Project, ProjectStatus, Task, TaskStatus
from level5.orchestrator import Orchestrator


def _orch() -> Orchestrator:
    return Orchestrator.__new__(Orchestrator)


def _task(title: str, status: TaskStatus, *, attempts: int = 0, max_attempts: int = 2) -> Task:
    t = Task(title=title, objective=title)
    t.status = status
    t.attempts = attempts
    t.max_attempts = max_attempts
    t.error = "previous error" if status == TaskStatus.FAILED else None
    return t


def _project(tasks: list[Task]) -> Project:
    project = Project(name="P", original_request="Build something")
    project.task_graph.tasks = tasks
    return project


class TestPrepareResume:
    def test_succeeded_tasks_are_kept(self):
        done = _task("done", TaskStatus.SUCCEEDED)
        project = _project([done])
        _orch().prepare_resume(project)
        assert done.status is TaskStatus.SUCCEEDED

    def test_task_caught_running_is_retried(self):
        running = _task("mid-flight", TaskStatus.RUNNING)
        project = _project([running])
        _orch().prepare_resume(project)
        assert running.status is TaskStatus.PENDING

    def test_skipped_tasks_are_reset_so_they_can_unblock(self):
        skipped = _task("blocked downstream", TaskStatus.SKIPPED)
        project = _project([skipped])
        _orch().prepare_resume(project)
        assert skipped.status is TaskStatus.PENDING

    def test_failed_task_with_budget_left_is_retried(self):
        failed = _task("flaky", TaskStatus.FAILED, attempts=1, max_attempts=2)
        project = _project([failed])
        _orch().prepare_resume(project)
        assert failed.status is TaskStatus.PENDING
        assert failed.error is None

    def test_failed_task_out_of_budget_stays_failed(self):
        """Retrying a defect that exhausted its attempts would loop forever."""
        failed = _task("broken", TaskStatus.FAILED, attempts=2, max_attempts=2)
        project = _project([failed])
        _orch().prepare_resume(project)
        assert failed.status is TaskStatus.FAILED
        assert failed.error == "previous error"

    def test_completed_work_survives_a_mixed_resume(self):
        done = _task("done", TaskStatus.SUCCEEDED)
        running = _task("mid-flight", TaskStatus.RUNNING)
        pending = _task("not started", TaskStatus.PENDING)
        project = _project([done, running, pending])
        _orch().prepare_resume(project)
        assert done.status is TaskStatus.SUCCEEDED
        assert running.status is TaskStatus.PENDING
        assert pending.status is TaskStatus.PENDING

    def test_project_is_marked_executing(self):
        project = _project([_task("t", TaskStatus.PENDING)])
        project.status = ProjectStatus.FAILED
        _orch().prepare_resume(project)
        assert project.status is ProjectStatus.EXECUTING

    def test_resume_is_recorded_in_the_log(self):
        project = _project([_task("t", TaskStatus.PENDING)])
        _orch().prepare_resume(project)
        assert any(e.kind == "resume" for e in project.events)
