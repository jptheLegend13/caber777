"""Innovation-to-Prototype Engine.

Takes an unfamiliar technical idea and drives it through a real investigation
rather than producing generic advice:

    IDEA -> UNDERSTANDING -> RESEARCH -> EXISTING SOLUTIONS -> TECHNICAL GAP
         -> FEASIBILITY -> ALTERNATIVE APPROACHES -> HYPOTHESIS -> ARCHITECTURE
         -> PROTOTYPE -> TEST -> EVALUATE -> IMPROVE -> DOCUMENT

The engine never asserts that an idea works. It builds the strongest testable
prototype it can, runs it, and reports what the run actually showed, what
remains a hypothesis and what could not be tested. A prototype that fails its
own experiment is a valid, informative result.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from level5.execution import ComputationResult, run_python_script
from level5.intelligence.research import ResearchEngine
from level5.llm.client import LLMClient, get_llm_client
from level5.models import Project, ProjectStatus

logger = logging.getLogger("level5.intelligence.innovation")


@dataclass
class InnovationReport:
    idea: str
    status: str = "completed"  # completed | partial | failed
    understanding: str = ""
    prior_art: list[str] = field(default_factory=list)
    technical_gap: str = ""
    feasibility: str = "unknown"  # feasible | uncertain | infeasible | unknown
    alternatives: list[str] = field(default_factory=list)
    hypothesis: str = ""
    architecture: str = ""
    prototype_description: str = ""
    prototype: ComputationResult | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    confidence: str = "low"

    def as_dict(self) -> dict[str, Any]:
        return {
            "idea": self.idea,
            "status": self.status,
            "understanding": self.understanding,
            "prior_art": self.prior_art,
            "technical_gap": self.technical_gap,
            "feasibility": self.feasibility,
            "alternatives": self.alternatives,
            "hypothesis": self.hypothesis,
            "architecture": self.architecture,
            "prototype_description": self.prototype_description,
            "prototype": (
                {
                    "succeeded": self.prototype.succeeded,
                    "exit_code": self.prototype.exit_code,
                    "timed_out": self.prototype.timed_out,
                    "duration_s": self.prototype.duration_s,
                    "stdout": self.prototype.stdout[-4000:],
                    "stderr": self.prototype.stderr[-2000:],
                    "parsed": self.prototype.parsed,
                    "files": self.prototype.files,
                }
                if self.prototype is not None
                else None
            ),
            "evidence": self.evidence,
            "findings": self.findings,
            "limitations": self.limitations,
            "next_steps": self.next_steps,
            "confidence": self.confidence,
        }


_FRAME_SYSTEM = """You are the innovation research intelligence of LEVEL 5.

A user proposes a technical idea. Investigate it as a researcher would - never
assume it works and never reject it for being unfamiliar. Produce JSON with
exactly these keys:
{
  "understanding": string,            // what the invention actually is
  "prior_art_queries": [string],      // searches to find similar systems
  "technical_gap": string,            // what is genuinely new or unproven
  "feasibility": "feasible"|"uncertain"|"infeasible",
  "alternatives": [string],           // alternative architectures worth testing
  "hypothesis": string,               // a single falsifiable claim
  "architecture": string,             // proposed architecture
  "prototype_description": string,    // what the prototype will build and measure
  "evaluation_plan": string           // how the run decides pass or fail
}"""

_PROTOTYPE_SYSTEM = """You are the innovation prototype engineer of LEVEL 5.

Write a single self-contained Python 3 program (standard library only) that
tests the stated hypothesis. Requirements:
- It must print a single JSON object as its LAST line.
- The JSON must include: "hypothesis", "metric", "result", "supports_hypothesis"
  (boolean), and "notes".
- It must run in under 30 seconds and must not use the network.
- It must compute a real measurement, not assert a conclusion.
Respond with JSON: {"prototype_code": string, "prototype_description": string}"""

_EVALUATE_SYSTEM = """You are the evaluation intelligence of LEVEL 5.

Judge what the executed prototype actually demonstrated. Never overstate
confidence; a prototype that did not support its hypothesis is a real result.
Respond with JSON:
{
  "findings": [string],
  "limitations": [string],
  "next_steps": [string],
  "feasibility": "feasible"|"uncertain"|"infeasible",
  "confidence": "low"|"medium"|"high"
}"""


class InnovationEngine:
    """Researches an unfamiliar idea and builds a tested prototype."""

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        research: ResearchEngine | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.llm = llm or get_llm_client()
        self.research = research or ResearchEngine(llm=self.llm)
        self.timeout = timeout

    async def investigate(
        self, idea: str, *, workspace: Path, research: bool = True
    ) -> InnovationReport:
        report = InnovationReport(idea=idea)

        frame = await self._frame(idea)
        report.understanding = str(frame.get("understanding", ""))
        report.technical_gap = str(frame.get("technical_gap", ""))
        report.feasibility = str(frame.get("feasibility", "uncertain"))
        report.alternatives = [str(a) for a in (frame.get("alternatives") or [])]
        report.hypothesis = str(frame.get("hypothesis", ""))
        report.architecture = str(frame.get("architecture", ""))
        report.prototype_description = str(frame.get("prototype_description", ""))

        if research and frame.get("prior_art_queries"):
            queries = [str(q) for q in frame["prior_art_queries"]][:3]
            reports = await self.research.investigate_many(queries)
            report.prior_art = [r.summary for r in reports if r.summary]
            report.evidence = [
                {
                    "question": r.question,
                    "summary": r.summary,
                    "sources": [
                        {"title": s.title, "url": s.url, "kind": s.kind.value}
                        for s in r.sources
                    ],
                }
                for r in reports
            ]

        design = await self._design(idea, report, frame)
        code = design.get("prototype_code")
        if design.get("prototype_description"):
            report.prototype_description = str(design["prototype_description"])

        if code:
            workspace.mkdir(parents=True, exist_ok=True)
            report.prototype = await run_python_script(
                str(code),
                workspace,
                timeout=self.timeout,
                subdir="prototype",
                filename="prototype.py",
            )
            if not report.prototype.succeeded:
                repaired = await self._repair(str(code), report.prototype, report.hypothesis)
                if repaired:
                    report.prototype = await run_python_script(
                        repaired,
                        workspace,
                        timeout=self.timeout,
                        subdir="prototype",
                        filename="prototype.py",
                    )

        evaluation = await self._evaluate(report)
        report.findings = [str(f) for f in (evaluation.get("findings") or [])]
        report.limitations = [str(l) for l in (evaluation.get("limitations") or [])]
        report.next_steps = [str(s) for s in (evaluation.get("next_steps") or [])]
        if evaluation.get("feasibility"):
            report.feasibility = str(evaluation["feasibility"])
        report.confidence = str(evaluation.get("confidence", "low"))
        if report.prototype is None:
            report.status = "partial"
        return report

    async def _frame(self, idea: str) -> dict[str, Any]:
        data, _ = await self.llm.chat_json(
            [
                {"role": "system", "content": _FRAME_SYSTEM},
                {"role": "user", "content": f"IDEA: {idea}"},
            ],
            temperature=0.3,
            max_tokens=3000,
        )
        return data

    async def _design(
        self, idea: str, report: InnovationReport, frame: dict[str, Any]
    ) -> dict[str, Any]:
        user = (
            f"IDEA: {idea}\nUNDERSTANDING: {report.understanding}\n"
            f"HYPOTHESIS: {report.hypothesis}\nARCHITECTURE: {report.architecture}\n"
            f"EVALUATION PLAN: {frame.get('evaluation_plan', '')}\n\n"
            "Write the prototype that measures the hypothesis."
        )
        try:
            data, _ = await self.llm.chat_json(
                [
                    {"role": "system", "content": _PROTOTYPE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=4000,
            )
        except Exception as exc:  # noqa: BLE001 - prototype is best-effort
            logger.warning("prototype design failed: %s", exc)
            return {}
        return data

    async def _repair(
        self, code: str, result: ComputationResult, hypothesis: str
    ) -> str | None:
        user = (
            f"HYPOTHESIS: {hypothesis}\n\nBROKEN PROTOTYPE:\n{code}\n\n"
            f"ERROR (exit {result.exit_code}):\n{result.stderr[-1500:]}"
        )
        try:
            data, _ = await self.llm.chat_json(
                [
                    {"role": "system", "content": _PROTOTYPE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=4000,
            )
        except Exception as exc:  # noqa: BLE001 - repair is best-effort
            logger.warning("prototype repair failed: %s", exc)
            return None
        code = data.get("prototype_code")
        return str(code) if code else None

    async def _evaluate(self, report: InnovationReport) -> dict[str, Any]:
        proto = report.prototype
        prototype_text = "NO PROTOTYPE RUN"
        if proto is not None:
            prototype_text = (
                f"succeeded={proto.succeeded} exit={proto.exit_code}\n"
                f"stdout:\n{proto.stdout[-3000:]}\nstderr:\n{proto.stderr[-1500:]}"
            )
        user = (
            f"IDEA: {report.idea}\nHYPOTHESIS: {report.hypothesis}\n"
            f"TECHNICAL GAP: {report.technical_gap}\n\nPROTOTYPE RUN:\n{prototype_text}\n\n"
            f"EVIDENCE:\n{json.dumps(report.evidence)[:2500]}"
        )
        try:
            data, _ = await self.llm.chat_json(
                [
                    {"role": "system", "content": _EVALUATE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=2500,
            )
        except Exception as exc:  # noqa: BLE001 - evaluation must not crash the run
            logger.warning("innovation evaluation failed: %s", exc)
            return {
                "findings": [],
                "limitations": [f"Evaluation model call failed: {exc}"],
                "next_steps": [],
                "confidence": "low",
            }
        return data


async def innovate_project(project: Project, *, research: bool = True) -> Project:
    """Run the innovation pipeline for a project and attach the report."""
    from level5.models import Artifact

    engine = InnovationEngine()
    workspace = Path(project.workspace_path)
    project.status = ProjectStatus.RESEARCHING
    project.log("phase", "Innovation pipeline started", phase="innovation")

    report = await engine.investigate(
        project.original_request, workspace=workspace, research=research
    )
    out_path = workspace / "innovation.json"
    out_path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")

    prototype_files = report.prototype.files if report.prototype else []
    project.artifacts = [
        Artifact(
            name="innovation.json",
            kind="report",
            path="innovation.json",
            description="Structured innovation investigation with prototype results",
        ),
    ]
    for relative in prototype_files:
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
        f"Innovation investigated: feasibility={report.feasibility}",
        status=report.status,
        confidence=report.confidence,
    )
    project.status = ProjectStatus.DELIVERED if report.status == "completed" else ProjectStatus.FAILED
    project.snapshot_workspace("innovation", note=report.hypothesis)
    return project
