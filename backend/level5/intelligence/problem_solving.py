"""Problem-Solving Intelligence (CABER Intelligence B).

Understand a technical problem, gather evidence, build a computational model,
run it, analyse the results and report uncertainty. The point is that claims
are backed by executed computation and cited evidence - not by fluent prose.

Pipeline: UNDERSTAND -> RESEARCH -> MODEL -> SIMULATE -> ANALYSE -> VERIFY.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from level5.intelligence.research import ResearchEngine
from level5.llm.client import LLMClient, get_llm_client
from level5.models import Project, ProjectStatus

logger = logging.getLogger("level5.intelligence.problem_solving")


@dataclass
class ComputationResult:
    """Outcome of running a generated model script."""

    script: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    duration_s: float = 0.0
    parsed: dict[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class SolutionReport:
    problem: str
    restatement: str = ""
    approach: str = ""
    model_description: str = ""
    computation: ComputationResult | None = None
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confidence: str = "low"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "problem": self.problem,
            "restatement": self.restatement,
            "approach": self.approach,
            "model_description": self.model_description,
            "computation": {
                "succeeded": self.computation.succeeded if self.computation else False,
                "exit_code": self.computation.exit_code if self.computation else None,
                "stdout": (self.computation.stdout or "")[-4000:] if self.computation else "",
                "stderr": (self.computation.stderr or "")[-2000:] if self.computation else "",
                "duration_s": self.computation.duration_s if self.computation else None,
                "parsed": self.computation.parsed if self.computation else None,
            },
            "findings": self.findings,
            "limitations": self.limitations,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "hypotheses": self.hypotheses,
        }


class ProblemSolver:
    """Runs the full problem-solving pipeline for a question."""

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        research: ResearchEngine | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.llm = llm or get_llm_client()
        self.research = research or ResearchEngine(llm=self.llm)
        self.timeout = timeout

    async def solve(
        self, problem: str, *, workspace: Path, research: bool = True
    ) -> SolutionReport:
        report = SolutionReport(problem=problem)

        # 1. Restate and identify the model ------------------------------- #
        plan = await self._plan(problem, research)
        report.restatement = plan.get("restatement", "")
        report.approach = plan.get("approach", "")
        report.model_description = plan.get("model_description", "")
        report.hypotheses = [str(h) for h in (plan.get("hypotheses") or [])]

        # 2. Evidence ------------------------------------------------------ #
        if research and plan.get("research_queries"):
            queries = [str(q) for q in plan["research_queries"]][:3]
            reports = await self.research.investigate_many(queries)
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

        # 3. Computational model ------------------------------------------ #
        script = plan.get("model_code")
        if script:
            report.computation = await self._run_model(script, workspace)
            if not report.computation.succeeded:
                # One repair attempt informed by the actual error.
                repaired = await self._repair_model(script, report.computation, problem)
                if repaired:
                    report.computation = await self._run_model(repaired, workspace)

        # 4. Analyse ------------------------------------------------------- #
        analysis = await self._analyse(report)
        report.findings = [str(f) for f in (analysis.get("findings") or [])]
        report.limitations = [str(l) for l in (analysis.get("limitations") or [])]
        report.confidence = str(analysis.get("confidence", "low"))
        return report

    async def _plan(self, problem: str, research: bool) -> dict[str, Any]:
        system = (
            "You are the problem-solving intelligence of LEVEL 5. For the given "
            "technical or real-world problem:\n"
            "1. Restate it precisely.\n"
            "2. Choose a solution approach and state it.\n"
            "3. Build a computational model as a SINGLE self-contained Python 3 "
            "script using only the standard library plus numpy if needed. The "
            "script MUST print a JSON object to stdout with the key results, "
            "and must be deterministic (seed any randomness).\n"
            "4. List 1-3 research queries that would provide external evidence.\n"
            "5. List hypotheses to test.\n"
            "Never claim a result you have not computed. Respond as JSON: "
            '{"restatement": str, "approach": str, "model_description": str, '
            '"model_code": str, "research_queries": [str], "hypotheses": [str]}'
        )
        data, _ = await self.llm.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": problem},
            ],
            temperature=0.2,
            max_tokens=4000,
        )
        return data

    async def _repair_model(
        self, script: str, result: ComputationResult, problem: str
    ) -> str | None:
        system = (
            "The Python model script failed. Fix it. Return JSON "
            '{"model_code": str} with a corrected, self-contained script that '
            "prints a JSON result object to stdout."
        )
        user = (
            f"PROBLEM: {problem}\n\nSCRIPT:\n{script}\n\n"
            f"EXIT CODE: {result.exit_code}\nSTDERR:\n{result.stderr[-2000:]}"
        )
        try:
            data, _ = await self.llm.chat_json(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.1,
                max_tokens=4000,
            )
        except Exception as exc:  # noqa: BLE001 - repair is best-effort
            logger.warning("model repair failed: %s", exc)
            return None
        code = data.get("model_code")
        return str(code) if code else None

    async def _run_model(self, script: str, workspace: Path) -> ComputationResult:
        """Execute a generated model script in an isolated temp directory."""
        workspace.mkdir(parents=True, exist_ok=True)
        models_dir = workspace / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        script_path = models_dir / "model.py"
        script_path.write_text(script, encoding="utf-8")

        start = asyncio.get_event_loop().time()
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            cwd=str(models_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            stdout, stderr = await proc.communicate()
        duration = asyncio.get_event_loop().time() - start
        out_text = stdout.decode("utf-8", "replace")
        err_text = stderr.decode("utf-8", "replace")
        return ComputationResult(
            script=script,
            stdout=out_text,
            stderr=err_text,
            exit_code=proc.returncode if proc.returncode is not None else -1,
            timed_out=timed_out,
            duration_s=round(duration, 3),
            parsed=_parse_json_block(out_text),
        )

    async def _analyse(self, report: SolutionReport) -> dict[str, Any]:
        comp = report.computation
        computation_text = "NO COMPUTATION RUN"
        if comp is not None:
            computation_text = (
                f"succeeded={comp.succeeded} exit={comp.exit_code}\n"
                f"stdout:\n{comp.stdout[-3000:]}\nstderr:\n{comp.stderr[-1000:]}"
            )
        evidence_text = json.dumps(report.evidence)[:3000]
        system = (
            "You are the problem-solving intelligence of LEVEL 5. Analyse the "
            "computed results and evidence. Distinguish what the computation "
            "actually shows from what remains uncertain. Never overstate "
            "confidence. Respond as JSON: "
            '{"findings": [str], "limitations": [str], '
            '"confidence": "low"|"medium"|"high"}'
        )
        user = (
            f"PROBLEM: {report.problem}\nAPPROACH: {report.approach}\n"
            f"MODEL: {report.model_description}\n\nCOMPUTATION:\n{computation_text}\n\n"
            f"EVIDENCE:\n{evidence_text}"
        )
        data, _ = await self.llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=2500,
        )
        return data


def _parse_json_block(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def solve_project(project: Project, *, research: bool = True) -> Project:
    """Convenience wrapper used by the API to solve a research project."""
    solver = ProblemSolver()
    workspace = Path(project.workspace_path)
    project.status = ProjectStatus.RESEARCHING
    project.log("phase", "Problem-solving pipeline started", phase="research")
    report = await solver.solve(project.original_request, workspace=workspace, research=research)

    out_path = workspace / "solution.json"
    out_path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")

    from level5.models import Artifact, ProjectStatus as PS

    project.artifacts = [
        Artifact(name="solution.json", kind="report", path="solution.json",
                 description="Structured solution report with computation and evidence"),
    ]
    project.log(
        "solution",
        f"Solution produced (confidence: {report.confidence})",
        findings=len(report.findings),
        computation_ok=bool(report.computation and report.computation.succeeded),
    )
    project.status = PS.DELIVERED
    project.snapshot("solution", note=f"confidence={report.confidence}")
    await get_store_ref().save(project)
    return project


def get_store_ref():
    from level5.storage.store import get_store

    return get_store()
