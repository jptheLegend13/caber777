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
from level5.knowledge.store import get_knowledge_store
from level5.models import (
    Artifact,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)
from level5.runtime.agent_server import AgentServerClient, ExecutionResult
from level5.storage.store import get_store
from level5.worktrees import WorktreeError, WorktreeManager, ensure_repo

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
        self._worktree_lock = asyncio.Lock()
        self._worktrees: WorktreeManager | None = None

    # ------------------------------------------------------------------ #
    # Planning pipeline
    # ------------------------------------------------------------------ #
    async def understand(
        self,
        project: Project,
        *,
        request: str | None = None,
    ) -> Project:
        """Understand the request and set the structured specification.

        Deliberately stops at the specification (no research, no plan). The run
        pipeline inspects the classified CABER module straight after this and
        routes building and novel-idea requests to their specialist engines,
        which perform their own research and planning. Running the generic
        research here first would duplicate that work and delay the route.
        """
        text = request or project.original_request
        await self._emit(project, "phase", "Understanding the request", phase="understanding")

        spec = await self.understanding.understand(text, attachments=project.attachments)
        project.specification = spec
        project.name = project.name or _derive_name(text)
        project.status = ProjectStatus.PLANNING
        self._research_context = ""
        # Remember the specification in LEVEL 5's own knowledge store. This is
        # the platform's memory: it is written here and retrieved before
        # planning, and it needs no model to work.
        try:
            await self._remember_specification(project)
        except Exception as exc:  # noqa: BLE001 - memory must never break a run
            logger.warning("knowledge write failed: %s", exc)
        await self._emit(
            project,
            "specification",
            f"Specification produced: {spec.deliverable}",
            domain=spec.domain.value,
            module=spec.caber_module.value,
            requirements=len(spec.requirements),
        )
        await self._persist(project)
        return project

    async def _remember_specification(self, project: Project) -> None:
        """Store the request, requirements and decisions in project memory."""
        store = get_knowledge_store()
        spec = project.specification
        await store.add(
            project_id=project.id,
            kind="specification",
            title=project.name or "Specification",
            text=(
                f"Intent: {spec.intent}\nDeliverable: {spec.deliverable}\n"
                f"Domain: {spec.domain.value}\nModule: {spec.caber_module.value}\n"
                f"Summary: {spec.summary}"
            ),
            source="understanding",
        )
        for req in spec.requirements:
            await store.add(
                project_id=project.id,
                kind="requirement",
                title=req.text[:120],
                text=f"[{req.origin}/{req.priority}] {req.text}",
                source="understanding",
            )
        for decision in spec.technology_choices:
            await store.add(
                project_id=project.id,
                kind="decision",
                title=f"{decision.get('area', 'decision')}: {decision.get('choice', '')}"[
                    :120
                ],
                text=(
                    f"{decision.get('area', '')} -> {decision.get('choice', '')}: "
                    f"{decision.get('rationale', '')}"
                ),
                source="planning",
            )

    async def recall(self, query: str, project_id: str, limit: int = 6) -> str:
        """Retrieve relevant project memory as a compact context block.

        Pure keyword retrieval — no model, no network.
        """
        try:
            hits = await get_knowledge_store().search(
                query, project_id=project_id, limit=limit
            )
        except Exception as exc:  # noqa: BLE001 - recall must never break a run
            logger.warning("knowledge retrieval failed: %s", exc)
            return ""
        if not hits:
            return ""
        lines = [f"- [{h.entry.kind}] {h.entry.title}: {h.entry.text[:300]}" for h in hits]
        return "PROJECT MEMORY (retrieved):\n" + "\n".join(lines)

    async def run_research(
        self, project: Project, *, do_research: bool | None = None
    ) -> Project:
        """Investigate the specification's research questions, if warranted."""
        spec = project.specification
        if spec is None:
            return project
        should_research = spec.research_needed if do_research is None else do_research
        research_context = ""
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
            # Persist research findings to project memory so later steps and
            # future sessions can retrieve them without re-searching.
            try:
                store = get_knowledge_store()
                for report in reports:
                    await store.add(
                        project_id=project.id,
                        kind="research",
                        title=report.question[:120],
                        text=report.summary + "\n" + "\n".join(report.findings),
                        source="research",
                    )
            except Exception as exc:  # noqa: BLE001 - memory is best-effort
                logger.warning("knowledge write (research) failed: %s", exc)
        self._research_context = research_context
        await self._persist(project)
        return project

    async def plan(self, project: Project) -> Project:
        """Build the dependency-aware task graph from the current spec."""
        await self._emit(project, "phase", "Planning engineering tasks", phase="planning")
        context = getattr(self, "_research_context", "")
        # Add retrieved project memory to the planning context. This is what
        # makes planning consistent across a resumed or long project: the
        # planner sees what the project already decided.
        memory = await self.recall(
            project.specification.intent, project.id, limit=6
        )
        if memory:
            context = f"{context}\n\n{memory}" if context else memory
        graph = await self.planner.plan(project.specification, research_context=context)
        project.task_graph = graph
        project.snapshot_workspace("plan", note=f"{len(graph.tasks)} tasks planned")
        await self._emit(
            project,
            "plan",
            f"Task graph ready: {len(graph.tasks)} tasks",
            tasks=[{"id": t.id, "title": t.title, "role": t.agent_role} for t in graph.tasks],
        )
        await self._persist(project)
        return project

    async def understand_and_plan(
        self,
        project: Project,
        *,
        request: str | None = None,
        do_research: bool | None = None,
    ) -> Project:
        """Understand, research, then build the graph (the generic path)."""
        await self.understand(project, request=request)
        await self.run_research(project, do_research=do_research)
        return await self.plan(project)

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #
    def prepare_resume(self, project: Project) -> None:
        """Reset a project for resumption without losing completed work.

        Tasks that already succeeded are kept; a task caught mid-flight when
        the process stopped is left RUNNING with no live conversation, so it is
        reset to PENDING and will be attempted again. Blocked/skipped tasks are
        also reset so a resolved upstream failure can unblock them.
        """
        for task in project.task_graph.tasks:
            if task.status == TaskStatus.SUCCEEDED:
                continue
            # A task that failed with attempts left over is worth another go;
            # one that exhausted its budget is left failed so the resume does
            # not loop on a defect that retrying cannot fix.
            if task.status == TaskStatus.FAILED and task.attempts >= task.max_attempts:
                continue
            if task.status in (
                TaskStatus.RUNNING,
                TaskStatus.READY,
                TaskStatus.BLOCKED,
                TaskStatus.SKIPPED,
                TaskStatus.PENDING,
                TaskStatus.FAILED,
            ):
                task.status = TaskStatus.PENDING
                task.error = None
        project.status = ProjectStatus.EXECUTING
        project.log("resume", "Resuming run from saved task state")

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
            unmet = [
                c
                for c in project.specification.acceptance_criteria
                if not c.satisfied
            ]
            if failed:
                project.status = ProjectStatus.FAILED
                await self._emit(
                    project,
                    "failed",
                    f"{len(failed)} task(s) failed",
                    tasks=[t.id for t in failed],
                )
            elif unmet:
                # No task failed, but the specification was not met. Reporting
                # this as delivered would be the same "files were generated"
                # mistake in a different place.
                project.status = ProjectStatus.FAILED
                await self._emit(
                    project,
                    "failed",
                    f"{len(unmet)} acceptance criteria unmet",
                    criteria=[c.id for c in unmet],
                )
            else:
                project.status = ProjectStatus.DELIVERED
                project.snapshot_workspace("delivered", note="All tasks succeeded")
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
        shared_workspace = str(Path(project.workspace_path))
        workspace, worktree = await self._prepare_workspace(project, task, shared_workspace)

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
                if worktree is not None:
                    await self._integrate_worktree(project, task)
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
            self._fail_task(task, error, result=result)
            if worktree is not None:
                await self._cleanup_worktree(task)
            await self._emit(
                project, "task_failed", f"[{role.title}] {task.title}: {error}",
                task_id=task.id,
                conversation_id=result.conversation_id,
            )
            await self._persist(project)
            return

    async def _prepare_workspace(
        self, project: Project, task: Task, shared_workspace: str
    ) -> tuple[str, bool]:
        """Return the directory the agent should work in and whether it is isolated.

        With worktrees enabled each task gets its own git worktree so parallel
        agents cannot overwrite one another's files; the changes are merged back
        into the shared workspace on success. Isolation is best-effort: if it
        cannot be set up the task runs in the shared workspace and an event says
        so, rather than pretending the work was isolated.
        """
        if not self.settings.task_worktrees:
            return shared_workspace, False
        try:
            manager = await self._ensure_worktree_manager(project)
            worktree = await asyncio.to_thread(manager.create, task.id)
        except (WorktreeError, OSError) as exc:
            await self._emit(
                project,
                "task_isolation",
                f"Worktree isolation unavailable for [{task.id}]; using the shared "
                f"workspace ({exc})",
                task_id=task.id,
            )
            return shared_workspace, False
        task.worktree = str(worktree.path)
        await self._emit(
            project,
            "task_isolation",
            f"Isolated [{task.id}] in a git worktree",
            task_id=task.id,
            path=str(worktree.path),
        )
        return str(worktree.path), True

    async def _ensure_worktree_manager(self, project: Project) -> WorktreeManager:
        if self._worktrees is not None:
            return self._worktrees
        async with self._worktree_lock:
            if self._worktrees is None:
                root = Path(project.workspace_path)
                await asyncio.to_thread(ensure_repo, root)
                self._worktrees = WorktreeManager(root, root / ".level5-worktrees")
        return self._worktrees

    async def _integrate_worktree(self, project: Project, task: Task) -> None:
        """Merge the task's worktree back into the shared workspace under a lock."""
        manager = self._worktrees
        if manager is None:
            return
        try:
            async with self._worktree_lock:
                changed = await asyncio.to_thread(
                    manager.integrate, task.id, f"[{task.agent_role}] {task.title}"
                )
            await self._emit(
                project,
                "task_integrated",
                f"Merged [{task.id}] into the workspace ({len(changed)} file(s))",
                task_id=task.id,
                files=changed,
            )
        except (WorktreeError, OSError) as exc:  # pragma: no cover - env dependent
            await self._emit(
                project,
                "task_integration_failed",
                f"Could not merge [{task.id}]; its files remain in the worktree ({exc})",
                task_id=task.id,
            )
        finally:
            await self._cleanup_worktree(task)

    async def _cleanup_worktree(self, task: Task) -> None:
        manager = self._worktrees
        if manager is None or task.worktree is None:
            return
        await asyncio.to_thread(manager.remove, task.id)
        task.worktree = None

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
    def _fail_task(
        task: Task, error: str, result: Any | None = None
    ) -> None:
        """Mark a task failed, keeping the conversation id and error detail.

        The conversation id is what makes a post-mortem possible: without it the
        Agent Server conversation that produced the failure cannot be inspected
        after the run, and the operator only sees "task did not complete".
        """
        task.status = TaskStatus.FAILED
        task.error = error
        task.finished_at = datetime.now(timezone.utc)
        if result is not None:
            conversation_id = getattr(result, "conversation_id", None)
            if conversation_id:
                task.conversation_id = conversation_id
            if not task.evidence and getattr(result, "final_message", None):
                task.evidence = str(result.final_message)[:2000]

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

    # Dependency and build directories are generated, not authored. Recording
    # them as deliverables would report thousands of files the team did not
    # write. They stay in the workspace; they are just not called artifacts.
    _DEPENDENCY_DIRS = frozenset(
        {
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
            ".git",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "dist",
            "build",
            ".next",
            "target",
            "site-packages",
        }
    )

    def _record_artifacts(
        self, project: Project, task: Task, result: ExecutionResult
    ) -> None:
        workspace = Path(project.workspace_path).resolve()
        seen = {a.path for a in project.artifacts}
        for rel in result.files_changed:
            path = Path(rel)
            if not path.is_absolute():
                path = workspace / rel
            try:
                resolved = path.resolve()
                rel_path = resolved.relative_to(workspace)
            except (ValueError, OSError):
                continue
            if any(part in self._DEPENDENCY_DIRS for part in rel_path.parts):
                continue
            rel_str = str(rel_path)
            if rel_str in seen:
                continue
            seen.add(rel_str)
            size = resolved.stat().st_size if resolved.exists() else 0
            project.artifacts.append(
                Artifact(
                    name=resolved.name,
                    kind="file",
                    path=rel_str,
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

    async def _build_deliverable(self, project: Project) -> None:
        """Build the generated app; if it fails, dispatch a repair and rebuild.

        A build failure is a real defect, not a cosmetic one, so it is handed
        to a debugging agent with the compiler output and the build is retried.
        Bounded by settings.max_build_repairs so a project that cannot be fixed
        is reported as such rather than looping.
        """
        from level5.models import TestResult
        from level5.preview import build_web_app

        max_repairs = max(0, int(getattr(self.settings, "max_build_repairs", 2)))
        last_repair = None
        for repair_round in range(max_repairs + 1):
            try:
                result = await asyncio.to_thread(build_web_app, project.workspace_path)
            except Exception as exc:  # noqa: BLE001 - build must not crash the run
                logger.warning("build raised: %s", exc)
                return
            if not result.attempted:
                return
            status = "passed" if result.succeeded else "failed"
            project.tests.append(
                TestResult(
                    suite="build",
                    name=result.command or "npm run build",
                    status=status,
                    message=(result.output or "")[-800:],
                )
            )
            await self._emit(
                project,
                "build",
                f"Frontend build {'succeeded' if result.succeeded else 'failed'}"
                + (f" -> {result.dist_dir}" if result.dist_dir else "")
                + (f" (repair {repair_round})" if repair_round else ""),
                succeeded=result.succeeded,
                command=result.command,
            )
            if result.succeeded:
                # A repair round is only successful once its rebuild passes;
                # the repair's acceptance criterion is "the build exits 0".
                if last_repair is not None:
                    last_repair.status = TaskStatus.SUCCEEDED
                return
            if last_repair is not None and last_repair.status == TaskStatus.SUCCEEDED:
                last_repair.status = TaskStatus.FAILED
                last_repair.error = "build still failing after this repair"
            if repair_round >= max_repairs:
                await self._emit(
                    project,
                    "build",
                    f"Build still failing after {max_repairs} repair attempt(s); "
                    "the deliverable does not build",
                    succeeded=False,
                )
                return
            last_repair = await self._repair_build(project, result, repair_round + 1)
            await self._persist(project)

    async def _repair_build(self, project: Project, result, repair_round: int) -> Task:
        """Dispatch a debugging agent to fix a failing build, with the errors."""
        from level5.models import Task, TaskStatus
        from level5.agents.registry import get_role

        role = get_role("debugging_engineer")
        task = Task(
            title=f"Repair failing frontend build (round {repair_round})",
            objective=(
                "The frontend build fails. Read the compiler output below, fix the "
                "source so the build succeeds, and verify by running the build "
                "command yourself. Do not disable type checking, remove tests, or "
                "loosen the build to make it pass."
            ),
            agent_role=role.name,
            phase="repair",
            inputs=[result.command or "npm run build"],
            outputs=["a frontend that builds cleanly"],
            acceptance_criteria=["npm run build exits 0"],
            status=TaskStatus.RUNNING,
        )
        task.attempts = 1
        project.task_graph.tasks.append(task)
        await self._emit(
            project,
            "repair",
            f"[{role.title}] repairing failing build (round {repair_round})",
            task_id=task.id,
            error=(result.output or "")[-300:],
        )
        prompt = (
            f"{role.system_prompt}\n\n"
            f"Workspace: {project.workspace_path}\n\n"
            f"Objective: {task.objective}\n\n"
            f"Build command: {result.command}\n"
            f"Package directory: {result.package_dir}\n\n"
            f"Build output:\n{result.output[-6000:]}\n"
        )
        outcome = await self.agent.run_to_completion(
            working_dir=project.workspace_path,
            task_prompt=prompt,
            tools=list(role.tools),
            system_prompt=role.system_prompt,
            max_iterations=self.settings.default_max_iterations,
            timeout=1800.0,
        )
        task.status = (
            TaskStatus.SUCCEEDED if outcome.succeeded else TaskStatus.FAILED
        )
        task.error = outcome.error
        task.evidence.append(outcome.final_message[:500])
        self._record_artifacts(project, task, outcome)
        await self._emit(
            project,
            "repair",
            f"[{role.title}] repair round {repair_round} "
            f"{'completed' if outcome.succeeded else 'failed'}",
            task_id=task.id,
        )
        return task

    async def _integrate(self, project: Project) -> None:
        """Build the app, write the project report, refresh artifacts."""
        await self._build_deliverable(project)

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
