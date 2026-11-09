"""Project workspace versioning, export and restore.

A project's deliverables live on disk under its workspace directory. This
module turns that directory into a git repository so every meaningful step
(plan, delivered, solution, building, innovation, handoff) is a real, named
commit that can be listed, compared, restored and exported.

Everything here runs real ``git`` and real ``zip`` against the project's own
files. Nothing is simulated: a restore that fails reports the failure.
"""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from level5.worktrees import _GIT_IDENTITY, _run, ensure_repo, is_git_repo

logger = logging.getLogger("level5.workspace")

# Large, machine-specific trees that must never enter a snapshot or an export.
_EXPORT_EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".level5-worktrees",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".next",
    "target",
}
_EXPORT_EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".db"}


class WorkspaceError(RuntimeError):
    """A workspace git/export operation failed."""


@dataclass
class Revision:
    sha: str
    short: str
    message: str
    committed_at: str
    files_changed: int


def _head_sha(root: Path) -> str | None:
    result = _run(["rev-parse", "--verify", "HEAD"], root, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def snapshot(root: Path, label: str, note: str = "") -> str | None:
    """Commit the current workspace state as a named revision.

    Returns the commit sha, or ``None`` when the workspace cannot be committed.
    The workspace is made a git repository on first use. When nothing changed
    since the last commit, an empty commit records the label anyway, unless the
    head already carries it (so repeated identical snapshots do not pile up).
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    ensure_repo(root)
    _run(["add", "-A"], root)
    message = f"{label}: {note}" if note else label
    head_message = _run(["log", "-1", "--pretty=%s"], root, check=False).stdout.strip()
    if head_message == message:
        return _head_sha(root)
    result = _run(
        [*_GIT_IDENTITY, "commit", "--allow-empty", "-m", message], root, check=False
    )
    if result.returncode != 0:
        raise WorkspaceError(
            f"git commit failed: {(result.stderr or result.stdout).strip()[:400]}"
        )
    return _head_sha(root)


def revisions(root: Path, limit: int = 100) -> list[Revision]:
    """List the workspace revisions, newest first."""
    root = Path(root)
    if not is_git_repo(root) or _head_sha(root) is None:
        return []
    fmt = "%H%x1f%h%x1f%s%x1f%cI"
    result = _run(
        ["log", f"--max-count={limit}", f"--pretty=format:{fmt}", "--shortstat"],
        root,
        check=False,
    )
    if result.returncode != 0:
        return []
    out: list[Revision] = []
    pending: dict[str, str] | None = None
    for line in result.stdout.splitlines():
        if "\x1f" in line:
            if pending:
                out.append(_to_revision(pending))
            full, short, message, committed = (line.split("\x1f") + ["", "", "", ""])[:4]
            pending = {
                "sha": full,
                "short": short,
                "message": message,
                "committed_at": committed,
            }
        elif pending is not None and "changed" in line:
            pending["files"] = line.strip()
    if pending:
        out.append(_to_revision(pending))
    return out


def _to_revision(data: dict[str, str]) -> Revision:
    files = 0
    for token in data.get("files", "").replace(",", " ").split():
        if token.isdigit():
            files = int(token)
            break
    return Revision(
        sha=data["sha"],
        short=data["short"],
        message=data["message"],
        committed_at=data["committed_at"],
        files_changed=files,
    )


def diff(root: Path, sha: str) -> str:
    """Return the unified diff introduced by ``sha`` (capped)."""
    root = Path(root)
    result = _run(["show", "--stat", "--patch", sha], root, check=False)
    if result.returncode != 0:
        raise WorkspaceError(f"git show failed: {(result.stderr or result.stdout)[:400]}")
    return result.stdout[:20000]


def restore(root: Path, sha: str) -> None:
    """Reset the working tree to ``sha``.

    A safety revision of the current state is committed first and kept on a
    ``level5/pre-restore-*`` branch so the rollback is itself reversible — the
    founder can always step back to the state they left.
    """
    root = Path(root)
    if not is_git_repo(root):
        raise WorkspaceError("workspace is not a git repository")
    verify = _run(["cat-file", "-e", f"{sha}^{{commit}}"], root, check=False)
    if verify.returncode != 0:
        raise WorkspaceError(f"unknown revision: {sha}")
    snapshot(root, "pre-restore", note=f"state before restoring {sha[:8]}")
    # Keep the just-created safety commit reachable before we move HEAD away.
    stamp = _run(["log", "-1", "--pretty=%ct"], root, check=False).stdout.strip()
    branch = f"level5/pre-restore-{stamp or 'state'}"
    _run(["branch", "-f", branch, "HEAD"], root, check=False)
    result = _run(["reset", "--hard", sha], root, check=False)
    if result.returncode != 0:
        raise WorkspaceError(f"git reset failed: {(result.stderr or result.stdout)[:400]}")
    _run(["clean", "-fd", "-e", ".level5-worktrees"], root, check=False)


def export_zip(root: Path, destination: Path) -> Path:
    """Write a zip of the workspace deliverables to ``destination``.

    Build outputs, dependency trees and version-control metadata are excluded so
    the archive contains the source the founder asked for, not machine junk.
    """
    root = Path(root).resolve()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root)
            if any(part in _EXPORT_EXCLUDE_DIRS for part in rel.parts):
                continue
            if path.suffix.lower() in _EXPORT_EXCLUDE_SUFFIXES:
                continue
            try:
                archive.write(path, arcname=str(rel))
                count += 1
            except (OSError, ValueError):
                continue
    if count == 0:
        raise WorkspaceError("workspace has no files to export")
    return destination
