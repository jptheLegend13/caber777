"""Tests for project workspace versioning, restore and export.

These exercise real git and real zip against temporary directories — no mocks.
"""

from __future__ import annotations

import subprocess
import zipfile

import pytest

from level5.workspace import (
    WorkspaceError,
    diff,
    export_zip,
    restore,
    revisions,
    snapshot,
)


class TestSnapshot:
    def test_first_snapshot_creates_a_revision(self, tmp_path):
        (tmp_path / "main.py").write_text("print(1)")
        sha = snapshot(tmp_path, "plan", "one task")
        assert sha
        revs = revisions(tmp_path)
        assert revs[0].message == "plan: one task"

    def test_distinct_steps_are_distinct_revisions(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        first = snapshot(tmp_path, "plan")
        (tmp_path / "b.py").write_text("b")
        second = snapshot(tmp_path, "delivered")
        assert first != second
        assert len(revisions(tmp_path)) >= 2

    def test_identical_repeat_does_not_duplicate(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        first = snapshot(tmp_path, "delivered")
        again = snapshot(tmp_path, "delivered")
        assert first == again

    def test_unchanged_files_still_record_the_label(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        snapshot(tmp_path, "plan")
        sha = snapshot(tmp_path, "delivered")
        assert sha
        assert revisions(tmp_path)[0].message == "delivered"


class TestRestore:
    def test_restore_rolls_files_back(self, tmp_path):
        (tmp_path / "keep.py").write_text("keep")
        first = snapshot(tmp_path, "plan")
        (tmp_path / "later.py").write_text("later")
        snapshot(tmp_path, "delivered")
        assert (tmp_path / "later.py").exists()
        restore(tmp_path, first)
        assert (tmp_path / "keep.py").exists()
        assert not (tmp_path / "later.py").exists()

    def test_restore_is_itself_reversible(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        first = snapshot(tmp_path, "plan")
        (tmp_path / "b.py").write_text("b")
        snapshot(tmp_path, "delivered")
        restore(tmp_path, first)
        # A pre-restore branch must exist so the founder can step back.
        branches = subprocess.run(
            ["git", "branch", "--list", "level5/pre-restore-*"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        ).stdout
        assert "pre-restore" in branches

    def test_unknown_revision_is_rejected(self, tmp_path):
        snapshot(tmp_path, "plan")
        with pytest.raises(WorkspaceError):
            restore(tmp_path, "deadbeef")


class TestDiff:
    def test_diff_shows_the_introduced_file(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        snapshot(tmp_path, "plan")
        (tmp_path / "b.py").write_text("b")
        second = snapshot(tmp_path, "delivered")
        text = diff(tmp_path, second)
        assert "b.py" in text


class TestExport:
    def test_export_excludes_dependency_trees(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("print('hi')")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "junk.js").write_text("junk")
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "bundle.js").write_text("bundle")
        out = tmp_path.parent / "export.zip"
        export_zip(tmp_path, out)
        names = zipfile.ZipFile(out).namelist()
        assert "src/app.py" in names
        assert not any("node_modules" in n for n in names)
        assert not any(n.startswith("dist/") for n in names)

    def test_empty_workspace_cannot_be_exported(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(WorkspaceError):
            export_zip(empty, tmp_path / "out.zip")
