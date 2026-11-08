"""Web-application build and static preview.

A generated web app is only a working deliverable once it builds. This module
finds the app's package root, runs its real build command, and exposes the
resulting static output for the workspace's browser preview.

Everything here executes the project's own toolchain. Nothing is simulated: if
the build fails, the failure and its output are reported, not hidden.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("level5.preview")

# Directories that commonly hold the front end of a generated monorepo.
_CANDIDATE_DIRS = ("", "apps/web", "frontend", "web", "client", "apps/frontend")
# Where a bundler usually writes its output, relative to the package root.
_DIST_CANDIDATES = ("dist", "build", "out", ".output/public")


@dataclass
class BuildResult:
    attempted: bool = False
    succeeded: bool = False
    package_dir: str = ""
    command: str = ""
    output: str = ""
    dist_dir: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "package_dir": self.package_dir,
            "command": self.command,
            "output": self.output[-4000:],
            "dist_dir": self.dist_dir,
        }


@dataclass
class WebApp:
    package_dir: Path
    build_script: str
    dist_dir: Path | None = None
    tags: list[str] = field(default_factory=list)


def _read_package_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def detect_web_app(workspace: str | Path) -> WebApp | None:
    """Find a Node package with a build script inside the workspace.

    Searched shallowly and in a fixed order so the choice is deterministic.
    """
    root = Path(workspace)
    for rel in _CANDIDATE_DIRS:
        pkg_dir = root / rel if rel else root
        pkg = _read_package_json(pkg_dir / "package.json")
        if not pkg:
            continue
        scripts = pkg.get("scripts") or {}
        build = scripts.get("build")
        if not isinstance(build, str) or not build.strip():
            continue
        app = WebApp(package_dir=pkg_dir, build_script=build)
        app.dist_dir = find_dist(pkg_dir)
        return app
    return None


def find_dist(package_dir: Path) -> Path | None:
    """Return the built output directory if it contains an index.html."""
    for name in _DIST_CANDIDATES:
        candidate = package_dir / name
        if (candidate / "index.html").is_file():
            return candidate
    return None


def static_preview_dir(workspace: str | Path) -> Path | None:
    """Directory to serve as the static preview, if the app has been built."""
    app = detect_web_app(workspace)
    if app and app.dist_dir:
        return app.dist_dir
    # A plain static site with no package.json.
    root = Path(workspace)
    for rel in ("dist", "public", "build", "site", ""):
        candidate = root / rel if rel else root
        if (candidate / "index.html").is_file():
            return candidate
    return None


def build_web_app(workspace: str | Path, *, timeout: float = 900.0) -> BuildResult:
    """Run the app's real build command and report the true outcome."""
    app = detect_web_app(workspace)
    if app is None:
        return BuildResult(attempted=False, output="no web app with a build script found")

    result = BuildResult(
        attempted=True,
        package_dir=str(app.package_dir),
        command=f"npm run build  ({app.build_script})",
    )

    npm = shutil.which("npm")
    if npm is None:
        result.output = "npm is not available in this environment; build skipped"
        return result

    try:
        proc = subprocess.run(  # noqa: S603 - the command is the project's own build script
            [npm, "run", "build"],
            cwd=str(app.package_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        result.output = f"build timed out after {timeout:.0f}s\n{(exc.stdout or '')[-2000:]}"
        return result
    except OSError as exc:
        result.output = f"build could not start: {exc}"
        return result

    result.output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    result.succeeded = proc.returncode == 0
    if result.succeeded:
        dist = find_dist(app.package_dir)
        result.dist_dir = str(dist) if dist else None
        if dist is None:
            # The build reported success but produced no index.html. Say so
            # rather than serving a directory that is not there.
            result.succeeded = False
            result.output += "\nbuild exited 0 but produced no index.html"
    return result
