"""REST + SSE routes for LEVEL 5."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from level5.agents.registry import all_roles, get_role, roles_by_discipline
from level5.caber.service import CABERBuildingService
from level5.config import get_settings
from level5.events import get_event_bus
from level5.intelligence.innovation import InnovationEngine
from level5.intelligence.problem_solving import ProblemSolver
from level5.llm.client import get_llm_client
from level5.models import (
    Attachment,
    CABERModule,
    Project,
    ProjectDomain,
    ProjectStatus,
)
from level5.orchestrator import Orchestrator
from level5.runtime.agent_server import get_agent_client
from level5.storage.store import get_store

logger = logging.getLogger("level5.api.routes")
router = APIRouter()

_orchestrator = Orchestrator()
_caber = CABERBuildingService()
_background: dict[str, asyncio.Task] = {}


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class CreateProjectRequest(BaseModel):
    request: str = Field(min_length=3)
    name: str | None = None
    auto_start: bool = True
    research: bool | None = None


class FollowUpRequest(BaseModel):
    message: str = Field(min_length=1)
    run: bool = True


class SolveRequest(BaseModel):
    problem: str = Field(min_length=3)
    research: bool = True
    name: str | None = None


class BuildingRequest(BaseModel):
    request: str = Field(min_length=3)
    name: str | None = None


class InnovateRequest(BaseModel):
    idea: str = Field(min_length=3)
    research: bool = True
    name: str | None = None


class SuiteRecordRequest(BaseModel):
    """One system's measured outcome on one suite task."""

    system: str = Field(min_length=1)
    task: str = Field(min_length=1)
    evidence: dict[str, bool] = Field(default_factory=dict)
    time_seconds: float | None = None
    cost_usd: float | None = None
    human_interventions: int | None = None
    notes: str = ""


class SuiteNotRunRequest(BaseModel):
    system: str = Field(min_length=1)
    task: str = Field(min_length=1)
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Health & metadata
# --------------------------------------------------------------------------- #
@router.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    server = await get_agent_client().healthy()
    gateway_ok = await get_llm_client().probe_gateway()
    transport = (settings.llm_transport or "auto").lower()
    # "auto" stays healthy when the gateway is down because it falls back to
    # ask_agent; an explicit "gateway" transport does not.
    llm_ready = gateway_ok or transport in ("auto", "ask_agent")
    return {
        "status": "ok" if llm_ready else "degraded",
        "service": "LEVEL 5",
        "version": "0.1.0",
        "llm": {
            "transport": transport,
            "gateway_models_available": gateway_ok,
            "ready": llm_ready,
        },
        "agent_server": {
            "url": settings.agent_server_url,
            "reachable": bool(server),
            "version": (server or {}).get("version"),
            "sdk_version": (server or {}).get("sdk_version"),
        },
        "caber_modules": [m.value for m in CABERModule],
    }


@router.get("/agents")
async def list_agents() -> dict[str, Any]:
    grouped = roles_by_discipline()
    return {
        "count": sum(len(v) for v in grouped.values()),
        "disciplines": {
            discipline: [r.as_dict() for r in roles]
            for discipline, roles in grouped.items()
        },
    }


@router.get("/agents/{name}")
async def get_agent(name: str) -> dict[str, Any]:
    role = get_role(name)
    return role.as_dict()


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
@router.get("/projects")
async def list_projects(
    limit: int = Query(100, ge=1, le=500), status: str | None = None
) -> dict[str, Any]:
    items = await get_store().list(limit=limit, status=status)
    return {"items": items, "count": len(items)}


@router.post("/projects", status_code=201)
async def create_project(
    body: CreateProjectRequest, background: BackgroundTasks
) -> dict[str, Any]:
    project = Project(name=body.name or _title_from(body.request), original_request=body.request)
    settings = get_settings()
    project.workspace_path = str(settings.projects_dir / project.id)
    Path(project.workspace_path).mkdir(parents=True, exist_ok=True)
    project.log("created", "Project created")
    await get_store().save(project)

    if body.auto_start:
        _launch(project.id, _run_full_pipeline(project.id, research=body.research))
    return {"project": json.loads(project.model_dump_json())}


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    project = await _load(project_id)
    return {"project": json.loads(project.model_dump_json())}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    deleted = await get_store().delete(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="project not found")
    return {"deleted": True, "id": project_id}


@router.post("/projects/{project_id}/run")
async def run_project(
    project_id: str, research: bool | None = None
) -> dict[str, Any]:
    project = await _load(project_id)
    if project.id in _background and not _background[project.id].done():
        raise HTTPException(status_code=409, detail="project is already running")
    _launch(project.id, _run_full_pipeline(project.id, research=research))
    return {"started": True, "project_id": project.id}


@router.post("/projects/{project_id}/plan")
async def plan_project(project_id: str) -> dict[str, Any]:
    project = await _load(project_id)
    project = await _orchestrator.understand_and_plan(project)
    return {"project": json.loads(project.model_dump_json())}


@router.post("/projects/{project_id}/cancel")
async def cancel_project(project_id: str) -> dict[str, Any]:
    task = _background.get(project_id)
    if task and not task.done():
        task.cancel()
    project = await _load(project_id)
    project.status = ProjectStatus.CANCELLED
    project.log("cancelled", "Cancellation requested")
    await get_store().save(project)
    return {"cancelled": True}


@router.get("/projects/{project_id}/events")
async def project_events(project_id: str) -> dict[str, Any]:
    project = await _load(project_id)
    return {"items": [json.loads(e.model_dump_json()) for e in project.events]}


@router.get("/projects/{project_id}/stream")
async def stream_project(project_id: str) -> StreamingResponse:
    bus = get_event_bus()

    async def generator():
        project = await get_store().get(project_id)
        if project:
            yield _sse({"kind": "snapshot", "project": json.loads(project.model_dump_json())})
        async for event in bus.subscribe(project_id):
            yield _sse(event)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/projects/{project_id}/files")
async def project_files(project_id: str, path: str = "") -> dict[str, Any]:
    project = await _load(project_id)
    root = Path(project.workspace_path).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=400, detail="path escapes workspace")
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if target.is_file():
        return {
            "type": "file",
            "path": str(target.relative_to(root)),
            "size": target.stat().st_size,
            "content": _read_text(target),
        }
    entries = []
    for child in sorted(target.iterdir()):
        if child.name.startswith("."):
            continue
        entries.append(
            {
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else 0,
            }
        )
    return {"type": "directory", "path": str(target.relative_to(root)), "entries": entries}


@router.get("/projects/{project_id}/report")
async def project_report(project_id: str) -> dict[str, Any]:
    project = await _load(project_id)
    report = Path(project.workspace_path) / "LEVEL5_REPORT.md"
    if not report.exists():
        raise HTTPException(status_code=404, detail="report not generated yet")
    return {"report": report.read_text(encoding="utf-8")}


@router.get("/projects/{project_id}/attachments")
async def list_attachments(project_id: str) -> dict[str, Any]:
    project = await _load(project_id)
    return {"items": [a.model_dump() for a in project.attachments]}


@router.post("/projects/{project_id}/attachments", status_code=201)
async def upload_attachment(
    project_id: str, file: UploadFile = File(...)
) -> dict[str, Any]:
    """Accept a file, image or reference document for a project.

    The bytes are written under the project workspace in an ``attachments``
    directory so an agent conversation can read them. Only metadata plus a short
    text excerpt is kept in the project record, and the stored filename is
    sanitised so an upload cannot escape the attachments directory.
    """
    project = await _load(project_id)
    settings = get_settings()
    safe_name = Path(file.filename or "upload").name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid filename")
    data = await file.read()
    if len(data) > settings.max_attachment_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"attachment exceeds {settings.max_attachment_bytes} bytes",
        )
    target_dir = Path(project.workspace_path or settings.projects_dir / project.id)
    target_dir = target_dir / "attachments"
    target_dir.mkdir(parents=True, exist_ok=True)
    attachment = Attachment(
        filename=safe_name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
    )
    target = target_dir / f"{attachment.id}_{safe_name}"
    target.write_bytes(data)
    attachment.path = str(target)
    attachment.text_excerpt = _extract_text_excerpt(target, attachment.content_type)
    project.attachments.append(attachment)
    project.log(
        "attachment", f"Attached {safe_name}", attachment_id=attachment.id
    )
    await get_store().save(project)
    return {"attachment": attachment.model_dump(), "project_id": project.id}


@router.delete("/projects/{project_id}/attachments/{attachment_id}")
async def delete_attachment(project_id: str, attachment_id: str) -> dict[str, Any]:
    project = await _load(project_id)
    remaining: list[Attachment] = []
    removed: Attachment | None = None
    for attachment in project.attachments:
        if attachment.id == attachment_id:
            removed = attachment
        else:
            remaining.append(attachment)
    if removed is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    if removed.path:
        try:
            Path(removed.path).unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best effort
            logger.warning("could not remove attachment file %s", removed.path)
    project.attachments = remaining
    await get_store().save(project)
    return {"deleted": True, "id": attachment_id}


@router.post("/projects/{project_id}/follow-up")
async def follow_up(project_id: str, body: FollowUpRequest) -> dict[str, Any]:
    """Send an instruction to the project's most recent agent conversation."""
    project = await _load(project_id)
    if not project.conversation_ids:
        raise HTTPException(status_code=409, detail="no agent conversation to continue")
    conversation_id = project.conversation_ids[-1]
    await get_agent_client().send_message(conversation_id, body.message, run=body.run)
    project.log("follow_up", body.message[:200])
    await get_store().save(project)
    return {"sent": True, "conversation_id": conversation_id}


# --------------------------------------------------------------------------- #
# Problem solving (CABER Intelligence B)
# --------------------------------------------------------------------------- #
@router.post("/solve", status_code=201)
async def solve(body: SolveRequest) -> dict[str, Any]:
    settings = get_settings()
    project = Project(
        name=body.name or _title_from(body.problem),
        original_request=body.problem,
    )
    project.specification.domain = ProjectDomain.RESEARCH
    project.specification.caber_module = CABERModule.PROBLEM_SOLVING
    project.specification.intent = body.problem[:200]
    project.workspace_path = str(settings.projects_dir / project.id)
    Path(project.workspace_path).mkdir(parents=True, exist_ok=True)
    await get_store().save(project)

    solver = ProblemSolver()
    project.status = ProjectStatus.RESEARCHING
    report = await solver.solve(
        body.problem, workspace=Path(project.workspace_path), research=body.research
    )
    out = Path(project.workspace_path) / "solution.json"
    out.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    from level5.models import Artifact

    project.artifacts = [
        Artifact(
            name="solution.json",
            kind="report",
            path="solution.json",
            description="Solution report with computation, evidence and limitations",
        )
    ]
    project.log(
        "solution",
        f"Solution produced (confidence: {report.confidence})",
        computation_ok=bool(report.computation and report.computation.succeeded),
    )
    project.status = ProjectStatus.DELIVERED
    await get_store().save(project)
    return {
        "project_id": project.id,
        "report": report.as_dict(),
    }


# --------------------------------------------------------------------------- #
# Innovation-to-prototype (new technology development, directive §13)
# --------------------------------------------------------------------------- #
@router.post("/innovate", status_code=201)
async def innovate(body: InnovateRequest) -> dict[str, Any]:
    settings = get_settings()
    project = Project(
        name=body.name or _title_from(body.idea),
        original_request=body.idea,
    )
    project.specification.domain = ProjectDomain.RESEARCH
    project.specification.caber_module = CABERModule.PROBLEM_SOLVING
    project.specification.intent = body.idea[:200]
    project.workspace_path = str(settings.projects_dir / project.id)
    Path(project.workspace_path).mkdir(parents=True, exist_ok=True)
    await get_store().save(project)

    engine = InnovationEngine()
    report = await engine.investigate(
        body.idea, workspace=Path(project.workspace_path), research=body.research
    )
    out = Path(project.workspace_path) / "innovation.json"
    out.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    from level5.models import Artifact

    project.artifacts = [
        Artifact(
            name="innovation.json",
            kind="report",
            path="innovation.json",
            description="Innovation investigation with prior art, prototype and evaluation",
        )
    ]
    for relative in (report.prototype.files if report.prototype else []):
        project.artifacts.append(
            Artifact(
                name=Path(relative).name,
                kind="prototype",
                path=f"prototype/{relative}",
                description="Prototype artifact produced by the investigation run",
            )
        )
    project.log(
        "innovation",
        f"Innovation investigated (feasibility: {report.feasibility})",
        prototype_ok=bool(report.prototype and report.prototype.succeeded),
        confidence=report.confidence,
    )
    project.status = (
        ProjectStatus.DELIVERED if report.status == "completed" else ProjectStatus.FAILED
    )
    await get_store().save(project)
    return {
        "project_id": project.id,
        "report": report.as_dict(),
        "report_url": f"/api/projects/{project.id}",
    }


# --------------------------------------------------------------------------- #
# CABER building creation (Intelligence C)
# --------------------------------------------------------------------------- #
@router.post("/caber/buildings", status_code=201)
async def create_building(body: BuildingRequest) -> dict[str, Any]:
    project = await _caber.create_project(body.request, name=body.name)
    project = await _caber.build(project, preferences=body.preferences)
    return {
        "project_id": project.id,
        "title": project.name,
        "validation": (_caber.report(project.id).as_dict() if _caber.report(project.id) else None),
        "scene_url": f"/api/projects/{project.id}/caber/scene",
        "viewer_url": f"/api/projects/{project.id}/caber/viewer",
        "spec_url": f"/api/projects/{project.id}/caber/spec",
    }


@router.get("/projects/{project_id}/caber/spec")
async def caber_spec(project_id: str) -> dict[str, Any]:
    spec = _caber.spec(project_id) or await _load_spec(project_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="no building spec for this project")
    return {"spec": json.loads(spec.model_dump_json())}


@router.get("/projects/{project_id}/caber/scene")
async def caber_scene(project_id: str) -> JSONResponse:
    scene = _caber.scene(project_id) or await _load_scene(project_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="no scene for this project")
    return JSONResponse(scene)


@router.get("/projects/{project_id}/caber/validation")
async def caber_validation(project_id: str) -> dict[str, Any]:
    report = _caber.report(project_id) or await _load_validation(project_id)
    if report is None:
        raise HTTPException(status_code=404, detail="no validation for this project")
    return report if isinstance(report, dict) else report.as_dict()


@router.get("/projects/{project_id}/preview/status")
async def preview_status(project_id: str) -> dict[str, Any]:
    """Whether a built web app is available to preview, and its build state."""
    from level5.preview import detect_web_app, static_preview_dir

    project = await _load(project_id)
    dist = static_preview_dir(project.workspace_path)
    app = detect_web_app(project.workspace_path)
    build_tests = [t for t in project.tests if t.suite == "build"]
    return {
        "available": dist is not None,
        "preview_url": f"/api/projects/{project.id}/preview/" if dist else None,
        "package_dir": str(app.package_dir) if app else None,
        "build": build_tests[-1].model_dump() if build_tests else None,
    }


@router.get("/projects/{project_id}/preview/{asset_path:path}")
async def preview_asset(project_id: str, asset_path: str = "") -> Any:
    """Serve the built static app for the browser preview.

    Only files inside the build output directory are served; path traversal is
    rejected. Unknown routes fall back to index.html so client-side routing in
    a single-page app works in the preview.
    """
    from level5.preview import static_preview_dir

    project = await _load(project_id)
    dist = static_preview_dir(project.workspace_path)
    if dist is None:
        raise HTTPException(status_code=404, detail="no built web app to preview")

    root = dist.resolve()
    target = (root / asset_path).resolve() if asset_path else root
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="path escapes preview root")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        fallback = root / "index.html"
        if fallback.is_file():
            return FileResponse(fallback, media_type="text/html")
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(target)


@router.get("/projects/{project_id}/caber/viewer")
async def caber_viewer(project_id: str) -> FileResponse:
    project = await _load(project_id)
    viewer = Path(project.workspace_path) / "viewer.html"
    if not viewer.exists():
        raise HTTPException(status_code=404, detail="viewer not generated")
    return FileResponse(viewer, media_type="text/html")


# --------------------------------------------------------------------------- #
# Benchmark & improvement records
# --------------------------------------------------------------------------- #
@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    """Available model providers and their declared capabilities.

    Returns the *name* of each credential environment variable, never a value.
    """
    from level5.llm.providers import get_registry

    return get_registry().report()


@router.get("/benchmarks")
async def list_benchmarks(limit: int = 200) -> dict[str, Any]:
    items = await get_store().list_benchmarks(limit=limit)
    return {"items": items, "count": len(items)}


# --------------------------------------------------------------------------- #
# Competitive benchmark suite (directive §17)
# --------------------------------------------------------------------------- #
@router.get("/benchmarks/suite")
async def suite_definition() -> dict[str, Any]:
    """The fixed suite tasks and their objective criteria."""
    from level5.benchmark_suite import SUITE_VERSION, list_tasks

    return {"suite_version": SUITE_VERSION, "tasks": list_tasks()}


@router.get("/benchmarks/suite/results")
async def suite_results(suite: str | None = None) -> dict[str, Any]:
    """Recorded results aggregated per system, with missing runs never faked."""
    from level5.benchmark_suite import SUITE_VERSION, aggregate

    records = await get_store().list_suite_records(suite=suite)
    return {"suite_version": SUITE_VERSION, "records": records, "summary": aggregate(records)}


@router.post("/benchmarks/suite/records", status_code=201)
async def suite_record(body: SuiteRecordRequest) -> dict[str, Any]:
    """Score and store one system's outcome on one suite task.

    Only criteria with supplied evidence can pass; a criterion with no evidence
    is scored False. A task counts as solved only when every criterion passes.
    """
    from level5.benchmark_suite import SUITE_VERSION, score_transcript

    try:
        result = score_transcript(
            system=body.system,
            task_id=body.task,
            evidence=body.evidence,
            time_seconds=body.time_seconds,
            cost_usd=body.cost_usd,
            human_interventions=body.human_interventions,
            notes=body.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown suite task: {exc}") from exc
    record = {
        "id": f"suiteres_{SUITE_VERSION}_{body.system}_{body.task}".replace("/", "_"),
        "suite": SUITE_VERSION,
        **result.as_dict(),
    }
    await get_store().save_suite_record(record)
    return {"record": record}


@router.post("/benchmarks/suite/not-run", status_code=201)
async def suite_not_run(body: SuiteNotRunRequest) -> dict[str, Any]:
    """Record explicitly that a system was not benchmarked here.

    No fabricated score is ever produced for a system this environment cannot
    drive under equivalent conditions.
    """
    from level5.benchmark_suite import SUITE_VERSION, run_external_system

    try:
        result = run_external_system(
            system=body.system, task_id=body.task, reason=body.reason
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown suite task: {exc}") from exc
    record = {
        "id": f"suiteres_{SUITE_VERSION}_{body.system}_{body.task}".replace("/", "_"),
        "suite": SUITE_VERSION,
        **result.as_dict(),
    }
    await get_store().save_suite_record(record)
    return {"record": record}


@router.get("/improvements")
async def list_improvements(limit: int = 100) -> dict[str, Any]:
    items = await get_store().list_improvements(limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/improvements/analyse")
async def analyse_improvements(
    min_samples: int = 3, review: bool = True
) -> dict[str, Any]:
    """Detect measured weaknesses and draft screened proposals.

    With ``review`` (the default), a separate independent reviewer agent decides
    accept or reject for each proposal. Nothing is ever applied: acceptance
    authorises implementation in isolation behind its tests, never deployment.
    """
    from level5.self_improvement import SelfImprovementEngine

    engine = SelfImprovementEngine()
    weaknesses = await engine.detect_weaknesses(min_samples=min_samples)
    proposals = []
    for weakness in weaknesses:
        proposal = await engine.propose(weakness)
        if review:
            proposal = await engine.review(proposal, weaknesses=weaknesses)
        await engine.record(proposal)
        proposals.append(proposal.as_dict())
    return {
        "weaknesses": [w.as_dict() for w in weaknesses],
        "proposals": proposals,
        "reviewed": review,
        "note": (
            "Proposals are recorded for review only. Nothing is applied "
            "automatically, and proposals that weaken safety controls are rejected "
            "by a deterministic screen and by an independent reviewer."
        ),
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _launch(project_id: str, coro) -> None:
    task = asyncio.create_task(coro)
    _background[project_id] = task

    def _cleanup(_):
        _background.pop(project_id, None)

    task.add_done_callback(_cleanup)


async def _run_full_pipeline(project_id: str, research: bool | None) -> None:
    project = await get_store().get(project_id)
    if project is None:
        return
    try:
        # Resume an existing plan rather than replacing it. Re-planning here
        # would build a new task graph and discard every result already
        # recorded against the current one, so a restart would silently throw
        # away completed work instead of continuing it (Section 15).
        if project.task_graph.tasks:
            _orchestrator.prepare_resume(project)
            await _orchestrator.execute(project)
            return

        project = await _orchestrator.understand(project)
        module = project.specification.caber_module
        if module == CABERModule.BUILDING:
            # Building requests go to the dedicated 3D creation intelligence,
            # which performs its own architectural understanding and validation.
            from level5.caber.service import CABERBuildingService

            project = await CABERBuildingService().build(project)
            await get_store().save(project)
            return
        if module == CABERModule.PROBLEM_SOLVING and _looks_like_innovation(
            project.original_request, project.specification
        ):
            # A novel, untested idea is driven through the innovation pipeline
            # (prior art -> hypothesis -> prototype -> evaluation) rather than
            # a generic engineering task graph.
            from level5.intelligence.innovation import innovate_project

            project = await innovate_project(project, research=bool(research))
            await get_store().save(project)
            return

        await _orchestrator.run_research(project, do_research=research)
        await _orchestrator.plan(project)
        await _orchestrator.execute(project)
    except asyncio.CancelledError:
        project.status = ProjectStatus.CANCELLED
        project.log("cancelled", "Run cancelled")
        await get_store().save(project)
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        logger.exception("pipeline failed for %s", project_id)
        project.status = ProjectStatus.FAILED
        project.log("error", f"Pipeline failed: {exc}")
        await get_store().save(project)


_INNOVATION_TERMS = (
    "invent", "innovation", "novel", "new technology", "prior art", "prototype",
    "patent", "unproven", "never been", "new kind", "new type", "original idea",
)


def _looks_like_innovation(request: str, spec: Any) -> bool:
    """True when a problem-solving request is about a novel, untested idea."""
    text = f"{request} {spec.deliverable} {spec.intent}".lower()
    return any(term in text for term in _INNOVATION_TERMS)


async def _load(project_id: str) -> Project:
    project = await get_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


async def _load_scene(project_id: str) -> dict[str, Any] | None:
    project = await get_store().get(project_id)
    if project is None:
        return None
    path = Path(project.workspace_path) / "building.scene.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def _load_spec(project_id: str):
    from level5.caber.models import BuildingSpec

    project = await get_store().get(project_id)
    if project is None:
        return None
    path = Path(project.workspace_path) / "building.spec.json"
    if not path.exists():
        return None
    return BuildingSpec.model_validate_json(path.read_text(encoding="utf-8"))


async def _load_validation(project_id: str) -> dict[str, Any] | None:
    """Read a persisted validation report from disk.

    The in-memory CABER service is lost when the backend restarts, but the run
    wrote ``validation.json`` to the project workspace. Without this fallback a
    delivered building 404s on its validation after any restart.
    """
    project = await get_store().get(project_id)
    if project is None:
        return None
    path = Path(project.workspace_path) / "validation.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except (UnicodeDecodeError, OSError):
        return "<binary or unreadable file>"


def _title_from(text: str) -> str:
    return (text.strip().split("\n")[0][:70]) or "Untitled project"


_TEXT_CONTENT_HINTS = (
    "text/",
    "application/json",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
    "application/javascript",
    "application/typescript",
    "application/x-sh",
    "application/sql",
)


def _extract_text_excerpt(path: Path, content_type: str, limit: int = 20_000) -> str:
    """Return a short text sample of an attachment for request understanding.

    Only text-like content is read; images and binaries return an empty string so
    a large upload is never slurped into the project record.
    """
    looks_textual = content_type.startswith("text/") or any(
        hint in content_type for hint in _TEXT_CONTENT_HINTS
    )
    if not looks_textual:
        return ""
    try:
        raw = path.read_bytes()[: limit * 4]
        return raw.decode("utf-8", errors="replace")[:limit]
    except OSError:
        return ""
