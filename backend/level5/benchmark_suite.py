"""Competitive benchmark suite (directive §17).

This module is deliberately split into two halves with different honesty
requirements:

1. **Define and score** — a fixed, versioned set of equivalent engineering tasks
   with objective scoring rules, and a function that scores one system's
   transcript against them. This half is deterministic and fully tested.

2. **Run** — execute a task on a *named external system*. No external system is
   reachable from this environment, and the directive forbids inventing results,
   so :func:`run_external_system` records a clearly-labelled ``not_run`` record
   rather than a fabricated score. A real comparison requires that system to be
   driven on the same tasks, model and hardware, and that is recorded as a
   prerequisite, not performed here.

No superiority claim is made anywhere. The suite exists so that a claim *could*
be established under equivalent conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

SUITE_VERSION = "1.0.0"

# Objective, checkable criteria per task. A criterion is met only when its
# evidence is present in the transcript; nothing is assumed.
_TASKS: tuple[dict[str, Any], ...] = (
    {
        "id": "webapp_crud",
        "title": "Build a working CRUD web application with tests",
        "checks": [
            ("plan_present", "A dependency-aware plan or task list was produced"),
            ("backend_files", "Backend source files exist"),
            ("frontend_files", "Frontend source files exist"),
            ("tests_written", "Automated tests were written"),
            ("tests_run", "The test suite was executed"),
            ("tests_pass", "The executed tests passed"),
            ("build_ok", "The application builds without error"),
            ("runs", "The application was started or its build output served"),
        ],
    },
    {
        "id": "api_service",
        "title": "Build a documented REST API service with tests",
        "checks": [
            ("plan_present", "A dependency-aware plan or task list was produced"),
            ("endpoints", "API endpoints are implemented"),
            ("docs", "API documentation was produced"),
            ("tests_written", "Automated tests were written"),
            ("tests_run", "The test suite was executed"),
            ("tests_pass", "The executed tests passed"),
        ],
    },
    {
        "id": "bugfix",
        "title": "Diagnose and fix a failing test in an existing codebase",
        "checks": [
            ("root_cause", "A root cause was identified, not just a symptom"),
            ("patch", "A code change was made"),
            ("regression_test", "A regression test guards the fix"),
            ("tests_run", "The test suite was executed"),
            ("tests_pass", "The previously failing test now passes"),
        ],
    },
    {
        "id": "research_report",
        "title": "Produce a cited research report answering a technical question",
        "checks": [
            ("sources", "Sources are cited with URLs"),
            ("verified_split", "Verified findings are separated from hypotheses"),
            ("answers_question", "The report answers the question asked"),
            ("implementation_link", "The research leads to a decision or experiment"),
        ],
    },
    {
        "id": "simulation",
        "title": "Model a quantitative problem and run a simulation",
        "checks": [
            ("model", "A computational or mathematical model was produced"),
            ("executed", "The model was executed, not just written"),
            ("results", "Numeric results were reported"),
            ("uncertainty", "Uncertainty or limitations are stated"),
        ],
    },
)


@dataclass
class SystemResult:
    """One system's measured outcome on one suite task."""

    system: str
    task: str
    status: str  # "scored" | "not_run"
    checks: dict[str, bool] = field(default_factory=dict)
    passed: int = 0
    total: int = 0
    success: bool = False
    time_seconds: float | None = None
    cost_usd: float | None = None
    human_interventions: int | None = None
    notes: str = ""
    evidence: list[str] = field(default_factory=list)
    recorded_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "task": self.task,
            "status": self.status,
            "checks": self.checks,
            "passed": self.passed,
            "total": self.total,
            "success": self.success,
            "time_seconds": self.time_seconds,
            "cost_usd": self.cost_usd,
            "human_interventions": self.human_interventions,
            "notes": self.notes,
            "evidence": self.evidence,
            "recorded_at": self.recorded_at or datetime.now(timezone.utc).isoformat(),
        }


def list_tasks() -> list[dict[str, Any]]:
    """The fixed suite tasks and their criteria (no evidence, just the spec)."""
    return [
        {
            "id": t["id"],
            "title": t["title"],
            "criteria": [{"key": k, "description": d} for k, d in t["checks"]],
        }
        for t in _TASKS
    ]


def task_ids() -> list[str]:
    return [t["id"] for t in _TASKS]


def _task(task_id: str) -> dict[str, Any]:
    for t in _TASKS:
        if t["id"] == task_id:
            return t
    raise KeyError(task_id)


def score_transcript(
    *,
    system: str,
    task_id: str,
    evidence: dict[str, bool],
    time_seconds: float | None = None,
    cost_usd: float | None = None,
    human_interventions: int | None = None,
    notes: str = "",
) -> SystemResult:
    """Score one system on one task from externally supplied evidence.

    ``evidence`` maps a check key to whether that check is objectively satisfied.
    A check with no evidence is scored False, never assumed.
    """
    task = _task(task_id)
    checks: dict[str, bool] = {}
    for key, _desc in task["checks"]:
        checks[key] = bool(evidence.get(key, False))
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    return SystemResult(
        system=system,
        task=task_id,
        status="scored",
        checks=checks,
        passed=passed,
        total=total,
        # A task counts as solved only when every criterion is met.
        success=passed == total,
        time_seconds=time_seconds,
        cost_usd=cost_usd,
        human_interventions=human_interventions,
        notes=notes,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )


def run_external_system(
    *, system: str, task_id: str, reason: str | None = None
) -> SystemResult:
    """Record that an external system was **not** benchmarked here.

    This environment cannot drive Claude Code, Codex, Cursor, Devin, Factory or
    Antigravity under equivalent conditions, and fabricating a score is
    forbidden. The record is explicit so no aggregate can silently treat a
    missing result as a pass or a fail.
    """
    _task(task_id)  # validate the task id
    return SystemResult(
        system=system,
        task=task_id,
        status="not_run",
        notes=reason
        or (
            "Not run: requires driving this system on the same task, model and "
            "hardware. Fabricated results are forbidden, so none are recorded."
        ),
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )


def aggregate(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarise records per system without inventing missing numbers.

    Only ``scored`` records contribute to success rates; ``not_run`` records are
    counted separately so a system with no runs shows a null rate, not a zero.
    """
    by_system: dict[str, dict[str, Any]] = {}
    for record in records:
        system = record.get("system", "unknown")
        entry = by_system.setdefault(
            system,
            {
                "system": system,
                "tasks_scored": 0,
                "tasks_solved": 0,
                "tasks_not_run": 0,
                "criteria_passed": 0,
                "criteria_total": 0,
                "success_rate": None,
                "mean_time_seconds": None,
                "total_cost_usd": 0.0,
            },
        )
        if record.get("status") == "scored":
            entry["tasks_scored"] += 1
            entry["tasks_solved"] += 1 if record.get("success") else 0
            entry["criteria_passed"] += int(record.get("passed", 0))
            entry["criteria_total"] += int(record.get("total", 0))
            if record.get("cost_usd") is not None:
                entry["total_cost_usd"] += float(record["cost_usd"])
        else:
            entry["tasks_not_run"] += 1

    for entry in by_system.values():
        if entry["tasks_scored"]:
            entry["success_rate"] = round(entry["tasks_solved"] / entry["tasks_scored"], 4)
        entry["total_cost_usd"] = round(entry["total_cost_usd"], 6)
    return {
        "suite_version": SUITE_VERSION,
        "systems": sorted(by_system.values(), key=lambda e: e["system"]),
        "note": (
            "Only scored records count. A system with no scored task shows a null "
            "success rate; missing runs are never treated as failures or passes."
        ),
    }
