"""Regression tests for the task-graph integrity boundary."""

from __future__ import annotations

import pytest

from level5.models import Task, TaskGraph


def test_task_graph_validation_accepts_an_acyclic_graph() -> None:
    first = Task(id="requirements", title="Extract requirements")
    second = Task(
        id="implementation",
        title="Implement feature",
        dependencies=["requirements"],
    )

    TaskGraph(tasks=[first, second]).validate()


@pytest.mark.parametrize(
    "tasks, message",
    [
        (
            [
                Task(id="implementation", title="Implement", dependencies=["missing"]),
            ],
            "unknown task",
        ),
        (
            [
                Task(id="a", title="A", dependencies=["b"]),
                Task(id="b", title="B", dependencies=["a"]),
            ],
            "dependency cycle",
        ),
        (
            [
                Task(id="same", title="First"),
                Task(id="same", title="Second"),
            ],
            "duplicate task IDs",
        ),
    ],
)
def test_task_graph_validation_rejects_invalid_dependencies(
    tasks: list[Task], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        TaskGraph(tasks=tasks).validate()
