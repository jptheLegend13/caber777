"""Unit tests for the domain model and storage layer."""

from __future__ import annotations

import pytest

from level5.models import (
    Project,
    ProjectStatus,
    Requirement,
    Task,
    TaskGraph,
    TaskStatus,
)


def test_project_log_appends_events():
    project = Project(name="demo", original_request="build a thing")
    project.log("phase", "started", phase="understanding")
    assert len(project.events) == 1
    assert project.events[0].kind == "phase"
    assert project.events[0].data["phase"] == "understanding"


def test_requirement_origin_defaults_to_user():
    assert Requirement(text="x").origin == "user"


def test_task_graph_ready_respects_dependencies():
    a = Task(title="A")
    b = Task(title="B", dependencies=[a.id])
    graph = TaskGraph(tasks=[a, b])
    assert [t.id for t in graph.ready()] == [a.id]
    a.status = TaskStatus.SUCCEEDED
    assert [t.id for t in graph.ready()] == [b.id]


def test_task_graph_ready_ignores_failed_dependencies():
    a = Task(title="A")
    b = Task(title="B", dependencies=[a.id])
    graph = TaskGraph(tasks=[a, b])
    a.status = TaskStatus.FAILED
    assert graph.ready() == []


async def test_store_roundtrip(store):
    project = Project(name="roundtrip", original_request="x")
    project.status = ProjectStatus.PLANNING
    await store.save(project)

    loaded = await store.get(project.id)
    assert loaded is not None
    assert loaded.name == "roundtrip"
    assert loaded.status == ProjectStatus.PLANNING


async def test_store_list_and_delete(store):
    a = Project(name="a", original_request="a")
    b = Project(name="b", original_request="b")
    await store.save(a)
    await store.save(b)

    items = await store.list()
    assert {i["id"] for i in items} == {a.id, b.id}

    assert await store.delete(a.id) is True
    assert await store.get(a.id) is None
    assert await store.delete("missing") is False


async def test_store_counts_by_status(store):
    await store.save(Project(name="a", original_request="a", status=ProjectStatus.DELIVERED))
    await store.save(Project(name="b", original_request="b", status=ProjectStatus.DELIVERED))
    await store.save(Project(name="c", original_request="c", status=ProjectStatus.FAILED))
    counts = await store.count_by_status()
    assert counts["delivered"] == 2
    assert counts["failed"] == 1
