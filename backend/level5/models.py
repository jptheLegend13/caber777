"""Structured domain model for LEVEL 5.

A project is represented as a :class:`Project` holding a :class:`Specification`
plus a task graph, research records, artifacts, tests and version history.
This structure - not a chat transcript - is the source of truth for project
state, and it is what makes work resumable across restarts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class ProjectDomain(str, Enum):
    """Technical domain of a project."""

    WEB_APP = "web_app"
    MOBILE_APP = "mobile_app"
    DESKTOP_APP = "desktop_app"
    ENTERPRISE_SOFTWARE = "enterprise_software"
    BACKEND_API = "backend_api"
    AI_APPLICATION = "ai_application"
    AI_AGENT = "ai_agent"
    MULTI_AGENT_SYSTEM = "multi_agent_system"
    DATA_SYSTEM = "data_system"
    CLOUD_DEVOPS = "cloud_devops"
    RESEARCH = "research"
    SIMULATION = "simulation"
    ARCHITECTURE_3D = "architecture_3d"
    DESIGN_SYSTEM = "design_system"
    GENERAL = "general"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    RESEARCHING = "researching"
    EXECUTING = "executing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    REPAIRING = "repairing"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class EvidenceKind(str, Enum):
    """Classification required for every research finding."""

    VERIFIED = "verified"
    PUBLISHED = "published"
    EXPERIMENTAL = "experimental"
    ASSUMPTION = "assumption"
    HYPOTHESIS = "hypothesis"
    UNSUPPORTED = "unsupported"


class CABERModule(str, Enum):
    """The three CABER intelligences plus shared platform work."""

    APPLICATION = "A"  # Application Creation Intelligence
    PROBLEM_SOLVING = "B"  # Problem-Solving Intelligence
    BUILDING = "C"  # Building Creation Intelligence
    PLATFORM = "P"  # Shared platform / infrastructure


# --------------------------------------------------------------------------- #
# Requirements & specification
# --------------------------------------------------------------------------- #
class Requirement(BaseModel):
    """A single, traceable requirement.

    ``origin`` keeps user-supplied requirements distinct from decisions the
    system inferred, which the directive requires explicitly.
    """

    id: str = Field(default_factory=lambda: _id("req"))
    text: str
    origin: Literal["user", "inferred"] = "user"
    category: str = "functional"
    priority: Literal["must", "should", "could"] = "must"
    acceptance_criteria: list[str] = Field(default_factory=list)
    satisfied_by: list[str] = Field(default_factory=list)  # task ids


class Constraint(BaseModel):
    id: str = Field(default_factory=lambda: _id("con"))
    text: str
    kind: Literal["technical", "budget", "time", "legal", "other"] = "technical"
    origin: Literal["user", "inferred"] = "user"


class AcceptanceCriterion(BaseModel):
    id: str = Field(default_factory=lambda: _id("ac"))
    statement: str
    verification_method: str = "automated_test"
    satisfied: bool = False
    evidence: str | None = None


class Specification(BaseModel):
    """The structured project specification produced by Central Intelligence."""

    intent: str = ""
    deliverable: str = ""
    domain: ProjectDomain = ProjectDomain.GENERAL
    caber_module: CABERModule = CABERModule.PLATFORM
    summary: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    clarifications_needed: bool = False
    technology_choices: list[dict[str, Any]] = Field(default_factory=list)
    research_needed: bool = False
    research_questions: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_now)


# --------------------------------------------------------------------------- #
# Research
# --------------------------------------------------------------------------- #
class Source(BaseModel):
    """A retrieved source with provenance."""

    id: str = Field(default_factory=lambda: _id("src"))
    url: str = ""
    title: str = ""
    publisher: str = ""
    published_date: str | None = None
    retrieved_at: datetime = Field(default_factory=_now)
    finding: str = ""
    kind: EvidenceKind = EvidenceKind.PUBLISHED
    reliability: Literal["high", "medium", "low"] = "medium"


class ResearchReport(BaseModel):
    id: str = Field(default_factory=lambda: _id("res"))
    question: str
    status: Literal["completed", "partial", "failed"] = "completed"
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    method: str = "web_search"
    created_at: datetime = Field(default_factory=_now)


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #
class Task(BaseModel):
    """A unit of work in the engineering task graph."""

    id: str = Field(default_factory=lambda: _id("task"))
    title: str
    objective: str = ""
    agent_role: str = "software_engineer"
    dependencies: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    phase: str = "execution"
    evidence: list[str] = Field(default_factory=list)
    error: str | None = None
    attempts: int = 0
    max_attempts: int = 2
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # OpenHands execution linkage
    conversation_id: str | None = None
    worktree: str | None = None


class TaskGraph(BaseModel):
    tasks: list[Task] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_now)

    def by_id(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def ready(self) -> list[Task]:
        """Tasks whose dependencies have all succeeded."""
        done = {t.id for t in self.tasks if t.status == TaskStatus.SUCCEEDED}
        ready: list[Task] = []
        for task in self.tasks:
            if task.status not in (TaskStatus.PENDING, TaskStatus.READY):
                continue
            if all(dep in done for dep in task.dependencies):
                ready.append(task)
        return ready


# --------------------------------------------------------------------------- #
# Artifacts, tests, events
# --------------------------------------------------------------------------- #
class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: _id("art"))
    name: str
    kind: Literal[
        "file", "directory", "document", "report", "preview", "model3d", "test_result"
    ] = "file"
    path: str = ""
    size_bytes: int = 0
    created_by_task: str | None = None
    description: str = ""
    created_at: datetime = Field(default_factory=_now)


class TestResult(BaseModel):
    id: str = Field(default_factory=lambda: _id("test"))
    suite: str
    name: str
    status: Literal["passed", "failed", "error", "skipped"] = "passed"
    duration_ms: float = 0.0
    message: str = ""
    task_id: str | None = None
    created_at: datetime = Field(default_factory=_now)


class ProjectEvent(BaseModel):
    """Append-only project log: the audit trail and activity feed."""

    id: str = Field(default_factory=lambda: _id("ev"))
    at: datetime = Field(default_factory=_now)
    kind: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class VersionSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: _id("ver"))
    label: str
    created_at: datetime = Field(default_factory=_now)
    status: ProjectStatus = ProjectStatus.DRAFT
    files: list[str] = Field(default_factory=list)
    note: str = ""


# --------------------------------------------------------------------------- #
# Project
# --------------------------------------------------------------------------- #
class Project(BaseModel):
    id: str = Field(default_factory=lambda: _id("proj"))
    name: str
    original_request: str = ""
    status: ProjectStatus = ProjectStatus.DRAFT
    specification: Specification = Field(default_factory=Specification)
    task_graph: TaskGraph = Field(default_factory=TaskGraph)
    research: list[ResearchReport] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    tests: list[TestResult] = Field(default_factory=list)
    events: list[ProjectEvent] = Field(default_factory=list)
    versions: list[VersionSnapshot] = Field(default_factory=list)
    workspace_path: str = ""
    conversation_ids: list[str] = Field(default_factory=list)
    preview_url: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def log(self, kind: str, message: str, **data: Any) -> ProjectEvent:
        event = ProjectEvent(kind=kind, message=message, data=data)
        self.events.append(event)
        self.updated_at = _now()
        return event

    def snapshot(self, label: str, note: str = "") -> VersionSnapshot:
        version = VersionSnapshot(
            label=label,
            status=self.status,
            files=[a.path for a in self.artifacts if a.path],
            note=note,
        )
        self.versions.append(version)
        return version
