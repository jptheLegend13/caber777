"""Tests for per-task git worktree isolation (directive §19/§9, finding F3).

These exercise real git: repositories are created, worktrees are added, files
are written, commits are made and branches are merged. Only the agent network
boundary is replaced in the orchestrator test; the isolation mechanism itself is
real.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from level5.models import Project, Task, TaskStatus
from level5.orchestrator import Orchestrator
from level5.worktrees import WorktreeManager, ensure_repo, is_git_repo


def _manager(tmp_path: Path) -> tuple[WorktreeManager, Path]:
    root = tmp_path / "ws"
    root.mkdir()
    ensure_repo(root)
    return WorktreeManager(root, root / ".level5-worktrees"), root


def test_ensure_repo_initialises_git(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    assert not is_git_repo(root)
    ensure_repo(root)
    assert is_git_repo(root)
    # Idempotent: a second call must not disturb the existing repository.
    ensure_repo(root)
    assert is_git_repo(root)


def test_isolated_task_work_lands_in_the_shared_workspace(tmp_path):
    manager, root = _manager(tmp_path)
    worktree = manager.create("t1")
    assert worktree.path.exists()
    (worktree.path / "feature.txt").write_text("real work", encoding="utf-8")

    changed = manager.integrate("t1", "[engineer] build feature")
    assert changed == ["feature.txt"]
    assert (root / "feature.txt").read_text(encoding="utf-8") == "real work"
    manager.remove("t1")
    assert not worktree.path.exists()


def test_parallel_tasks_with_disjoint_files_both_integrate(tmp_path):
    manager, root = _manager(tmp_path)
    a = manager.create("ta")
    b = manager.create("tb")
    (a.path / "a.txt").write_text("a", encoding="utf-8")
    (b.path / "b.txt").write_text("b", encoding="utf-8")

    manager.integrate("ta", "[a] write a")
    manager.integrate("tb", "[b] write b")

    assert (root / "a.txt").exists()
    assert (root / "b.txt").exists()


def test_conflicting_change_falls_back_to_copy_without_losing_work(tmp_path):
    manager, root = _manager(tmp_path)
    a = manager.create("ta")
    b = manager.create("tb")
    # Both agents edit the same file: a genuine conflict.
    (a.path / "shared.txt").write_text("from-a", encoding="utf-8")
    (a.path / "only-a.txt").write_text("a", encoding="utf-8")
    (b.path / "shared.txt").write_text("from-b", encoding="utf-8")

    manager.integrate("ta", "[a] edit shared")
    changed_b = manager.integrate("tb", "[b] edit shared")

    # b's version wins on the conflicting file, and a's non-conflicting file is
    # not discarded by the failed merge.
    assert (root / "shared.txt").read_text(encoding="utf-8") == "from-b"
    assert (root / "only-a.txt").read_text(encoding="utf-8") == "a"
    assert "shared.txt" in changed_b


def test_remove_cleans_up_worktree_and_branch(tmp_path):
    manager, root = _manager(tmp_path)
    worktree = manager.create("t1")
    manager.remove("t1")
    assert not worktree.path.exists()
    import subprocess

    branches = subprocess.run(
        ["git", "branch", "--list", "level5/t1"],
        cwd=str(root),
        capture_output=True,
        text=True,
    ).stdout
    assert branches.strip() == ""


class _FileWritingAgent:
    """Creates a real file in whatever directory it is handed."""

    def __init__(self) -> None:
        self.dirs: list[str] = []

    async def run_to_completion(
        self, *, working_dir, task_prompt, tools, system_prompt, max_iterations, timeout
    ):
        from level5.runtime.agent_server import ExecutionResult

        self.dirs.append(working_dir)
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        name = f"out_{len(self.dirs)}.txt"
        Path(working_dir, name).write_text("done", encoding="utf-8")
        return ExecutionResult(
            conversation_id=f"conv_{len(self.dirs)}",
            status="finished",
            final_message="wrote a file",
            files_changed=[name],
        )


def _project_with(tmp_path, tasks: list[Task]) -> Project:
    project = Project(name="wt-test", original_request="test")
    project.workspace_path = str(tmp_path / "ws")
    Path(project.workspace_path).mkdir(parents=True, exist_ok=True)
    project.task_graph.tasks = tasks
    return project


def test_orchestrator_isolates_and_integrates_each_task(tmp_path):
    from level5.config import Settings

    settings = Settings()
    settings.task_worktrees = True
    agent = _FileWritingAgent()
    orch = Orchestrator(agent_client=agent, settings=settings)
    tasks = [
        Task(title="One", description="d", agent_role="backend_engineer"),
        Task(title="Two", description="d", agent_role="frontend_engineer"),
    ]
    project = _project_with(tmp_path, tasks)

    asyncio.run(orch.execute(project))

    # Each agent ran in a directory that is not the shared workspace.
    shared = str(Path(project.workspace_path))
    assert all(d != shared for d in agent.dirs)
    assert all(".level5-worktrees" in d for d in agent.dirs)
    # Both tasks' files were merged into the shared workspace...
    root = Path(project.workspace_path)
    assert (root / "out_1.txt").exists()
    assert (root / "out_2.txt").exists()
    # ...and the worktrees were cleaned up afterwards.
    for task in tasks:
        assert task.status == TaskStatus.SUCCEEDED
        assert task.worktree is None
    kinds = [e.kind for e in project.events]
    assert "task_isolation" in kinds
    assert "task_integrated" in kinds


def test_orchestrator_without_flag_uses_the_shared_workspace(tmp_path):
    from level5.config import Settings

    settings = Settings()
    settings.task_worktrees = False
    agent = _FileWritingAgent()
    orch = Orchestrator(agent_client=agent, settings=settings)
    tasks = [Task(title="One", description="d", agent_role="backend_engineer")]
    project = _project_with(tmp_path, tasks)

    asyncio.run(orch.execute(project))

    assert agent.dirs == [str(Path(project.workspace_path))]
