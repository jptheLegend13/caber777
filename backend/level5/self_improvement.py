"""Controlled self-improvement (Milestone 7).

Loop: DETECT WEAKNESS -> RESEARCH -> HYPOTHESIS -> DESIGN -> (implement in
isolation) -> TEST -> COMPARE -> INDEPENDENT REVIEW -> ACCEPT OR REJECT ->
RECORD.

Scope and safety, enforced in code rather than promised in prose:

- Weaknesses are detected from **real** benchmark records, not invented.
- Proposals are recorded, never auto-applied. This module cannot modify the
  running system. A proposal must carry the tests and the before/after
  comparison that would justify it, and a human or a review task decides.
- Proposals that would weaken security, widen permissions, disable checks or
  delete tests are rejected outright by `screen_proposal`.
- Recursive agent creation is not permitted: proposals cannot create new agents
  as a side effect, and dynamic roles are only ever created explicitly by the
  registry.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from level5.llm.client import LLMClient, get_llm_client
from level5.storage.store import get_store

logger = logging.getLogger("level5.improvement")

# Proposals matching any of these are rejected before they are ever recorded.
_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\b(disabl|bypass|skip|remove|delete|weaken)\w*\b[^.]{0,40}\b(security|auth|permission|sandbox|check|test|validation|guardrail)", "weakens a safety control"),
    (r"\b(grant|widen|escalate|elevate)\w*\b[^.]{0,40}\b(permission|privilege|access|scope|role)", "widens permissions"),
    (r"\b(ignore|disable)\w*\b[^.]{0,30}\b(confirmation|approval|policy)", "removes an approval gate"),
    (r"\b(auto[- ]?apply|self[- ]?modify|rewrite)\w*\b[^.]{0,40}\b(production|primary|core|live)", "applies self-modification to the running system"),
    (r"\bexpose\b[^.]{0,30}\b(secret|credential|api[- ]?key|token)", "exposes credentials"),
    (r"\bcreate\b[^.]{0,30}\b(agents?|roles?)\b[^.]{0,20}\b(recursiv|automatically|in a loop)", "uncontrolled agent creation"),
]


@dataclass
class Weakness:
    """A measured shortfall in LEVEL 5's own performance."""

    id: str
    area: str
    statement: str
    metric: str
    value: float
    sample_size: int
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "area": self.area,
            "statement": self.statement,
            "metric": self.metric,
            "value": self.value,
            "sample_size": self.sample_size,
            "evidence": self.evidence,
        }


@dataclass
class Proposal:
    id: str
    weakness_id: str
    area: str
    hypothesis: str
    change: str
    target_files: list[str]
    required_tests: list[str]
    comparison_plan: str
    risk: str
    created_at: str
    status: str = "proposed"  # proposed | rejected | accepted
    rejection_reason: str | None = None
    review: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "weakness_id": self.weakness_id,
            "area": self.area,
            "hypothesis": self.hypothesis,
            "change": self.change,
            "target_files": self.target_files,
            "required_tests": self.required_tests,
            "comparison_plan": self.comparison_plan,
            "risk": self.risk,
            "created_at": self.created_at,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "review": self.review,
        }


class SelfImprovementEngine:
    """Detects weaknesses and produces screened, reviewable proposals."""

    def __init__(self, llm: LLMClient | None = None, store=None) -> None:
        self.llm = llm or get_llm_client()
        self.store = store or get_store()

    # -- detection ---------------------------------------------------------- #
    async def detect_weaknesses(self, *, min_samples: int = 3) -> list[Weakness]:
        """Find measured shortfalls from recorded benchmark runs."""
        records = await self.store.list_benchmarks(limit=500)
        if len(records) < min_samples:
            return []

        weaknesses: list[Weakness] = []

        by_domain: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_domain.setdefault(str(record.get("domain", "general")), []).append(record)

        for domain, group in by_domain.items():
            if len(group) < min_samples:
                continue
            failures = sum(int(r.get("tasks_failed") or 0) for r in group)
            total = sum(int(r.get("tasks_total") or 0) for r in group)
            if total and failures / total >= 0.2:
                rate = round(failures / total, 3)
                weaknesses.append(
                    Weakness(
                        id=f"weak_{uuid.uuid4().hex[:8]}",
                        area="task_execution",
                        statement=(
                            f"{rate:.0%} of tasks failed for domain '{domain}' across "
                            f"{len(group)} runs."
                        ),
                        metric="task_failure_rate",
                        value=rate,
                        sample_size=total,
                        evidence=[str(r.get("project_id")) for r in group[-5:]],
                    )
                )

        criteria_rates = [
            float(r["criteria_rate"])
            for r in records
            if r.get("criteria_rate") is not None
        ]
        if len(criteria_rates) >= min_samples:
            average = sum(criteria_rates) / len(criteria_rates)
            if average < 0.7:
                weaknesses.append(
                    Weakness(
                        id=f"weak_{uuid.uuid4().hex[:8]}",
                        area="verification",
                        statement=(
                            f"Average acceptance-criteria satisfaction is {average:.0%} "
                            f"across {len(criteria_rates)} measured runs."
                        ),
                        metric="criteria_rate",
                        value=round(average, 3),
                        sample_size=len(criteria_rates),
                        evidence=[],
                    )
                )

        test_rates = [
            float(r["test_pass_rate"]) for r in records if r.get("test_pass_rate") is not None
        ]
        if len(test_rates) >= min_samples:
            average = sum(test_rates) / len(test_rates)
            if average < 0.8:
                weaknesses.append(
                    Weakness(
                        id=f"weak_{uuid.uuid4().hex[:8]}",
                        area="testing",
                        statement=(
                            f"Average agent-run test pass rate is {average:.0%} across "
                            f"{len(test_rates)} measured runs."
                        ),
                        metric="test_pass_rate",
                        value=round(average, 3),
                        sample_size=len(test_rates),
                        evidence=[],
                    )
                )

        logger.info("detected %d weakness(es)", len(weaknesses))
        return weaknesses

    # -- proposal ----------------------------------------------------------- #
    async def propose(self, weakness: Weakness) -> Proposal:
        """Draft a proposal, then screen it. Rejected proposals are recorded too."""
        system = (
            "You are the self-improvement engine of LEVEL 5. Propose ONE concrete, "
            "verifiable improvement to the platform that addresses the stated "
            "weakness. Rules:\n"
            "- Propose a change to LEVEL 5's own source code, never to a user's project.\n"
            "- The proposal must be testable: name the tests that must pass and how the "
            "before/after comparison will be measured.\n"
            "- Never propose disabling security, widening permissions, removing tests, "
            "or applying changes automatically to the running system.\n"
            "- Do not propose creating agents recursively.\n"
            'Respond as JSON: {"hypothesis": str, "change": str, '
            '"target_files": [str], "required_tests": [str], '
            '"comparison_plan": str, "risk": str}'
        )
        user = (
            f"AREA: {weakness.area}\nWEAKNESS: {weakness.statement}\n"
            f"METRIC: {weakness.metric} = {weakness.value} (n={weakness.sample_size})"
        )
        try:
            data, _ = await self.llm.chat_json(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.3,
                max_tokens=2000,
            )
        except Exception as exc:  # noqa: BLE001 - a failed proposal is recorded as such
            logger.warning("proposal generation failed: %s", exc)
            data = {
                "hypothesis": "Proposal generation failed.",
                "change": str(exc)[:300],
                "target_files": [],
                "required_tests": [],
                "comparison_plan": "",
                "risk": "unknown",
            }

        proposal = Proposal(
            id=f"prop_{uuid.uuid4().hex[:8]}",
            weakness_id=weakness.id,
            area=weakness.area,
            hypothesis=str(data.get("hypothesis", "")),
            change=str(data.get("change", "")),
            target_files=[str(f) for f in (data.get("target_files") or [])][:12],
            required_tests=[str(t) for t in (data.get("required_tests") or [])][:12],
            comparison_plan=str(data.get("comparison_plan", "")),
            risk=str(data.get("risk", "unknown")),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        reason = screen_proposal(proposal)
        if reason:
            proposal.status = "rejected"
            proposal.rejection_reason = reason
            logger.warning("proposal %s rejected: %s", proposal.id, reason)
        return proposal

    async def record(self, proposal: Proposal) -> None:
        await self.store.save_improvement(
            {**proposal.as_dict(), "recorded_at": datetime.now(timezone.utc).isoformat()}
        )


def screen_proposal(proposal: Proposal) -> str | None:
    """Return a rejection reason, or None when the proposal is acceptable."""
    if not proposal.required_tests:
        return "no tests specified: an unverified change cannot be accepted"
    if not proposal.comparison_plan.strip():
        return "no before/after comparison plan"
    blob = " ".join(
        [proposal.hypothesis, proposal.change, proposal.comparison_plan]
    ).lower()
    for pattern, label in _FORBIDDEN_PATTERNS:
        if re.search(pattern, blob, re.I):
            return f"proposal {label}"
    return None
