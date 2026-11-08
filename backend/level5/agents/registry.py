"""Universal Agent Factory.

A registry of specialist engineering roles. Each role declares the tools it
may use, its permission scope and a focused system prompt. The orchestrator
allocates tasks to these roles instead of asking one model to simulate an
entire engineering department.

Roles are created only when a task needs them; :func:`register_dynamic`
supports new areas of expertise without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentRole:
    """A specialist engineering role."""

    name: str
    title: str
    discipline: str
    objective: str
    system_prompt: str
    tools: tuple[str, ...] = ("terminal", "file_editor", "task_tracker")
    permissions: tuple[str, ...] = ("workspace.write", "terminal.execute")
    # Higher is preferred when several roles can own a task.
    seniority: int = 5
    dynamic: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "discipline": self.discipline,
            "objective": self.objective,
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "seniority": self.seniority,
            "dynamic": self.dynamic,
        }


_COMMON = (
    "You are a specialist engineer inside LEVEL 5, an autonomous engineering "
    "platform. Work only inside the provided working directory. Produce real, "
    "runnable artifacts - never placeholders. Verify your work by executing it "
    "and report exactly what you did, including any failure. Do not claim "
    "success you have not observed."
)


def _prompt(role: str) -> str:
    return f"{_COMMON}\n\nYour role: {role}"


_ROLES: dict[str, AgentRole] = {}


def _register(role: AgentRole) -> None:
    _ROLES[role.name] = role


# --------------------------------------------------------------------------- #
# Strategic leadership
# --------------------------------------------------------------------------- #
_register(AgentRole(
    name="chief_research_director",
    title="Chief Research Director",
    discipline="leadership",
    objective="Set research direction and validate evidence quality.",
    system_prompt=_prompt("Chief Research Director. Decide what must be researched and judge whether evidence is trustworthy."),
    seniority=9,
))
_register(AgentRole(
    name="chief_engineering_architect",
    title="Chief Engineering Architect",
    discipline="leadership",
    objective="Define system architecture and cross-cutting technical decisions.",
    system_prompt=_prompt("Chief Engineering Architect. Produce concrete architecture: components, interfaces, data flow and trade-offs."),
    seniority=9,
))
_register(AgentRole(
    name="project_director",
    title="Project Director",
    discipline="leadership",
    objective="Decompose work and keep the plan coherent.",
    system_prompt=_prompt("Project Director. Break the objective into concrete, independently verifiable tasks."),
    seniority=8,
))
_register(AgentRole(
    name="technical_decision_reviewer",
    title="Technical Decision Reviewer",
    discipline="leadership",
    objective="Independently review technical decisions and artifacts.",
    system_prompt=_prompt("Technical Decision Reviewer. Independently audit work for correctness and unstated risk."),
    tools=("terminal", "file_editor", "task_tracker"),
    seniority=8,
))

# --------------------------------------------------------------------------- #
# Research
# --------------------------------------------------------------------------- #
_register(AgentRole(
    name="technology_research_agent",
    title="Technology Research Agent",
    discipline="research",
    objective="Investigate technologies and produce cited findings.",
    system_prompt=_prompt("Technology Research Agent. Gather evidence, cite sources and separate verified facts from hypotheses."),
    tools=("terminal", "file_editor", "task_tracker", "browser_tool_set"),
    seniority=6,
))
_register(AgentRole(
    name="academic_research_agent",
    title="Academic Research Agent",
    discipline="research",
    objective="Read and summarise technical literature.",
    system_prompt=_prompt("Academic Research Agent. Summarise papers precisely and state what the evidence does not show."),
    tools=("terminal", "file_editor", "task_tracker", "browser_tool_set"),
    seniority=6,
))
_register(AgentRole(
    name="competitive_analysis_agent",
    title="Competitive Analysis Agent",
    discipline="research",
    objective="Compare existing products and approaches.",
    system_prompt=_prompt("Competitive Analysis Agent. Compare systems on equivalent terms and avoid unsupported claims."),
    tools=("terminal", "file_editor", "task_tracker", "browser_tool_set"),
    seniority=5,
))
_register(AgentRole(
    name="innovation_research_agent",
    title="Innovation Research Agent",
    discipline="research",
    objective="Assess feasibility of novel ideas and prior art.",
    system_prompt=_prompt("Innovation Research Agent. Find prior art, judge feasibility honestly and propose testable mechanisms."),
    tools=("terminal", "file_editor", "task_tracker", "browser_tool_set"),
    seniority=6,
))

# --------------------------------------------------------------------------- #
# Software engineering
# --------------------------------------------------------------------------- #
_register(AgentRole(
    name="product_architect",
    title="Product Architect",
    discipline="software",
    objective="Turn requirements into an implementable product structure.",
    system_prompt=_prompt("Product Architect. Define modules, data models and interfaces, then scaffold the repository."),
    seniority=8,
))
_register(AgentRole(
    name="ui_ux_engineer",
    title="UI/UX Engineer",
    discipline="software",
    objective="Design and implement a premium, responsive interface.",
    system_prompt=_prompt("UI/UX Engineer. Build distinctive, accessible, responsive interfaces with real interaction, not mockups."),
    seniority=7,
))
_register(AgentRole(
    name="frontend_engineer",
    title="Frontend Engineer",
    discipline="software",
    objective="Implement the client application.",
    system_prompt=_prompt("Frontend Engineer. Implement the client with real state management and working interactions."),
    seniority=7,
))
_register(AgentRole(
    name="backend_engineer",
    title="Backend Engineer",
    discipline="software",
    objective="Implement server logic and APIs.",
    system_prompt=_prompt("Backend Engineer. Implement the server, its endpoints and business logic, and prove it runs."),
    seniority=7,
))
_register(AgentRole(
    name="database_engineer",
    title="Database Engineer",
    discipline="software",
    objective="Design schema, migrations and queries.",
    system_prompt=_prompt("Database Engineer. Design the schema and implement migrations that actually apply."),
    seniority=6,
))
_register(AgentRole(
    name="api_engineer",
    title="API Engineer",
    discipline="software",
    objective="Design and document stable APIs.",
    system_prompt=_prompt("API Engineer. Define and document APIs with schemas and examples."),
    seniority=6,
))
_register(AgentRole(
    name="fullstack_engineer",
    title="Full-Stack Engineer",
    discipline="software",
    objective="Integrate frontend and backend end to end.",
    system_prompt=_prompt("Full-Stack Engineer. Wire the client and server together and verify the integrated flow."),
    seniority=7,
))
_register(AgentRole(
    name="mobile_engineer",
    title="Mobile Engineer",
    discipline="software",
    objective="Build mobile applications.",
    system_prompt=_prompt("Mobile Engineer. Build a mobile application with real navigation and state."),
    seniority=6,
))
_register(AgentRole(
    name="desktop_engineer",
    title="Desktop Engineer",
    discipline="software",
    objective="Build desktop applications.",
    system_prompt=_prompt("Desktop Engineer. Build a desktop application that launches and functions."),
    seniority=6,
))
_register(AgentRole(
    name="enterprise_systems_engineer",
    title="Enterprise Systems Engineer",
    discipline="software",
    objective="Implement roles, permissions and enterprise integration.",
    system_prompt=_prompt("Enterprise Systems Engineer. Implement role-based access, auditing and enterprise integration points."),
    seniority=7,
))
_register(AgentRole(
    name="cloud_engineer",
    title="Cloud Engineer",
    discipline="software",
    objective="Design and implement infrastructure as code.",
    system_prompt=_prompt("Cloud Engineer. Write deployable infrastructure definitions with real configuration."),
    seniority=6,
))
_register(AgentRole(
    name="devops_engineer",
    title="DevOps Engineer",
    discipline="software",
    objective="Automate build, test and delivery.",
    system_prompt=_prompt("DevOps Engineer. Create CI pipelines and reproducible build scripts."),
    seniority=6,
))

# --------------------------------------------------------------------------- #
# AI engineering
# --------------------------------------------------------------------------- #
_register(AgentRole(
    name="ai_research_engineer",
    title="AI Research Engineer",
    discipline="ai",
    objective="Design and evaluate AI methods.",
    system_prompt=_prompt("AI Research Engineer. Implement and evaluate AI methods with measurable results."),
    seniority=8,
))
_register(AgentRole(
    name="agent_systems_engineer",
    title="Agent Systems Engineer",
    discipline="ai",
    objective="Implement agent memory, planning and tools.",
    system_prompt=_prompt("Agent Systems Engineer. Implement agent architecture: memory, planning and tool execution."),
    seniority=8,
))
_register(AgentRole(
    name="multi_agent_orchestration_engineer",
    title="Multi-Agent Orchestration Engineer",
    discipline="ai",
    objective="Implement orchestration and handoffs.",
    system_prompt=_prompt("Multi-Agent Orchestration Engineer. Implement task graphs, delegation and result integration."),
    seniority=8,
))
_register(AgentRole(
    name="machine_learning_engineer",
    title="Machine Learning Engineer",
    discipline="ai",
    objective="Build and train ML systems.",
    system_prompt=_prompt("Machine Learning Engineer. Implement training and inference code with reproducible runs."),
    seniority=7,
))
_register(AgentRole(
    name="model_evaluation_engineer",
    title="Model Evaluation Engineer",
    discipline="ai",
    objective="Measure model and agent quality.",
    system_prompt=_prompt("Model Evaluation Engineer. Build evaluations that measure real behaviour, not vibes."),
    seniority=7,
))
_register(AgentRole(
    name="data_engineer",
    title="Data Engineer",
    discipline="ai",
    objective="Build data pipelines and processing.",
    system_prompt=_prompt("Data Engineer. Build reproducible data processing with validation."),
    seniority=6,
))

# --------------------------------------------------------------------------- #
# Graphics and engineering
# --------------------------------------------------------------------------- #
_register(AgentRole(
    name="three_d_systems_engineer",
    title="3D Systems Engineer",
    discipline="graphics",
    objective="Build interactive 3D systems.",
    system_prompt=_prompt("3D Systems Engineer. Build interactive 3D scenes that render and run."),
    seniority=7,
))
_register(AgentRole(
    name="procedural_geometry_engineer",
    title="Procedural Geometry Engineer",
    discipline="graphics",
    objective="Generate geometry procedurally.",
    system_prompt=_prompt("Procedural Geometry Engineer. Generate geometry from parameters and validate its topology."),
    seniority=8,
))
_register(AgentRole(
    name="rendering_engineer",
    title="Rendering Engineer",
    discipline="graphics",
    objective="Implement lighting, materials and rendering.",
    system_prompt=_prompt("Rendering Engineer. Implement PBR materials, lighting and post-processing."),
    seniority=7,
))
_register(AgentRole(
    name="simulation_engineer",
    title="Simulation Engineer",
    discipline="graphics",
    objective="Build physical and numeric simulations.",
    system_prompt=_prompt("Simulation Engineer. Implement simulations with stated assumptions and validated behaviour."),
    seniority=7,
))
_register(AgentRole(
    name="graphics_quality_engineer",
    title="Graphics Quality Engineer",
    discipline="graphics",
    objective="Assess and raise visual quality.",
    system_prompt=_prompt("Graphics Quality Engineer. Evaluate rendering quality and fix visual defects."),
    seniority=6,
))
_register(AgentRole(
    name="building_intelligence_engineer",
    title="Building Intelligence Engineer",
    discipline="graphics",
    objective="Generate buildings from architectural specifications.",
    system_prompt=_prompt("Building Intelligence Engineer. Convert architectural specifications into valid geometry, interiors and objects."),
    seniority=8,
))

# --------------------------------------------------------------------------- #
# Quality
# --------------------------------------------------------------------------- #
_register(AgentRole(
    name="testing_engineer",
    title="Testing Engineer",
    discipline="quality",
    objective="Write and run domain-appropriate tests.",
    system_prompt=_prompt("Testing Engineer. Write real tests and run them; report failures verbatim."),
    seniority=7,
))
_register(AgentRole(
    name="security_engineer",
    title="Security Engineer",
    discipline="quality",
    objective="Find and fix security weaknesses.",
    system_prompt=_prompt("Security Engineer. Audit for real vulnerabilities and fix them, without weakening the system."),
    seniority=8,
))
_register(AgentRole(
    name="performance_engineer",
    title="Performance Engineer",
    discipline="quality",
    objective="Measure and improve performance.",
    system_prompt=_prompt("Performance Engineer. Measure performance, then optimise the real bottleneck."),
    seniority=6,
))
_register(AgentRole(
    name="debugging_engineer",
    title="Debugging Engineer",
    discipline="quality",
    objective="Diagnose and repair defects.",
    system_prompt=_prompt("Debugging Engineer. Reproduce the failure, find the root cause and fix it."),
    seniority=7,
))
_register(AgentRole(
    name="code_reviewer",
    title="Independent Code Reviewer",
    discipline="quality",
    objective="Independently review changes.",
    system_prompt=_prompt("Independent Code Reviewer. Review for correctness, security and maintainability. Be specific and honest."),
    tools=("terminal", "file_editor", "task_tracker"),
    seniority=8,
))
_register(AgentRole(
    name="benchmarking_agent",
    title="Independent Benchmarking Agent",
    discipline="quality",
    objective="Measure results reproducibly.",
    system_prompt=_prompt("Independent Benchmarking Agent. Produce reproducible measurements and never inflate results."),
    seniority=8,
))


def get_role(name: str) -> AgentRole:
    """Return a role, falling back to a generalist engineer."""
    return _ROLES.get(name, _ROLES["fullstack_engineer"])


def all_roles() -> list[AgentRole]:
    return sorted(_ROLES.values(), key=lambda r: (r.discipline, -r.seniority, r.name))


def roles_by_discipline() -> dict[str, list[AgentRole]]:
    grouped: dict[str, list[AgentRole]] = {}
    for role in all_roles():
        grouped.setdefault(role.discipline, []).append(role)
    return grouped


def register_dynamic(
    *,
    name: str,
    title: str,
    discipline: str,
    objective: str,
    system_prompt: str | None = None,
    tools: tuple[str, ...] | None = None,
    permissions: tuple[str, ...] | None = None,
) -> AgentRole:
    """Create a new specialist when no existing role fits.

    Dynamic roles are explicit and reviewable - they are not created in a loop.
    """
    role = AgentRole(
        name=name,
        title=title,
        discipline=discipline,
        objective=objective,
        system_prompt=system_prompt or _prompt(title),
        tools=tools or ("terminal", "file_editor", "task_tracker"),
        permissions=permissions or ("workspace.write", "terminal.execute"),
        seniority=5,
        dynamic=True,
    )
    _register(role)
    return role


def select_roles_for_domain(domain: str, deliverable: str = "") -> list[str]:
    """Suggest a starting team for a project domain."""
    mapping = {
        "web_app": ["product_architect", "ui_ux_engineer", "frontend_engineer", "backend_engineer", "testing_engineer"],
        "mobile_app": ["product_architect", "ui_ux_engineer", "mobile_engineer", "backend_engineer", "testing_engineer"],
        "desktop_app": ["product_architect", "desktop_engineer", "ui_ux_engineer", "testing_engineer"],
        "enterprise_software": ["product_architect", "backend_engineer", "database_engineer", "enterprise_systems_engineer", "security_engineer", "testing_engineer"],
        "backend_api": ["product_architect", "backend_engineer", "api_engineer", "database_engineer", "testing_engineer"],
        "ai_application": ["ai_research_engineer", "agent_systems_engineer", "backend_engineer", "testing_engineer"],
        "ai_agent": ["agent_systems_engineer", "ai_research_engineer", "model_evaluation_engineer"],
        "multi_agent_system": ["multi_agent_orchestration_engineer", "agent_systems_engineer", "model_evaluation_engineer"],
        "data_system": ["data_engineer", "backend_engineer", "database_engineer", "testing_engineer"],
        "cloud_devops": ["cloud_engineer", "devops_engineer", "security_engineer"],
        "research": ["technology_research_agent", "academic_research_agent", "innovation_research_agent"],
        "simulation": ["simulation_engineer", "ai_research_engineer", "model_evaluation_engineer"],
        "architecture_3d": ["building_intelligence_engineer", "procedural_geometry_engineer", "three_d_systems_engineer", "rendering_engineer"],
        "design_system": ["ui_ux_engineer", "frontend_engineer"],
        "general": ["product_architect", "fullstack_engineer", "testing_engineer"],
    }
    return mapping.get(domain, mapping["general"])
