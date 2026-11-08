"""Reproducible self-benchmarking.

Records what LEVEL 5 actually measured on a real run: task success rate, test
results, artifact counts, elapsed time and the acceptance-criteria rate. These
are LEVEL 5's own numbers on its own tasks.

This module deliberately does **not** compare LEVEL 5 against other systems.
Such a comparison is only meaningful under equivalent tasks, models and
hardware, and none has been run. See docs/ROADMAP.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from level5.models import Project, TaskStatus
from level5.storage.store import get_store


def summarise(project: Project) -> dict[str, Any]:
    """Compute the measured metrics for one project."""
    tasks = project.task_graph.tasks
    succeeded = [t for t in tasks if t.status == TaskStatus.SUCCEEDED]
    failed = [t for t in tasks if t.status == TaskStatus.FAILED]
    skipped = [t for t in tasks if t.status == TaskStatus.SKIPPED]

    tests = project.tests
    tests_passed = [t for t in tests if t.status == "passed"]
    tests_failed = [t for t in tests if t.status in ("failed", "error")]

    criteria = project.specification.acceptance_criteria
    criteria_met = [c for c in criteria if c.satisfied]

    started = project.created_at
    finished = project.updated_at
    duration = max(0.0, (finished - started).total_seconds())

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "project_id": project.id,
        "project_name": project.name,
        "domain": project.specification.domain.value,
        "caber_module": project.specification.caber_module.value,
        "status": project.status.value,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "tasks_total": len(tasks),
        "tasks_succeeded": len(succeeded),
        "tasks_failed": len(failed),
        "tasks_skipped": len(skipped),
        "task_success_rate": ratio(len(succeeded), len(tasks)),
        "tests_total": len(tests),
        "tests_passed": len(tests_passed),
        "tests_failed": len(tests_failed),
        "test_pass_rate": ratio(len(tests_passed), len(tests)),
        "criteria_total": len(criteria),
        "criteria_met": len(criteria_met),
        "criteria_rate": ratio(len(criteria_met), len(criteria)),
        "artifacts": len(project.artifacts),
        "agent_conversations": len(project.conversation_ids),
        "duration_seconds": round(duration, 1),
        "model": _model_name(),
    }


async def record(project: Project) -> dict[str, Any]:
    """Persist a benchmark record for a completed project."""
    record = summarise(project)
    await get_store().save_benchmark(record)
    return record


def _model_name() -> str:
    from level5.config import get_settings

    return get_settings().llm_model
