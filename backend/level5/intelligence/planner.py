"""Engineering planner: specification -> dependency-aware task graph.

Each task names its objective, agent role, dependencies, expected outputs and
acceptance criteria, so the orchestrator can schedule it and a reviewer can
judge it. The planner prefers a small, coherent graph over many tiny tasks.
"""

from __future__ import annotations

import logging
from typing import Any

from level5.agents.registry import get_role, select_roles_for_domain
from level5.llm.client import LLMClient, get_llm_client
from level5.models import Specification, Task, TaskGraph

logger = logging.getLogger("level5.intelligence.planner")

_SYSTEM = """You are the engineering planning engine of LEVEL 5.

Decompose the specification into a dependency-aware task graph of real
implementation work. Rules:
- Prefer 4-10 substantial tasks over dozens of trivial ones.
- Each task must produce a concrete artifact (files, tests, a report).
- Dependencies must reference other task indices and be acyclic.
- Every task names exactly one specialist role from the allowed list.
- Include at least one testing/verification task and, for non-trivial systems,
  one independent review task.
- Phase is one of: architecture, implementation, integration, testing, review,
  research, documentation.

Respond with a single JSON object:
{
  "tasks": [
    {
      "key": string,                    // short unique slug, e.g. "backend_api"
      "title": string,
      "objective": string,              // precise, self-contained instruction
      "agent_role": one of %(roles)s,
      "phase": string,
      "depends_on": [string],           // other task keys
      "outputs": [string],              // expected file paths or artifacts
      "acceptance_criteria": [string],
      "tools": [string]                 // subset of terminal, file_editor, task_tracker
    }
  ]
}"""


class Planner:
    """Builds a :class:`TaskGraph` from a specification."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    async def plan(
        self,
        spec: Specification,
        *,
        research_context: str = "",
        max_tasks: int = 12,
    ) -> TaskGraph:
        suggested = select_roles_for_domain(spec.domain.value, spec.deliverable)
        allowed_roles = sorted(
            {
                "product_architect",
                "fullstack_engineer",
                "frontend_engineer",
                "backend_engineer",
                "database_engineer",
                "api_engineer",
                "ui_ux_engineer",
                "mobile_engineer",
                "desktop_engineer",
                "enterprise_systems_engineer",
                "cloud_engineer",
                "devops_engineer",
                "ai_research_engineer",
                "agent_systems_engineer",
                "multi_agent_orchestration_engineer",
                "machine_learning_engineer",
                "model_evaluation_engineer",
                "data_engineer",
                "three_d_systems_engineer",
                "procedural_geometry_engineer",
                "rendering_engineer",
                "simulation_engineer",
                "building_intelligence_engineer",
                "testing_engineer",
                "security_engineer",
                "performance_engineer",
                "debugging_engineer",
                "code_reviewer",
                "technology_research_agent",
                "academic_research_agent",
                "innovation_research_agent",
                *suggested,
            }
        )
        system = _SYSTEM % {"roles": allowed_roles}
        user = self._render_brief(spec, research_context, max_tasks)

        data, usage = await self.llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=5000,
        )
        logger.info("planning complete (%s tokens)", usage.total_tokens)
        return self._to_graph(data, allowed_roles, max_tasks)

    def _render_brief(
        self, spec: Specification, research_context: str, max_tasks: int
    ) -> str:
        reqs = "\n".join(
            f"- [{r.origin}/{r.priority}] {r.text}" for r in spec.requirements
        )
        criteria = "\n".join(f"- {c.statement}" for c in spec.acceptance_criteria)
        tech = "\n".join(
            f"- {t['area']}: {t['choice']} ({t['rationale']})"
            for t in spec.technology_choices
        )
        parts = [
            f"INTENT: {spec.intent}",
            f"DELIVERABLE: {spec.deliverable}",
            f"DOMAIN: {spec.domain.value}",
            f"SUMMARY: {spec.summary}",
            f"REQUIREMENTS:\n{reqs or '- (none listed)'}",
            f"ACCEPTANCE CRITERIA:\n{criteria or '- (none listed)'}",
        ]
        if tech:
            parts.append(f"TECHNOLOGY CHOICES:\n{tech}")
        if research_context:
            parts.append(f"RESEARCH CONTEXT:\n{research_context[:4000]}")
        parts.append(f"Produce at most {max_tasks} tasks.")
        return "\n\n".join(parts)

    def _to_graph(
        self, data: dict[str, Any], allowed_roles: list[str], max_tasks: int
    ) -> TaskGraph:
        raw_tasks = [t for t in (data.get("tasks") or []) if isinstance(t, dict)]
        raw_tasks = raw_tasks[:max_tasks]
        key_to_id: dict[str, str] = {}
        tasks: list[Task] = []

        for index, item in enumerate(raw_tasks):
            key = str(item.get("key") or f"task_{index + 1}")
            role = str(item.get("agent_role", "fullstack_engineer"))
            if role not in allowed_roles:
                role = "fullstack_engineer"
            tools = [
                str(t)
                for t in (item.get("tools") or ["terminal", "file_editor", "task_tracker"])
                if t in ("terminal", "file_editor", "task_tracker", "browser_tool_set")
            ]
            task = Task(
                title=str(item.get("title") or key),
                objective=str(item.get("objective") or item.get("title") or key),
                agent_role=role,
                phase=str(item.get("phase", "implementation")),
                outputs=[str(o) for o in (item.get("outputs") or [])],
                tools=tools or ["terminal", "file_editor", "task_tracker"],
                permissions=list(get_role(role).permissions),
                acceptance_criteria=[
                    str(c) for c in (item.get("acceptance_criteria") or [])
                ],
            )
            key_to_id[key] = task.id
            tasks.append(task)

        # Resolve dependencies and drop any that point outside the graph or
        # would create a cycle (defensive: the model occasionally misbehaves).
        for item, task in zip(raw_tasks, tasks):
            deps: list[str] = []
            for dep_key in item.get("depends_on") or []:
                dep_id = key_to_id.get(str(dep_key))
                if dep_id and dep_id != task.id and not _would_cycle(tasks, task.id, dep_id):
                    deps.append(dep_id)
            task.dependencies = deps

        if not tasks:
            tasks = [
                Task(
                    title="Implement the deliverable",
                    objective="Implement the requested deliverable end to end.",
                    agent_role="fullstack_engineer",
                    phase="implementation",
                    acceptance_criteria=["The deliverable exists and runs."],
                )
            ]
        return TaskGraph(tasks=tasks)


def _would_cycle(tasks: list[Task], node_id: str, dep_id: str) -> bool:
    """True when adding ``node -> dep`` would introduce a cycle."""
    by_id = {t.id: t for t in tasks}
    stack = [dep_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current == node_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        parent = by_id.get(current)
        if parent:
            stack.extend(parent.dependencies)
    return False
