"""Tests for the cross-intelligence handoff (Milestone 6, C -> A).

These exercise the real handoff: a building project's scene artifact is copied
into a new application project, the application is generated and its real build
runs. Only the LLM is absent — the building is supplied as a real on-disk scene,
so no model call is needed and no network boundary is mocked.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from level5.api.routes import _looks_like_building_viewer
from level5.config import get_settings
from level5.integration import (
    HandoffError,
    create_building_viewer_app,
    ensure_building_project,
)
from level5.models import CABERModule, Project, ProjectStatus, Specification
from level5.storage.store import get_store


def _scene() -> dict:
    return {
        "title": "Test Villa",
        "units": "metres",
        "primitives": [
            {
                "id": "ground",
                "kind": "ground",
                "name": "Ground",
                "position": [0.0, -0.1, 0.0],
                "size": [10.0, 0.2, 10.0],
                "rotation": [0.0, 0.0, 0.0],
                "material": {
                    "color": "#6f7a63",
                    "roughness": 1.0,
                    "metalness": 0.0,
                    "opacity": 1.0,
                },
                "room_id": None,
                "object_id": None,
            },
            {
                "id": "wall_0",
                "kind": "wall",
                "name": "Wall",
                "position": [0.0, 1.4, -5.0],
                "size": [10.0, 2.8, 0.2],
                "rotation": [0.0, 0.0, 0.0],
                "material": {
                    "color": "#d9d2c5",
                    "roughness": 0.9,
                    "metalness": 0.0,
                    "opacity": 1.0,
                },
                "room_id": None,
                "object_id": None,
            },
        ],
        "lights": [
            {
                "id": "light_0",
                "kind": "ambient",
                "intensity": 0.5,
                "color": "#ffffff",
                "position": [0.0, 3.0, 0.0],
            }
        ],
        "bounds": {
            "min": [-5.0, 0.0, -5.0],
            "max": [5.0, 3.0, 5.0],
            "center": [0.0, 1.5, 0.0],
            "size": [10.0, 3.0, 10.0],
        },
        "stats": {
            "rooms": 1,
            "objects": 0,
            "primitives": 2,
            "floor_area": 25.0,
            "floors": 1,
        },
        "metadata": {
            "category": "villa",
            "style": "modern",
            "roof_type": "flat",
            "environment": {},
        },
    }


async def _make_building(request: str, *, with_scene: bool = True) -> Project:
    project = Project(name="Test Villa", original_request=request)
    project.specification.caber_module = CABERModule.BUILDING
    project.workspace_path = str(get_settings().projects_dir / project.id)
    workspace = Path(project.workspace_path)
    workspace.mkdir(parents=True, exist_ok=True)
    if with_scene:
        (workspace / "building.scene.json").write_text(
            json.dumps(_scene()), encoding="utf-8"
        )
        (workspace / "building.spec.json").write_text(
            json.dumps({"title": "Test Villa"}), encoding="utf-8"
        )
    await get_store().save(project)
    return project


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for the app build")
async def test_handoff_builds_a_real_viewer_app():
    building = await _make_building("Design a modern villa")
    app = await create_building_viewer_app(building.id)

    assert app.specification.caber_module == CABERModule.APPLICATION
    assert app.status == ProjectStatus.DELIVERED
    assert app.preview_url == f"/api/projects/{app.id}/preview/"

    workspace = Path(app.workspace_path)
    assert (workspace / "building.scene.json").is_file()
    dist = workspace / "web" / "dist"
    assert (dist / "index.html").is_file()
    assert (dist / "viewer.js").is_file()
    assert (dist / "building.scene.json").is_file()

    # The build ran for real and validated the scene.
    build_tests = [t for t in app.tests if t.suite == "build"]
    assert build_tests and build_tests[0].status == "passed"
    assert "viewer built" in build_tests[0].message

    kinds = {a.kind for a in app.artifacts}
    assert "preview" in kinds and "model3d" in kinds
    handoff = [e for e in app.events if e.kind == "handoff"]
    assert handoff and handoff[0].data["source_project"] == building.id
    assert handoff[0].data["module_from"] == "C"
    assert handoff[0].data["module_to"] == "A"


async def test_handoff_fails_loudly_without_a_scene():
    building = await _make_building("Design a villa with no scene yet", with_scene=False)
    with pytest.raises(HandoffError):
        await create_building_viewer_app(building.id)


async def test_handoff_rejects_a_non_building_project():
    project = Project(name="Not a building", original_request="Build a dashboard")
    project.specification.caber_module = CABERModule.APPLICATION
    project.workspace_path = str(get_settings().projects_dir / project.id)
    await get_store().save(project)
    with pytest.raises(HandoffError):
        await create_building_viewer_app(project.id)


async def test_ensure_building_project_reuses_an_existing_scene():
    request = "Design a reusable lakeside cabin"
    first = await _make_building(request)
    again = await ensure_building_project(request)
    assert again.id == first.id


def _spec(deliverable: str = "", intent: str = "") -> Specification:
    spec = Specification()
    spec.deliverable = deliverable
    spec.intent = intent
    return spec


class TestViewerClassification:
    def test_plain_building_request_is_not_a_viewer_app(self):
        # "Build a house" is Intelligence C, not an application.
        assert not _looks_like_building_viewer("Build a modern house", _spec())

    def test_plain_app_request_is_not_a_building_viewer(self):
        assert not _looks_like_building_viewer(
            "Build a project management dashboard", _spec()
        )

    def test_building_viewer_app_request_matches(self):
        assert _looks_like_building_viewer(
            "Build a web application that displays a building in 3D", _spec()
        )

    def test_virtual_tour_matches(self):
        assert _looks_like_building_viewer(
            "Create a virtual tour of a villa", _spec()
        )

    def test_incidental_substring_does_not_match(self):
        # "happy" contains "app"; it must not trigger the handoff on its own.
        assert not _looks_like_building_viewer("Design a happy family home", _spec())

    def test_app_term_requires_a_building_subject(self):
        assert not _looks_like_building_viewer("Build a viewer for my data", _spec())


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for the app build")
async def test_command_box_routes_a_viewer_request_through_the_handoff(monkeypatch):
    """A viewer request from the command box reaches the handoff before the
    building branch, even though its text contains "building" (which classifies
    it as module C).

    Only the understanding step is replaced, because that step normally calls the
    model; everything after it — scene discovery, app generation and the real
    build — runs unchanged.
    """
    from level5.api import routes

    request = "Build a web application that displays my villa in 3D"
    building = await _make_building(request)

    async def fake_understand(project: Project) -> Project:
        project.specification.caber_module = CABERModule.BUILDING
        project.specification.deliverable = "3D building"
        return project

    monkeypatch.setattr(routes._orchestrator, "understand", fake_understand)

    project = Project(name="viewer", original_request=request)
    project.workspace_path = str(get_settings().projects_dir / project.id)
    Path(project.workspace_path).mkdir(parents=True, exist_ok=True)
    await get_store().save(project)

    await routes._run_full_pipeline(project.id, research=False)

    saved = await get_store().get(project.id)
    assert saved.specification.caber_module == CABERModule.APPLICATION
    assert saved.status == ProjectStatus.DELIVERED
    assert any(e.kind == "handoff" and e.data["source_project"] == building.id
               for e in saved.events)

