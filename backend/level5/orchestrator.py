"""Engineering orchestrator.

Runs the full pipeline:

    REQUEST -> UNDERSTANDING -> RESEARCH -> SPECIFICATION -> PLANNING
    -> ALLOCATION -> EXECUTION -> INTEGRATION -> TESTING -> REVIEW -> REPAIR
    -> DELIVERY

Execution is dependency-aware and parallel: tasks whose dependencies have
succeeded run concurrently, each in its own Agent Server conversation bound to
the project workspace. Every state change is persisted and published on the
event bus, so a run can be watched live and resumed after a restart.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from level5.agents.registry import get_role
from level5.config import Settings, get_settings
from level5.events import get_event_bus
from level5.intelligence.planner import Planner
from level5.intelligence.research import ResearchEngine
from level5.intelligence.understanding import UnderstandingEngine
from level5.models import (
    Artifact,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)
from level5.runtime.agent_server import AgentServerClient, ExecutionResult
from level5.storage.store import get_store

logger = logging.getLogger("level5.orchestrator")

# Words too common to signal that a task addresses an acceptance criterion.
_STOPWORDS = {
    "with", "that", "this", "from", "have", "must", "able", "into", "than",
    "then", "when", "which", "where", "there", "their", "they", "them", "been",
    "each", "does", "your", "user", "users", "using", "used", "also", "such",
    "more", "most", "only", "over", "same", "some", "will", "would", "should",
    "could", "about", "after", "before", "between", "both", "other", "any",
    "all", "and", "the", "for", "are", "not", "can", "its", "own", "one",
}


def _stem(word: str) -> str:
    """Crude suffix stripping so 'authenticate' matches 'authentication'."""
    for suffix in ("ation", "ting", "ing", "ions", "ion", "ate", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _keywords(text: str) -> set[str]:
    """Significant, lightly stemmed words in `text`."""
    return {
        _stem(w)
        for w in re.findall(r"[a-z]{3,}", text.lower())
        if w not in _STOPWORDS
    }


# Roles that verify other tasks rather than produce the artifact a criterion
# describes. They are not accepted as the evidence owner for a criterion.
_REVIEW_ROLES = {
    "code_reviewer",
    "security_engineer",
    "performance_engineer",
    "benchmarking_agent",
    "technical_decision_reviewer",
}

# Errors worth retrying: infrastructure hiccups that say nothing about the
# quality of the agent's work.
_TRANSIENT_FAILURE_MARKERS = (
    "504",
    "502",
    "503",
    "gateway timeout",
    "timed out",
    "timeout",
    "rate limit",
    "429",
    "connection reset",
    "connection error",
    "temporarily unavailable",
    "overloaded",
)

# Errors that must never be retried: they are the agent's own result.
_PERMANENT_FAILURE_MARKERS = (
    "test failed",
    "tests failed",
    "syntaxerror",
    "assertionerror",
    "traceback",
    "permission denied",
    "blocked by an upstream failure",
)


class Orchestrator:
    """Drives a project from request to delivered artifacts."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        agent_client: AgentServerClient | None = None,
        understanding: UnderstandingEngine | None = None,
        research: ResearchEngine | None = None,
        planner: Planner | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.agent = agent_client or AgentServerClient(self.settings)
        self.understanding = understanding or UnderstandingEngine()
        self.research = research or ResearchEngine()
        self.planner = planner or Planner()
        self.bus = get_event_bus()
        self.store = get_store()
        self._running: set[str] = set()

    # ------------------------------------------------------------------ #
    # Planning pipeline
    # ------------------------------------------------------------------ #
    async def understand_and_plan(
        self,
        project: Project,
        *,
        request: str | None = None,
        do_research: bool | None = None,
    ) -> Project:
        """Understand the request, optionally research, then build the graph."""
        text = request or project.original_request
        await self._emit(project, "phase", "Understanding the request", phase="understanding")

        spec = await self.understanding.understand(text)
        project.specification = spec
        project.name = project.name or _derive_name(text)
        project.status = ProjectStatus.PLANNING
        await self._emit(
            project,
            "specification",
            f"Specification produced: {spec.deliverable}",
            domain=spec.domain.value,
            module=spec.caber_module.value,
            requirements=len(spec.requirements),
        )

        research_context = ""
        should_research = (
            spec.research_needed if do_research is None else do_research
        )
        if should_research and spec.research_questions:
            project.status = ProjectStatus.RESEARCHING
            await self._emit(
                project,
                "phase",
                f"Researching {len(spec.research_questions)} question(s)",
                phase="research",
            )
            reports = await self.research.investigate_many(spec.research_questions)
            project.research.extend(reports)
            research_context = "\n\n".join(
                f"Q: {r.question}\n{r.summary}\n"
                + "\n".join(f"  - {f}" for f in r.findings)
                for r in reports
            )
            await self._emit(
                project,
                "research",
                f"Research complete: {len(reports)} report(s)",
                sources=sum(len(r.sources) for r in reports),
            )

        await self._emit(project, "phase", "Planning engineering tasks", phase="planning")
        graph = await self.planner.plan(spec, research_context=research_context)
        project.task_graph = graph
        project.snapshot("plan", note=f"{len(graph.tasks)} tasks planned")
        await self._emit(
            project,
            "plan",
            f"Task graph ready: {len(graph.tasks)} tasks",
            tasks=[{"id": t.id, "title": t.title, "role": t.agent_role} for t in graph.tasks],
        )
        await self._persist(project)
        return project

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #
    async def execute(self, project: Project) -> Project:
        """Execute the task graph to completion, then deliver."""
        if project.id in self._running:
            raise RuntimeError(f"project {project.id} is already executing")
        self._running.add(project.id)
        try:
            project.status = ProjectStatus.EXECUTING
            await self._persist(project)
            await self._emit(project, "phase", "Executing task graph", phase="execution")

            await self._run_graph(project)

            project.status = ProjectStatus.TESTING
            await self._emit(project, "phase", "Verifying deliverables", phase="testing")
            await self._verify(project)

            await self._integrate(project)

            failed = [t for t in project.task_graph.tasks if t.status == TaskStatus.FAILED]
            if failed:
                project.status = ProjectStatus.FAILED
                await self._emit(
                    project,
                    "failed",
                    f"{len(failed)} task(s) failed",
                    tasks=[t.id for t in failed],
                )
            else:
                project.status = ProjectStatus.DELIVERED
                project.snapshot("delivered", note="All tasks succeeded")
                await self._emit(project, "delivered", "Project delivered")
            await self._persist(project)
            try:
                from level5.benchmarks import record as record_benchmark

                summary = await record_benchmark(project)
                await self._emit(
                    project,
                    "benchmark",
                    "Measured run recorded",
                    task_success_rate=summary["task_success_rate"],
                    criteria_rate=summary["criteria_rate"],
                    duration_seconds=summary["duration_seconds"],
                )
            except Exception as exc:  # noqa: BLE001 - benchmarking must not fail a run
                logger.warning("benchmark recording failed: %s", exc)
            return project
        finally:
            self._running.discard(project.id)

    async def _run_graph(self, project: Project) -> None:
        graph = project.task_graph
        max_parallel = max(1, self.settings.max_parallel_tasks)
        while True:
            ready = [
                t
                for t in graph.ready()
                if t.status in (TaskStatus.PENDING, TaskStatus.READY)
            ]
            if not ready:
                break
            batch = ready[:max_parallel]
            for task in batch:
                task.status = TaskStatus.READY
            await asyncio.gather(*(self._run_task(project, task) for task in batch))
            await self._persist(project)
            # If nothing progressed and nothing is running, stop to avoid a spin.
            if all(
                t.status in (TaskStatus.FAILED, TaskStatus.CANCELLED)
                for t in graph.tasks
                if t.status not in (TaskStatus.SUCCEEDED, TaskStatus.SKIPPED)
            ):
                break
        # Mark anything still pending as skipped (blocked by a failure).
        for task in graph.tasks:
            if task.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.BLOCKED):
                task.status = TaskStatus.SKIPPED
                task.error = "blocked by an upstream failure"

    async def _run_task(self, project: Project, task: Task) -> None:
        role = get_role(task.agent_role)
        prompt = self._task_prompt(project, task)
        workspace = str(Path(project.workspace_path))

        while True:
            task.status = TaskStatus.RUNNING
            task.attempts += 1
            task.started_at = datetime.now(timezone.utc)
            await self._emit(
                project,
                "task_started",
                f"[{role.title}] {task.title}"
                + (f" (attempt {task.attempts})" if task.attempts > 1 else ""),
                task_id=task.id,
                role=role.name,
                phase=task.phase,
            )
            # Persist the RUNNING state immediately so a live client sees which
            # tasks are in flight, not just the last completed batch.
            await self._persist(project)

            try:
                result = await self.agent.run_to_completion(
                    working_dir=workspace,
                    task_prompt=prompt,
                    tools=list(task.tools),
                    system_prompt=role.system_prompt,
                    max_iterations=self.settings.default_max_iterations,
                    timeout=1800.0,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as task failure
                if self._should_retry(task, str(exc)):
                    await self._emit(
                        project,
                        "task_retry",
                        f"[{role.title}] {task.title}: transient error, retrying "
                        f"({task.attempts}/{task.max_attempts})",
                        task_id=task.id,
                        error=str(exc)[:200],
                    )
                    await asyncio.sleep(self._retry_delay(task.attempts))
                    continue
                self._fail_task(task, str(exc))
                await self._emit(
                    project, "task_failed", f"[{role.title}] {task.title}: {exc}",
                    task_id=task.id,
                )
                await self._persist(project)
                return

            if result.succeeded:
                task.conversation_id = result.conversation_id
                project.conversation_ids.append(result.conversation_id)
                self._record_artifacts(project, task, result)
                project.tests.extend(self._tests_from(result, task))
                task.status = TaskStatus.SUCCEEDED
                task.error = None
                task.evidence.append(result.final_message[:500])
                for path in result.files_changed:
                    task.evidence.append(f"file: {path}")
                task.finished_at = datetime.now(timezone.utc)
                await self._emit(
                    project,
                    "task_succeeded",
                    f"[{role.title}] {task.title} completed",
                    task_id=task.id,
                    files=len(result.files_changed),
                    iterations=result.iterations,
                    attempts=task.attempts,
                )
                await self._persist(project)
                return

            error = result.error or "task did not complete successfully"
            if self._should_retry(task, error, retryable=result.retryable):
                await self._emit(
                    project,
                    "task_retry",
                    f"[{role.title}] {task.title}: transient error, retrying "
                    f"({task.attempts}/{task.max_attempts})",
                    task_id=task.id,
                    error=error[:200],
                )
                await asyncio.sleep(self._retry_delay(task.attempts))
                continue
            self._fail_task(task, error)
            await self._emit(
                project, "task_failed", f"[{role.title}] {task.title}: {error}",
                task_id=task.id,
            )
            await self._persist(project)
            return

    def _should_retry(
        self, task: Task, error: str, retryable: bool | None = None
    ) -> bool:
        """Retry only transient infrastructure faults, never logic failures.

        A gateway timeout, rate limit or dropped connection is worth retrying.
        A compile error, a failed test or a bad plan is not: retrying it just
        burns budget and would mask a real defect.

        When the agent server classified the error it tells us whether it is
        retryable; that verdict wins. String matching is only the fallback for
        errors the server did not classify.
        """
        if task.attempts >= task.max_attempts:
            return False
        if retryable is not None:
            return retryable
        lowered = error.lower()
        if any(s in lowered for s in _PERMANENT_FAILURE_MARKERS):
            return False
        return any(s in lowered for s in _TRANSIENT_FAILURE_MARKERS)

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return min(30.0, 5.0 * (2 ** (attempt - 1)))

    @staticmethod
    def _fail_task(task: Task, error: str) -> None:
        task.status = TaskStatus.FAILED
        task.error = error
        task.finished_at = datetime.now(timezone.utc)

    def _task_prompt(self, project: Project, task: Task) -> str:
        spec = project.specification
        lines = [
            f"PROJECT: {project.name}",
            f"OVERALL DELIVERABLE: {spec.deliverable}",
            f"DOMAIN: {spec.domain.value}",
            "",
            f"YOUR TASK: {task.title}",
            f"OBJECTIVE: {task.objective}",
        ]
        if task.outputs:
            lines.append("EXPECTED OUTPUTS: " + ", ".join(task.outputs))
        if task.acceptance_criteria:
            lines.append("ACCEPTANCE CRITERIA:")
            lines.extend(f"- {c}" for c in task.acceptance_criteria)
        completed = [
            t.title
            for t in project.task_graph.tasks
            if t.status == TaskStatus.SUCCEEDED and t.id != task.id
        ]
        if completed:
            lines.append("")
            lines.append("ALREADY COMPLETED BY OTHER AGENTS:")
            lines.extend(f"- {title}" for title in completed)
            lines.append(
                "Reuse existing files; do not duplicate or overwrite work unless "
                "it is necessary and you explain why."
            )
        lines.append("")
        lines.append(
            "Work only inside the current working directory. Create real files. "
            "Run the code or tests you write to confirm they work, then summarise "
            "what you produced and any remaining problem."
        )
        return "\n".join(lines)

    def _record_artifacts(
        self, project: Project, task: Task, result: ExecutionResult
    ) -> None:
        workspace = Path(project.workspace_path)
        seen = {a.path for a in project.artifacts}
        for rel in result.files_changed:
            path = Path(rel)
            if not path.is_absolute():
                path = workspace / rel
            try:
                resolved = path.resolve()
                resolved.relative_to(workspace.resolve())
            except (ValueError, OSError):
                continue
            rel_path = str(resolved.relative_to(workspace.resolve()))
            if rel_path in seen:
                continue
            seen.add(rel_path)
            size = resolved.stat().st_size if resolved.exists() else 0
            project.artifacts.append(
                Artifact(
                    name=resolved.name,
                    kind="file",
                    path=rel_path,
                    size_bytes=size,
                    created_by_task=task.id,
                    description=f"Produced by {task.title}",
                )
            )

    def _tests_from(self, result: ExecutionResult, task: Task):
        from level5.models import TestResult

        tests = []
        for command in result.commands_run:
            if any(k in command for k in ("pytest", "npm test", "go test", "cargo test", "jest")):
                tests.append(
                    TestResult(
                        suite="agent-run",
                        name=command[:120],
                        status="passed" if result.succeeded else "failed",
                        task_id=task.id,
                        message=result.final_message[:300],
                    )
                )
        return tests

    # ------------------------------------------------------------------ #
    # Verification, integration, delivery
    # ------------------------------------------------------------------ #
    async def _verify(self, project: Project) -> None:
        """Record per-criterion verification state from task evidence.

        A criterion is satisfied only when a succeeded task actually addresses
        it — matched on the task's own acceptance criteria, objective and title.
        A criterion no task addresses is left unsatisfied and flagged as
        unverified rather than being marked met because *something* ran.
        """
        succeeded = [
            t for t in project.task_graph.tasks if t.status == TaskStatus.SUCCEEDED
        ]
        for criterion in project.specification.acceptance_criteria:
            owner = self._matching_task(criterion.statement, succeeded)
            criterion.satisfied = owner is not None
            if owner is not None:
                criterion.evidence = f"task {owner.id} ({owner.title})"
            else:
                criterion.evidence = "no task produced evidence for this criterion"
        met = sum(1 for c in project.specification.acceptance_criteria if c.satisfied)
        await self._emit(
            project,
            "verification",
            f"{met}/{len(project.specification.acceptance_criteria)} criteria satisfied",
        )

    @staticmethod
    def _matching_task(statement: str, candidates: list[Task]) -> Task | None:
        """Return the best succeeded task that addresses `statement`, if any.

        Review-only roles are excluded as evidence owners: a reviewer task lists
        every criterion in its own scope, so it would otherwise absorb all of
        them and report universal satisfaction without producing anything.
        """
        keywords = _keywords(statement)
        if not keywords:
            return None
        best: tuple[float, Task] | None = None
        for task in candidates:
            if task.agent_role in _REVIEW_ROLES:
                continue
            haystack = " ".join(
                [task.title, task.objective, *task.acceptance_criteria]
            )
            overlap = len(keywords & _keywords(haystack))
            score = overlap / len(keywords)
            if overlap >= 2 and score >= 0.34 and (best is None or score > best[0]):
                best = (score, task)
        return best[1] if best else None

    async def _integrate(self, project: Project) -> None:
        """Write the project report and refresh the artifact list."""
        workspace = Path(project.workspace_path)
        report_path = workspace / "LEVEL5_REPORT.md"
        report_path.write_text(self._render_report(project), encoding="utf-8")
        if not any(a.path == "LEVEL5_REPORT.md" for a in project.artifacts):
            project.artifacts.append(
                Artifact(
                    name="LEVEL5_REPORT.md",
                    kind="report",
                    path="LEVEL5_REPORT.md",
                    size_bytes=report_path.stat().st_size,
                    description="Generated project report",
                )
            )
        await self._emit(project, "report", "Project report generated")

    def _render_report(self, project: Project) -> str:
        spec = project.specification
        lines = [
            f"# {project.name}",
            "",
            f"**Status:** {project.status.value}",
            f"**Domain:** {spec.domain.value}  |  **CABER module:** {spec.caber_module.value}",
            "",
            "## Intent",
            spec.intent,
            "",
            "## Deliverable",
            spec.deliverable,
            "",
            "## Requirements",
        ]
        for req in spec.requirements:
            lines.append(f"- ({req.origin}/{req.priority}) {req.text}")
        lines += ["", "## Acceptance criteria"]
        for crit in spec.acceptance_criteria:
            mark = "x" if crit.satisfied else " "
            lines.append(f"- [{mark}] {crit.statement} ({crit.verification_method})")
        if project.research:
            lines += ["", "## Research"]
            for report in project.research:
                lines.append(f"### {report.question}")
                lines.append(report.summary)
                for source in report.sources:
                    lines.append(f"- ({source.kind.value}) {source.title} <{source.url}>")
        lines += ["", "## Tasks"]
        for task in project.task_graph.tasks:
            lines.append(
                f"- [{task.status.value}] {task.title} - {task.agent_role}"
                + (f" (error: {task.error})" if task.error else "")
            )
        lines += ["", "## Artifacts"]
        for art in project.artifacts:
            lines.append(f"- {art.path} ({art.size_bytes} bytes)")
        lines += ["", "## Version history"]
        for version in project.versions:
            lines.append(f"- {version.label} @ {version.created_at.isoformat()} - {version.note}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    async def _emit(self, project: Project, kind: str, message: str, **data: Any) -> None:
        project.log(kind, message, **data)
        await self.bus.publish(
            project.id, {"kind": kind, "message": message, "project_id": project.id, **data}
        )

    async def _persist(self, project: Project) -> None:
        await self.store.save(project)


def _derive_name(request: str) -> str:
    text = request.strip().split("\n")[0]
    text = text[:80].strip()
    return text or "Untitled project"
