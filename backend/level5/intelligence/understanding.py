"""Central Intelligence: request understanding and engineering planning.

Turns a natural-language request into a structured :class:`Specification`:
intent, deliverable, domain, requirements, constraints, acceptance criteria,
missing information and research questions.

The model is instructed to separate user-supplied requirements from inferred
decisions, and to use safe defaults instead of asking about unimportant gaps.
"""

from __future__ import annotations

import logging
from typing import Any

from level5.llm.client import LLMClient, get_llm_client
from level5.models import (
    AcceptanceCriterion,
    CABERModule,
    Constraint,
    ProjectDomain,
    Requirement,
    Specification,
)

logger = logging.getLogger("level5.intelligence.understanding")

_VALID_DOMAINS = {d.value for d in ProjectDomain}
_VALID_MODULES = {m.value for m in CABERModule}

_SYSTEM = """You are Central Intelligence, the requirement-understanding and
engineering-planning engine of LEVEL 5, an autonomous engineering platform.

Given a user's request, produce a precise engineering specification as JSON.

Rules:
- Identify the concrete deliverable (what will exist when the work is done).
- Classify the technical domain using exactly one of the allowed values.
- Separate requirements the USER stated (origin="user") from decisions you
  inferred to fill gaps (origin="inferred"). Be strict about this distinction.
- Use safe, conventional defaults for unimportant missing details; list only
  gaps that materially change the outcome in `missing_information`.
- Every acceptance criterion must be objectively verifiable.
- Never invent facts about the user's environment.

Respond with a single JSON object using exactly this schema:
{
  "intent": string,                     // one sentence: what the user wants
  "deliverable": string,                // the concrete artifact to produce
  "domain": one of %(domains)s,
  "caber_module": one of %(modules)s,   // A=apps, B=problem solving, C=buildings, P=platform
  "summary": string,                    // 2-4 sentence plan overview
  "requirements": [{"text": string, "origin": "user"|"inferred",
                    "category": string, "priority": "must"|"should"|"could",
                    "acceptance_criteria": [string]}],
  "constraints": [{"text": string, "kind": "technical"|"budget"|"time"|"legal"|"other",
                   "origin": "user"|"inferred"}],
  "acceptance_criteria": [{"statement": string, "verification_method": string}],
  "missing_information": [string],
  "assumptions": [string],
  "clarifications_needed": boolean,     // true ONLY if work cannot sensibly start
  "research_needed": boolean,
  "research_questions": [string],
  "technology_choices": [{"area": string, "choice": string, "rationale": string}]
}""" % {"domains": sorted(_VALID_DOMAINS), "modules": sorted(_VALID_MODULES)}


class UnderstandingEngine:
    """Builds a structured specification from a natural-language request."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    async def understand(self, request: str) -> Specification:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": request.strip()},
        ]
        data, usage = await self.llm.chat_json(messages, temperature=0.1, max_tokens=4000)
        logger.info(
            "understanding complete (%s tokens)", usage.total_tokens
        )
        return self._to_specification(request, data)

    def _to_specification(self, request: str, data: dict[str, Any]) -> Specification:
        domain_value = str(data.get("domain", "general"))
        if domain_value not in _VALID_DOMAINS:
            domain_value = _infer_domain(request).value
        module_value = str(data.get("caber_module", "P")).upper()
        if module_value not in _VALID_MODULES:
            module_value = _default_module(ProjectDomain(domain_value)).value

        requirements: list[Requirement] = []
        for item in data.get("requirements", []) or []:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            origin = item.get("origin", "user")
            priority = item.get("priority", "must")
            requirements.append(
                Requirement(
                    text=str(item["text"]),
                    origin="user" if origin == "user" else "inferred",
                    category=str(item.get("category", "functional")),
                    priority=priority if priority in ("must", "should", "could") else "must",
                    acceptance_criteria=[
                        str(c) for c in (item.get("acceptance_criteria") or [])
                    ],
                )
            )
        if not requirements:
            requirements = [
                Requirement(
                    text=f"Deliver: {data.get('deliverable') or request[:120]}",
                    origin="user",
                    acceptance_criteria=["The deliverable exists and runs."],
                )
            ]

        constraints = [
            Constraint(
                text=str(c["text"]),
                kind=c.get("kind", "technical")
                if c.get("kind") in ("technical", "budget", "time", "legal", "other")
                else "technical",
                origin="user" if c.get("origin") == "user" else "inferred",
            )
            for c in (data.get("constraints") or [])
            if isinstance(c, dict) and c.get("text")
        ]

        criteria = [
            AcceptanceCriterion(
                statement=str(c["statement"]),
                verification_method=str(c.get("verification_method", "automated_test")),
            )
            for c in (data.get("acceptance_criteria") or [])
            if isinstance(c, dict) and c.get("statement")
        ]
        if not criteria:
            criteria = [
                AcceptanceCriterion(
                    statement="The deliverable is produced and passes its tests.",
                    verification_method="automated_test",
                )
            ]

        tech = [
            {
                "area": str(t.get("area", "")),
                "choice": str(t.get("choice", "")),
                "rationale": str(t.get("rationale", "")),
            }
            for t in (data.get("technology_choices") or [])
            if isinstance(t, dict) and t.get("choice")
        ]

        return Specification(
            intent=str(data.get("intent") or request[:200]),
            deliverable=str(data.get("deliverable") or "working software"),
            domain=ProjectDomain(domain_value),
            caber_module=CABERModule(module_value),
            summary=str(data.get("summary", "")),
            requirements=requirements,
            constraints=constraints,
            acceptance_criteria=criteria,
            missing_information=[str(m) for m in (data.get("missing_information") or [])],
            assumptions=[str(a) for a in (data.get("assumptions") or [])],
            clarifications_needed=bool(data.get("clarifications_needed", False)),
            technology_choices=tech,
            research_needed=bool(data.get("research_needed", False)),
            research_questions=[str(q) for q in (data.get("research_questions") or [])],
        )


def _infer_domain(request: str) -> ProjectDomain:
    """Cheap keyword fallback when the model output is unusable."""
    text = request.lower()
    rules = [
        (("building", "house", "villa", "architecture", "floor plan", "mansion"), ProjectDomain.ARCHITECTURE_3D),
        (("3d", "game", "render", "viewport", "mesh"), ProjectDomain.ARCHITECTURE_3D),
        (("research", "investigate", "study", "paper", "hypothesis"), ProjectDomain.RESEARCH),
        (("simulation", "simulate", "numeric model"), ProjectDomain.SIMULATION),
        (("multi-agent", "multi agent", "orchestrat"), ProjectDomain.MULTI_AGENT_SYSTEM),
        (("ai agent", "agent with memory", "agent architecture"), ProjectDomain.AI_AGENT),
        (("machine learning", "model train", "neural"), ProjectDomain.AI_APPLICATION),
        (("mobile", "android", "ios", "flutter", "react native"), ProjectDomain.MOBILE_APP),
        (("desktop", "electron", "tauri"), ProjectDomain.DESKTOP_APP),
        (("enterprise", "role", "permission", "sso"), ProjectDomain.ENTERPRISE_SOFTWARE),
        (("api", "endpoint", "rest", "graphql"), ProjectDomain.BACKEND_API),
        (("database", "schema", "etl", "pipeline"), ProjectDomain.DATA_SYSTEM),
        (("cloud", "kubernetes", "terraform", "devops", "ci/cd"), ProjectDomain.CLOUD_DEVOPS),
        (("website", "web app", "frontend", "full stack", "fullstack", "saas"), ProjectDomain.WEB_APP),
    ]
    for keywords, domain in rules:
        if any(k in text for k in keywords):
            return domain
    return ProjectDomain.GENERAL


def _default_module(domain: ProjectDomain) -> CABERModule:
    if domain == ProjectDomain.ARCHITECTURE_3D:
        return CABERModule.BUILDING
    if domain in (ProjectDomain.RESEARCH, ProjectDomain.SIMULATION):
        return CABERModule.PROBLEM_SOLVING
    if domain in (
        ProjectDomain.WEB_APP,
        ProjectDomain.MOBILE_APP,
        ProjectDomain.DESKTOP_APP,
        ProjectDomain.ENTERPRISE_SOFTWARE,
        ProjectDomain.BACKEND_API,
        ProjectDomain.AI_APPLICATION,
        ProjectDomain.AI_AGENT,
        ProjectDomain.MULTI_AGENT_SYSTEM,
        ProjectDomain.DATA_SYSTEM,
        ProjectDomain.CLOUD_DEVOPS,
        ProjectDomain.DESIGN_SYSTEM,
    ):
        return CABERModule.APPLICATION
    return CABERModule.PLATFORM
