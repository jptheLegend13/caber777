# LEVEL 5 — consolidated requirements

This is the retained requirements record for the LEVEL 5 platform. It condenses
the founding directives into one document so the intended scope survives across
sessions. It describes **requirements and intended scope**; what is actually
built and verified is tracked separately in `docs/ROADMAP.md` and `docs/RUNS.md`.
Where the two disagree, the roadmap and runs log win.

## 1. Vision

LEVEL 5 is an autonomous universal research, engineering and technical creation
intelligence. A user describes an intended result in text or voice; LEVEL 5
understands it, researches it, plans it, designs it, builds it, executes it,
tests it, evaluates it, corrects defects and delivers the actual result.

It is explicitly **not** a chat wrapper and **not** a static mock-up. Agents must
perform real, authorised tool execution.

## 2. Technical creation scope

The platform is required to be extensible across domains rather than limited to
a fixed template list. Intended coverage:

- **Software** — websites, web/mobile/desktop/enterprise apps, full-stack
  systems, frontends, backends, databases, APIs, authentication, payments,
  SaaS, developer platforms, cloud services, DevOps, distributed and data
  systems, automation.
- **AI** — AI apps, assistants, agents, multi-agent systems, orchestration,
  retrieval, knowledge systems, model integration, ML, evaluation, reasoning.
- **Design** — UI/UX, design systems, component libraries, responsive
  interfaces, prototypes, enterprise interfaces.
- **Engineering and research** — simulations, mathematical models, scientific
  computing, data analysis, algorithms, optimisation, technical documentation,
  original innovations.
- **Advanced graphics** — 3D applications, interactive environments,
  procedural geometry, rendering, building generation, game environments.

New categories are supported by defining a specialist workflow, not by refusing
anything outside a predefined template.

## 3. The three CABER intelligences

LEVEL 5 is architected to build three specialised intelligences that share one
platform:

- **A — Application Creation Intelligence.** Creates complete technical
  applications and digital products.
- **B — Problem-Solving Intelligence.** Investigates, models, simulates,
  verifies and explains technical and real-world problems.
- **C — Building Creation Intelligence.** Creates buildings and architectural
  environments from the three-block specification (building/design/spaces;
  objects/components; position/actions/behaviours) and renders them as an
  interactive 3D environment.

They must share common infrastructure (account/project system, command
interface, storage, research, agent execution, file management, permissions,
version history, testing) rather than being three disconnected applications.

## 4. Intelligence independence (permanent requirement)

- The model configured in the OpenHands development environment is a temporary
  development tool and must not become a required intelligence provider in the
  product.
- External AI APIs must not be mandatory; they are optional, replaceable
  development assistants, off by default.
- Never hard-code a provider into the intelligence architecture.
- Never automatically fall back to an external model when the internal model
  fails.
- Internal (self-hosted) inference is the production target.
- A self-hosted third-party model must never be described as a model trained
  entirely by us. **No foundation model has been trained.**

Full architecture and the staged model roadmap: `docs/ARCHITECTURE-INDEPENDENCE.md`.

## 5. Engineering orchestrator

The orchestrator translates requirements into a dependency-aware task graph and
runs:

```
REQUEST → UNDERSTANDING → RESEARCH → SPECIFICATION → ARCHITECTURE
→ TASK DECOMPOSITION → AGENT ALLOCATION → TOOL SELECTION → EXECUTION
→ INTEGRATION → TESTING → REVIEW → REPAIR → DELIVERY
```

Every task carries an id, objective, inputs, outputs, dependencies, assigned
agent, required tools, permissions, acceptance criteria, state, completion
evidence and error information. Parallel work, handoffs, checkpoints, resumption,
retries, cancellation and independent review are required.

## 6. Agents

Specialist roles across strategic, research, software, AI, graphics/engineering
and quality disciplines, with additional specialists created dynamically when a
real task needs them. One model must not pretend to be the whole department.

## 7. Verification

Independent verification is required for every project, with domain-appropriate
tests (unit, integration, end-to-end, browser, API, database, security,
performance for software; output accuracy, tool correctness, hallucination
checks and source validity for AI; geometry, room connections, placement and
dimensions for buildings). A feature is complete only when its verification
passes — never merely because files were generated.

## 8. Security and governance

Explicit per-agent capabilities and permissions, sandboxed execution, project
isolation, credential protection, audit logs, resource quotas, timeouts, and
approval before destructive, paid, deployment or irreversible actions. Secrets
never appear in frontend code or the repository.

## 9. Milestones

See `docs/ROADMAP.md` for the authoritative, per-item status. Milestone summary:

1. Working engineering platform foundation.
2. Universal agent orchestration.
3. Universal creation capability.
4. Problem-Solving Intelligence.
5. Building Creation Intelligence.
6. Integrated CABER.
7. Continuous research and improvement.
8. Intelligence independence (permanent requirement).

## 10. First end-to-end acceptance test

Build a complete technical product through LEVEL 5, using the request:

> "Build an enterprise-grade task-management application with an original
> premium UI/UX, responsive frontend, backend, authentication, database, task
> management, user roles, analytics, API documentation and automated tests."

LEVEL 5 must understand it, produce requirements, research, produce an
architecture, allocate real tasks, create files, build frontend and backend,
create the database, integrate, run it, run tests, find and correct errors,
produce a working preview and report actual results. Problem-solving and
building-generation demonstrations are also required.

## 11. Honesty rules (binding)

- Do not claim a system is verified without tests.
- Do not fabricate research, benchmark results or completed tasks.
- Do not report imaginary agent activity.
- Distinguish what is designed/simulated from what is manufactured/verified.
- No competitive superiority claim without equivalent-condition benchmarks.
