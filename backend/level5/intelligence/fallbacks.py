"""Model-free understanding and planning.

LEVEL 5 must keep operating when no inference backend is available. These
functions are the deterministic core of that guarantee: they turn a request
into a structured :class:`Specification` and a :class:`TaskGraph` using rules,
keyword classification and per-domain task templates — no model, no network.

They are also used as the fallback path when a model call fails, so a broken
or absent model degrades the platform to deterministic operation instead of
stopping it. The output is deliberately conservative and honest: inferred
requirements are labelled ``inferred``, and the plan is a well-formed,
dependency-ordered engineering plan for the detected domain.
"""

from __future__ import annotations

from level5.agents.registry import select_roles_for_domain
from level5.intelligence.understanding import _infer_domain, _default_module
from level5.models import (
    AcceptanceCriterion,
    Constraint,
    ProjectDomain,
    Requirement,
    Specification,
    Task,
    TaskGraph,
)


def spec_from_request(request: str) -> Specification:
    """Build a structured specification from a request without a model.

    Domain and module come from the same keyword rules the model path falls
    back to, so behaviour is consistent whether or not a model is present.
    """
    request = request.strip()
    domain = _infer_domain(request)
    module = _default_module(domain)
    deliverable = _deliverable_for(domain, request)
    return Specification(
        intent=request[:200] or "Implement the requested deliverable.",
        deliverable=deliverable,
        domain=domain,
        caber_module=module,
        summary=(
            f"Deterministic plan for a {domain.value.replace('_', ' ')} "
            f"deliverable. Produced without a language model."
        ),
        requirements=[
            Requirement(
                text=request or deliverable,
                origin="user",
                category="functional",
                priority="must",
                acceptance_criteria=[f"The deliverable exists: {deliverable}"],
            ),
            Requirement(
                text=(
                    "The deliverable runs in its target environment and passes "
                    "an automated test or build check."
                ),
                origin="inferred",
                category="quality",
                priority="must",
                acceptance_criteria=["An automated check passes."],
            ),
        ],
        constraints=[
            Constraint(
                text="Produced by the deterministic (model-free) planner.",
                kind="technical",
                origin="inferred",
            )
        ],
        acceptance_criteria=[
            AcceptanceCriterion(
                statement=f"The deliverable is produced: {deliverable}",
                verification_method="automated_test",
            ),
            AcceptanceCriterion(
                statement="The project's automated checks pass.",
                verification_method="automated_test",
            ),
        ],
        assumptions=[
            "No language model was available; a conventional engineering plan "
            "was generated from the request."
        ],
        clarifications_needed=False,
        technology_choices=_default_technology(domain),
        research_needed=False,
        research_questions=[],
    )


def _deliverable_for(domain: ProjectDomain, request: str) -> str:
    labels = {
        ProjectDomain.WEB_APP: "a working web application",
        ProjectDomain.MOBILE_APP: "a working mobile application",
        ProjectDomain.DESKTOP_APP: "a working desktop application",
        ProjectDomain.ENTERPRISE_SOFTWARE: "a working enterprise application",
        ProjectDomain.BACKEND_API: "a working backend API",
        ProjectDomain.AI_APPLICATION: "a working AI application",
        ProjectDomain.AI_AGENT: "a working AI agent",
        ProjectDomain.MULTI_AGENT_SYSTEM: "a working multi-agent system",
        ProjectDomain.DATA_SYSTEM: "a working data system",
        ProjectDomain.CLOUD_DEVOPS: "a working cloud/DevOps configuration",
        ProjectDomain.RESEARCH: "a cited research report",
        ProjectDomain.SIMULATION: "a working simulation with verified results",
        ProjectDomain.ARCHITECTURE_3D: "an interactive 3D building environment",
        ProjectDomain.DESIGN_SYSTEM: "a working design system and UI",
    }
    base = labels.get(domain, "working software")
    return f"{base} for: {request[:120]}" if request else base


def _default_technology(domain: ProjectDomain) -> list[dict[str, str]]:
    choices = {
        ProjectDomain.WEB_APP: [
            ("frontend", "React + TypeScript", "conventional, well-supported stack"),
            ("backend", "FastAPI (Python)", "async, typed, easy to test"),
        ],
        ProjectDomain.BACKEND_API: [
            ("backend", "FastAPI (Python)", "async, typed, easy to test"),
            ("database", "SQLite for local, PostgreSQL for production", "portable"),
        ],
        ProjectDomain.MOBILE_APP: [
            ("mobile", "React Native", "shared language with the web stack"),
        ],
        ProjectDomain.AI_AGENT: [
            ("runtime", "Python agent loop", "explicit control over the agent loop"),
        ],
    }
    return [
        {"area": area, "choice": choice, "rationale": rationale}
        for area, choice, rationale in choices.get(domain, [])
    ]


# -- task-graph templates ------------------------------------------------ #
# Each template is an ordered list of (key, title, objective, role, phase,
# depends_on, outputs). It is a conventional engineering plan for the domain,
# not a model guess.
_TEMPLATES: dict[ProjectDomain, list[tuple]] = {
    ProjectDomain.WEB_APP: [
        ("scaffold", "Scaffold the project", "Create the project skeleton, package files and a README.", "product_architect", "architecture", [], ["README.md"]),
        ("backend", "Implement the backend", "Implement the server, routes and business logic.", "backend_engineer", "implementation", ["scaffold"], ["backend"]),
        ("frontend", "Implement the frontend", "Implement the UI and connect it to the backend.", "frontend_engineer", "implementation", ["scaffold"], ["frontend"]),
        ("integrate", "Integrate frontend and backend", "Wire the frontend to the real backend and fix the seams.", "fullstack_engineer", "integration", ["backend", "frontend"], []),
        ("tests", "Write automated tests", "Write and run automated tests for the application.", "testing_engineer", "testing", ["integrate"], ["tests"]),
        ("review", "Independent review", "Review the code against the requirements without modifying it.", "code_reviewer", "review", ["tests"], ["REVIEW.md"]),
    ],
    ProjectDomain.BACKEND_API: [
        ("scaffold", "Scaffold the API project", "Create the project skeleton and packaging.", "product_architect", "architecture", [], ["README.md"]),
        ("database", "Design and create the database", "Create the schema and migrations.", "database_engineer", "implementation", ["scaffold"], ["migrations"]),
        ("api", "Implement the API", "Implement the endpoints and business logic.", "api_engineer", "implementation", ["database"], ["api"]),
        ("tests", "Write API tests", "Write and run automated API tests.", "testing_engineer", "testing", ["api"], ["tests"]),
        ("review", "Independent review", "Review the API against the requirements.", "code_reviewer", "review", ["tests"], ["REVIEW.md"]),
    ],
    ProjectDomain.AI_AGENT: [
        ("scaffold", "Scaffold the agent project", "Create the project skeleton and packaging.", "product_architect", "architecture", [], ["README.md"]),
        ("tools", "Implement the agent tools", "Implement the tools the agent can call.", "agent_systems_engineer", "implementation", ["scaffold"], ["tools"]),
        ("loop", "Implement the agent loop", "Implement planning, tool execution and memory.", "agent_systems_engineer", "implementation", ["tools"], ["agent"]),
        ("tests", "Write agent tests", "Write and run tests for the agent and its tools.", "model_evaluation_engineer", "testing", ["loop"], ["tests"]),
        ("review", "Independent review", "Review the agent against the requirements.", "code_reviewer", "review", ["tests"], ["REVIEW.md"]),
    ],
    ProjectDomain.RESEARCH: [
        ("gather", "Gather sources", "Retrieve relevant sources for the question.", "technology_research_agent", "research", [], ["sources.json"]),
        ("analyse", "Analyse the evidence", "Classify and analyse the retrieved evidence.", "academic_research_agent", "research", ["gather"], ["analysis.md"]),
        ("report", "Write the cited report", "Produce a report that distinguishes verified findings from hypotheses.", "innovation_research_agent", "documentation", ["analyse"], ["REPORT.md"]),
        ("verify", "Verify the report", "Independently check that every claim traces to a source and that no finding is overstated.", "model_evaluation_engineer", "review", ["report"], ["VERIFICATION.md"]),
    ],
    ProjectDomain.ARCHITECTURE_3D: [
        ("brief", "Establish the building brief", "Capture the building program and dimensions.", "building_intelligence_engineer", "architecture", [], ["brief.json"]),
        ("geometry", "Generate the geometry", "Generate rooms, walls, openings and objects.", "procedural_geometry_engineer", "implementation", ["brief"], ["scene.json"]),
        ("render", "Assemble the interactive scene", "Assemble the renderable scene and lighting.", "rendering_engineer", "integration", ["geometry"], ["index.html"]),
        ("validate", "Validate the design", "Validate geometry, dimensions and room connections.", "three_d_systems_engineer", "testing", ["render"], ["validation.json"]),
    ],
}


def _generic_template(domain: ProjectDomain) -> list[tuple]:
    roles = select_roles_for_domain(domain.value)
    impl_roles = [r for r in roles if "engineer" in r] or ["fullstack_engineer"]
    steps: list[tuple] = [
        ("scaffold", "Scaffold the project", "Create the project skeleton and packaging.", roles[0], "architecture", [], ["README.md"]),
    ]
    prev = ["scaffold"]
    for idx, role in enumerate(impl_roles[:3]):
        key = f"implement_{idx + 1}"
        steps.append(
            (key, f"Implement ({role.replace('_', ' ')})", "Implement this part of the deliverable.", role, "implementation", list(prev), [])
        )
        prev = [key]
    steps.append(("tests", "Write automated tests", "Write and run automated tests for the deliverable.", "testing_engineer", "testing", prev, ["tests"]))
    steps.append(("review", "Independent review", "Review the work against the requirements.", "code_reviewer", "review", ["tests"], ["REVIEW.md"]))
    return steps


def graph_from_spec(spec: Specification) -> TaskGraph:
    """Build a dependency-ordered task graph for the specification's domain."""
    template = _TEMPLATES.get(spec.domain) or _generic_template(spec.domain)
    key_to_task: dict[str, Task] = {}
    for key, title, objective, role, phase, deps, outputs in template:
        task = Task(
            title=title,
            objective=f"{objective} Deliverable: {spec.deliverable}",
            agent_role=role,
            phase=phase,
            outputs=list(outputs),
            tools=["terminal", "file_editor", "task_tracker"],
            acceptance_criteria=["The task's output exists and is correct."],
        )
        task.dependencies = [key_to_task[d].id for d in deps if d in key_to_task]
        key_to_task[key] = task
    return TaskGraph(tasks=list(key_to_task.values()))
