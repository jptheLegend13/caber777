"""Per-task git worktree isolation.

When several tasks of one project run in parallel they share a single working
directory, so two agents can write the same file and silently overwrite each
other. This module gives each task its own git worktree and integrates the
result back into the project workspace under a lock, so changes from parallel
agents are combined in a coordinated order instead of racing.

Isolation is opt-in (``LEVEL5_TASK_WORKTREES=1``) because it requires the
project workspace to be a git repository. When it is not, or when a worktree
cannot be created, the orchestrator falls back to the shared workspace and
records that it did so rather than pretending isolation happened.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_GIT_IDENTITY = (
    "-c",
    "user.name=LEVEL 5",
    "-c",
    "user.email=level5@localhost",
)

# Directories that must never be committed from a generated project: they are
# large, machine-specific and would make a fresh `git add -A` enormous.
_DEFAULT_GITIGNORE = """\
node_modules/
dist/
build/
.venv/
__pycache__/
*.py[cod]
.level5-data/
.level5-worktrees/
*.log
.env
"""


class WorktreeError(RuntimeError):
    """A git worktree operation failed."""


def _run(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - env dependent
        raise WorktreeError(f"git {' '.join(args)} could not run: {exc}") from exc
    if check and result.returncode != 0:
        raise WorktreeError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:400]}"
        )
    return result


def is_git_repo(path: Path) -> bool:
    """True only when ``path`` is itself a repository root.

    A directory that merely sits *inside* another repository is not its own
    repository: treating it as one would make a project snapshot commit to the
    enclosing repository (for example the platform's own source tree when the
    data directory lives inside it).
    """
    path = Path(path)
    if not path.exists():
        return False
    if not (path / ".git").exists():
        return False
    result = _run(["rev-parse", "--git-dir"], path, check=False)
    return result.returncode == 0


def ensure_repo(root: Path) -> bool:
    """Make ``root`` a usable git repository with at least one commit.

    Returns True when the repository is ready for worktrees. An existing
    repository is left untouched (its own commits are the base).
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if not is_git_repo(root):
        _run(["init"], root)
        gitignore = root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(_DEFAULT_GITIGNORE, encoding="utf-8")
    # A worktree needs a base commit; create one if the history is empty.
    head = _run(["rev-parse", "--verify", "HEAD"], root, check=False)
    if head.returncode != 0:
        _run(["add", "-A"], root)
        _run([*_GIT_IDENTITY, "commit", "--allow-empty", "-m", "level5: base"], root)
    return True


@dataclass
class Worktree:
    task_id: str
    path: Path
    branch: str
    base_sha: str


class WorktreeManager:
    """Creates, commits, integrates and removes one worktree per task."""

    def __init__(self, repo_root: Path, worktrees_dir: Path) -> None:
        self.repo_root = Path(repo_root)
        self.worktrees_dir = Path(worktrees_dir)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self._active: dict[str, Worktree] = {}

    def _branch(self, task_id: str) -> str:
        return f"level5/{task_id}"

    def create(self, task_id: str) -> Worktree:
        path = self.worktrees_dir / task_id
        if path.exists():
            raise WorktreeError(f"worktree path already exists: {path}")
        base = _run(["rev-parse", "HEAD"], self.repo_root).stdout.strip()
        branch = self._branch(task_id)
        # A branch left over from a previous run must not block a fresh add.
        _run(["branch", "-D", branch], self.repo_root, check=False)
        _run(["worktree", "add", "-b", branch, str(path), base], self.repo_root)
        worktree = Worktree(task_id=task_id, path=path, branch=branch, base_sha=base)
        self._active[task_id] = worktree
        return worktree

    def commit(self, task_id: str, message: str) -> list[str]:
        """Commit the task's work and return the files it changed.

        Returns an empty list when the agent changed nothing.
        """
        worktree = self._active[task_id]
        _run(["add", "-A"], worktree.path)
        status = _run(["status", "--porcelain"], worktree.path).stdout.strip()
        if status:
            _run([*_GIT_IDENTITY, "commit", "-m", message[:200]], worktree.path)
        diff = _run(
            ["diff", "--name-only", worktree.base_sha, "HEAD"], worktree.path
        ).stdout
        return [line for line in diff.splitlines() if line.strip()]

    def integrate(self, task_id: str, message: str) -> list[str]:
        """Squash-merge the task branch into the project workspace.

        Falls back to copying the changed files when git reports a conflict, so
        one conflicting task cannot discard another task's committed work.
        """
        worktree = self._active[task_id]
        changed = self.commit(task_id, message)
        if not changed:
            return []
        merge = _run(
            ["merge", "--squash", "--no-commit", worktree.branch],
            self.repo_root,
            check=False,
        )
        if merge.returncode != 0:
            _run(["merge", "--abort"], self.repo_root, check=False)
            _run(["reset", "--hard", "HEAD"], self.repo_root, check=False)
            copied = self._copy_changes(worktree, changed)
            return copied
        _run([*_GIT_IDENTITY, "commit", "--no-edit", "-m", message[:200]], self.repo_root)
        return changed

    def _copy_changes(self, worktree: Worktree, changed: list[str]) -> list[str]:
        copied: list[str] = []
        for rel in changed:
            source = worktree.path / rel
            target = self.repo_root / rel
            if not source.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            copied.append(rel)
        return copied

    def remove(self, task_id: str) -> None:
        worktree = self._active.pop(task_id, None)
        if worktree is None:
            return
        _run(["worktree", "remove", "--force", str(worktree.path)], self.repo_root, check=False)
        _run(["branch", "-D", worktree.branch], self.repo_root, check=False)

    def cleanup(self) -> None:
        for task_id in list(self._active):
            self.remove(task_id)
