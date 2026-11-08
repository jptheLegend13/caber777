"""REST + SSE routes for LEVEL 5."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from level5.agents.registry import all_roles, get_role, roles_by_discipline
from level5.caber.service import CABERBuildingService
from level5.config import get_settings
from level5.events import get_event_bus
from level5.intelligence.problem_solving import ProblemSolver
from level5.models import CABERModule, Project, ProjectDomain, ProjectStatus
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
    preferences: str = ""


# --------------------------------------------------------------------------- #
# Health & metadata
# --------------------------------------------------------------------------- #
@router.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    server = await get_agent_client().healthy()
    return {
        "status": "ok",
        "service": "LEVEL 5",
        "version": "0.1.0",
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
    report = _caber.report(project_id)
    if report is None:
        raise HTTPException(status_code=404, detail="no validation for this project")
    return report.as_dict()


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


@router.get("/improvements")
async def list_improvements(limit: int = 100) -> dict[str, Any]:
    items = await get_store().list_improvements(limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/improvements/analyse")
async def analyse_improvements(min_samples: int = 3) -> dict[str, Any]:
    """Detect measured weaknesses and draft screened proposals.

    This never applies a change. It records proposals for review.
    """
    from level5.self_improvement import SelfImprovementEngine

    engine = SelfImprovementEngine()
    weaknesses = await engine.detect_weaknesses(min_samples=min_samples)
    proposals = []
    for weakness in weaknesses:
        proposal = await engine.propose(weakness)
        await engine.record(proposal)
        proposals.append(proposal.as_dict())
    return {
        "weaknesses": [w.as_dict() for w in weaknesses],
        "proposals": proposals,
        "note": (
            "Proposals are recorded for review only. Nothing is applied "
            "automatically, and proposals that weaken safety controls are rejected."
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
        project = await _orchestrator.understand_and_plan(project, do_research=research)
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


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except (UnicodeDecodeError, OSError):
        return "<binary or unreadable file>"


def _title_from(text: str) -> str:
    return (text.strip().split("\n")[0][:70]) or "Untitled project"
