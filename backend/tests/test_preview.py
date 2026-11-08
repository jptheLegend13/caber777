"""Tests for web-app detection and the static preview.

Detection must find the right package, find the real build output, and refuse
to call an unbuilt app previewable. These run against real files on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from level5.preview import detect_web_app, find_dist, static_preview_dir


def _write_pkg(root: Path, rel: str, scripts: dict, name: str = "app") -> Path:
    pkg_dir = root / rel if rel else root
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "package.json").write_text(
        json.dumps({"name": name, "scripts": scripts}), encoding="utf-8"
    )
    return pkg_dir


class TestDetection:
    def test_finds_root_package_with_build(self, tmp_path):
        _write_pkg(tmp_path, "", {"build": "vite build", "dev": "vite"})
        app = detect_web_app(tmp_path)
        assert app is not None
        assert app.build_script == "vite build"
        assert app.package_dir == tmp_path

    def test_finds_apps_web_package(self, tmp_path):
        _write_pkg(tmp_path, "apps/web", {"build": "next build"})
        app = detect_web_app(tmp_path)
        assert app is not None
        assert app.package_dir == tmp_path / "apps/web"

    def test_package_without_build_script_is_ignored(self, tmp_path):
        _write_pkg(tmp_path, "", {"dev": "vite", "test": "vitest"})
        assert detect_web_app(tmp_path) is None

    def test_empty_build_script_is_ignored(self, tmp_path):
        _write_pkg(tmp_path, "", {"build": "   "})
        assert detect_web_app(tmp_path) is None

    def test_no_package_json_at_all(self, tmp_path):
        assert detect_web_app(tmp_path) is None

    def test_malformed_package_json_is_skipped(self, tmp_path):
        (tmp_path / "package.json").write_text("{not json", encoding="utf-8")
        assert detect_web_app(tmp_path) is None

    def test_detection_is_deterministic_between_candidates(self, tmp_path):
        _write_pkg(tmp_path, "", {"build": "a"})
        _write_pkg(tmp_path, "frontend", {"build": "b"})
        # The root candidate is searched first, so it wins.
        app = detect_web_app(tmp_path)
        assert app is not None and app.build_script == "a"


class TestDistFinding:
    def test_find_dist_requires_index_html(self, tmp_path):
        (tmp_path / "dist").mkdir()
        assert find_dist(tmp_path) is None
        (tmp_path / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
        assert find_dist(tmp_path) == tmp_path / "dist"

    def test_find_dist_prefers_dist_over_build(self, tmp_path):
        for name in ("dist", "build"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "index.html").write_text("x", encoding="utf-8")
        assert find_dist(tmp_path) == tmp_path / "dist"


class TestStaticPreviewDir:
    def test_unbuilt_app_is_not_previewable(self, tmp_path):
        _write_pkg(tmp_path, "", {"build": "vite build"})
        assert static_preview_dir(tmp_path) is None

    def test_built_app_is_previewable(self, tmp_path):
        pkg = _write_pkg(tmp_path, "", {"build": "vite build"})
        (pkg / "dist").mkdir()
        (pkg / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
        assert static_preview_dir(tmp_path) == pkg / "dist"

    def test_plain_static_site_without_package_json(self, tmp_path):
        (tmp_path / "public").mkdir()
        (tmp_path / "public" / "index.html").write_text("<html></html>", encoding="utf-8")
        assert static_preview_dir(tmp_path) == tmp_path / "public"

    def test_empty_workspace_has_no_preview(self, tmp_path):
        assert static_preview_dir(tmp_path) is None
