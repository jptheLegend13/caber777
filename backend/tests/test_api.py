"""API integration tests.

These exercise the real FastAPI application and the real storage layer. They do
not trigger LLM work: project creation is tested with `auto_start=false`, and the
agent-driven pipeline is covered separately by the orchestrator tests (which
replace only the network boundary).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from level5.api.app import create_app


@pytest.fixture
def client(_data_dir):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_service_and_agent_server(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "LEVEL 5"
    assert "agent_server" in body
    assert set(body["caber_modules"]) == {"A", "B", "C", "P"}


def test_agents_endpoint_lists_disciplines(client):
    response = client.get("/api/agents")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 30
    assert "software" in body["disciplines"]
    assert "graphics" in body["disciplines"]


def test_agent_detail_and_fallback(client):
    response = client.get("/api/agents/product_architect")
    assert response.status_code == 200
    assert response.json()["discipline"] == "software"

    fallback = client.get("/api/agents/not_a_real_role")
    assert fallback.status_code == 200
    assert fallback.json()["name"] == "fullstack_engineer"


def test_create_project_without_autostart(client):
    response = client.post(
        "/api/projects",
        json={"request": "Build a small internal tool", "auto_start": False},
    )
    assert response.status_code == 201
    project = response.json()["project"]
    assert project["name"]
    assert project["status"] == "draft"
    assert project["original_request"] == "Build a small internal tool"

    listed = client.get("/api/projects").json()
    assert any(item["id"] == project["id"] for item in listed["items"])


def test_get_missing_project_returns_404(client):
    assert client.get("/api/projects/does-not-exist").status_code == 404


def test_delete_project(client):
    created = client.post(
        "/api/projects", json={"request": "temp project", "auto_start": False}
    ).json()["project"]
    assert client.delete(f"/api/projects/{created['id']}").status_code == 200
    assert client.get(f"/api/projects/{created['id']}").status_code == 404
    assert client.delete(f"/api/projects/{created['id']}").status_code == 404


def test_file_browser_lists_workspace(client):
    created = client.post(
        "/api/projects", json={"request": "file browser test", "auto_start": False}
    ).json()["project"]
    response = client.get(f"/api/projects/{created['id']}/files")
    assert response.status_code == 200
    assert response.json()["type"] == "directory"


def test_file_browser_blocks_path_traversal(client):
    created = client.post(
        "/api/projects", json={"request": "traversal test", "auto_start": False}
    ).json()["project"]
    response = client.get(
        f"/api/projects/{created['id']}/files", params={"path": "../../../../etc/passwd"}
    )
    assert response.status_code in (400, 404)
    assert "passwd" not in response.text or response.status_code == 404


def test_report_missing_before_run(client):
    created = client.post(
        "/api/projects", json={"request": "no report yet", "auto_start": False}
    ).json()["project"]
    assert client.get(f"/api/projects/{created['id']}/report").status_code == 404


def test_caber_scene_missing_for_non_building_project(client):
    created = client.post(
        "/api/projects", json={"request": "not a building", "auto_start": False}
    ).json()["project"]
    assert client.get(f"/api/projects/{created['id']}/caber/scene").status_code == 404


def test_events_endpoint_returns_creation_event(client):
    created = client.post(
        "/api/projects", json={"request": "events test", "auto_start": False}
    ).json()["project"]
    response = client.get(f"/api/projects/{created['id']}/events")
    assert response.status_code == 200
    events = response.json()["items"]
    assert any(event["kind"] == "created" for event in events)


def test_openapi_schema_is_served(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "LEVEL 5"
    assert "/api/projects" in schema["paths"]
