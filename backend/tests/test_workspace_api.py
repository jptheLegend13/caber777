"""API tests for workspace versioning, restore and export routes.

These drive the real FastAPI app against the real storage layer and real git.
No LLM work is triggered (projects are created with auto_start=false and the
workspace is populated directly on disk).
"""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from level5.api.app import create_app


@pytest.fixture
def client(_data_dir):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _make_project(client) -> dict:
    response = client.post(
        "/api/projects",
        json={"request": "Build a tiny tool that prints hello", "auto_start": False},
    )
    assert response.status_code == 201
    return response.json()["project"]


def _workspace(project: dict) -> str:
    return project["workspace_path"]


def test_versions_are_empty_for_a_new_project(client):
    project = _make_project(client)
    response = client.get(f"/api/projects/{project['id']}/versions")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_revisions_reflect_real_commits(client):
    from pathlib import Path

    from level5.workspace import snapshot

    project = _make_project(client)
    root = Path(_workspace(project))
    (root / "app.py").write_text("print('hi')")
    snapshot(root, "plan", "one task")
    (root / "test_app.py").write_text("def test(): pass")
    snapshot(root, "delivered", "all tasks")

    response = client.get(f"/api/projects/{project['id']}/revisions")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["message"] == "delivered: all tasks"
    assert len(items) >= 2


def test_revision_diff_is_served(client):
    from pathlib import Path

    from level5.workspace import snapshot

    project = _make_project(client)
    root = Path(_workspace(project))
    (root / "a.py").write_text("a")
    snapshot(root, "plan")
    (root / "b.py").write_text("b")
    sha = snapshot(root, "delivered")

    response = client.get(f"/api/projects/{project['id']}/revisions/{sha}/diff")
    assert response.status_code == 200
    assert "b.py" in response.json()["diff"]


def test_restore_rolls_back_and_records_event(client):
    from pathlib import Path

    from level5.workspace import snapshot

    project = _make_project(client)
    root = Path(_workspace(project))
    (root / "keep.py").write_text("keep")
    first = snapshot(root, "plan")
    (root / "later.py").write_text("later")
    snapshot(root, "delivered")

    response = client.post(
        f"/api/projects/{project['id']}/restore", json={"sha": first, "run": False}
    )
    assert response.status_code == 200
    assert response.json()["restored"] is True
    assert (root / "keep.py").exists()
    assert not (root / "later.py").exists()

    events = client.get(f"/api/projects/{project['id']}/events").json()["items"]
    assert any(e["kind"] == "restored" for e in events)


def test_restore_unknown_revision_is_rejected(client):
    project = _make_project(client)
    response = client.post(
        f"/api/projects/{project['id']}/restore", json={"sha": "deadbeef", "run": False}
    )
    assert response.status_code == 400


def test_export_returns_a_zip_of_deliverables(client):
    from pathlib import Path

    project = _make_project(client)
    root = Path(_workspace(project))
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hi')")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("junk")

    response = client.get(f"/api/projects/{project['id']}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert "src/app.py" in names
    assert not any("node_modules" in n for n in names)


def test_export_of_empty_workspace_is_rejected(client):
    project = _make_project(client)
    response = client.get(f"/api/projects/{project['id']}/export")
    assert response.status_code == 400
