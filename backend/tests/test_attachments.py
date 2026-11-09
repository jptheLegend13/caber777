"""Tests for request attachments (files, images, reference documents).

Exercises the real upload endpoint, the on-disk storage, the traversal guard
and the text-excerpt extraction that feeds request understanding.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from level5.api.app import create_app
from level5.intelligence.understanding import _render_attachments
from level5.models import Attachment


@pytest.fixture
def client(_data_dir):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _new_project(client: TestClient, request: str = "attachments test") -> dict:
    return client.post(
        "/api/projects", json={"request": request, "auto_start": False}
    ).json()["project"]


class TestUploadEndpoint:
    def test_upload_text_file_records_metadata_and_excerpt(self, client):
        project = _new_project(client)
        response = client.post(
            f"/api/projects/{project['id']}/attachments",
            files={"file": ("spec.txt", b"hello reference material", "text/plain")},
        )
        assert response.status_code == 201
        attachment = response.json()["attachment"]
        assert attachment["filename"] == "spec.txt"
        assert attachment["size_bytes"] == len(b"hello reference material")
        assert "hello reference material" in attachment["text_excerpt"]
        assert Path(attachment["path"]).exists()

    def test_uploaded_file_is_persisted_on_project(self, client):
        project = _new_project(client)
        client.post(
            f"/api/projects/{project['id']}/attachments",
            files={"file": ("a.md", b"# Title", "text/markdown")},
        )
        listed = client.get(f"/api/projects/{project['id']}/attachments").json()["items"]
        assert [a["filename"] for a in listed] == ["a.md"]
        reloaded = client.get(f"/api/projects/{project['id']}").json()["project"]
        assert len(reloaded["attachments"]) == 1

    def test_binary_upload_has_no_text_excerpt(self, client):
        project = _new_project(client)
        response = client.post(
            f"/api/projects/{project['id']}/attachments",
            files={"file": ("logo.png", b"\x89PNG\r\n\x1a\n\x00\x01", "image/png")},
        )
        assert response.status_code == 201
        assert response.json()["attachment"]["text_excerpt"] == ""

    def test_path_traversal_in_filename_is_neutralised(self, client, _data_dir):
        project = _new_project(client)
        response = client.post(
            f"/api/projects/{project['id']}/attachments",
            files={"file": ("../../evil.txt", b"payload", "text/plain")},
        )
        assert response.status_code == 201
        stored = Path(response.json()["attachment"]["path"])
        assert stored.name.endswith("evil.txt")
        assert stored.parent.name == "attachments"
        assert stored.parent.parent == Path(_data_dir) / "projects" / project["id"]

    def test_oversized_upload_is_rejected(self, client, monkeypatch):
        project = _new_project(client)
        from level5.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "max_attachment_bytes", 4, raising=False)
        response = client.post(
            f"/api/projects/{project['id']}/attachments",
            files={"file": ("big.txt", b"way too large", "text/plain")},
        )
        assert response.status_code == 413

    def test_delete_attachment_removes_file_and_record(self, client):
        project = _new_project(client)
        created = client.post(
            f"/api/projects/{project['id']}/attachments",
            files={"file": ("gone.txt", b"bye", "text/plain")},
        ).json()["attachment"]
        assert Path(created["path"]).exists()

        response = client.delete(
            f"/api/projects/{project['id']}/attachments/{created['id']}"
        )
        assert response.status_code == 200
        assert not Path(created["path"]).exists()
        assert client.get(f"/api/projects/{project['id']}/attachments").json()["items"] == []

    def test_delete_missing_attachment_returns_404(self, client):
        project = _new_project(client)
        response = client.delete(
            f"/api/projects/{project['id']}/attachments/att_missing"
        )
        assert response.status_code == 404

    def test_upload_to_missing_project_returns_404(self, client):
        response = client.post(
            "/api/projects/proj_missing/attachments",
            files={"file": ("x.txt", b"x", "text/plain")},
        )
        assert response.status_code == 404


class TestAttachmentPromptRendering:
    def test_no_attachments_renders_empty(self):
        assert _render_attachments(None) == ""
        assert _render_attachments([]) == ""

    def test_attachments_render_as_untrusted_reference_material(self):
        rendered = _render_attachments(
            [
                Attachment(
                    filename="notes.txt",
                    size_bytes=12,
                    text_excerpt="follow the spec",
                )
            ]
        )
        assert "notes.txt" in rendered
        assert "follow the spec" in rendered
        # Contents are labelled untrusted so a prompt-injection attempt in an
        # uploaded document is treated as data, not as instructions.
        assert "not instructions" in rendered
