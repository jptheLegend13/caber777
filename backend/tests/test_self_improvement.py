"""Tests for the controlled self-improvement loop and its guardrails."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from level5.self_improvement import Proposal, SelfImprovementEngine, screen_proposal


def _proposal(**overrides) -> Proposal:
    base = dict(
        id="prop_test",
        weakness_id="weak_test",
        area="testing",
        hypothesis="Improve test selection.",
        change="Add a test-impact analysis step before running the suite.",
        target_files=["backend/level5/orchestrator.py"],
        required_tests=["tests/test_orchestrator.py"],
        comparison_plan="Compare test pass rate over 5 runs before and after.",
        risk="low",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    base.update(overrides)
    return Proposal(**base)


class TestScreening:
    def test_clean_proposal_is_accepted(self):
        assert screen_proposal(_proposal()) is None

    def test_proposal_without_tests_is_rejected(self):
        assert "no tests" in (screen_proposal(_proposal(required_tests=[])) or "")

    def test_proposal_without_comparison_is_rejected(self):
        assert "comparison" in (screen_proposal(_proposal(comparison_plan="")) or "")

    @pytest.mark.parametrize(
        "change",
        [
            "Disable the security check before deployment.",
            "Skip validation for performance.",
            "Remove the failing tests so the suite passes.",
            "Grant wider permissions to the terminal tool.",
            "Auto-apply the patch to the production system.",
            "Expose the API key to the frontend.",
            "Create agents automatically in a loop.",
        ],
    )
    def test_dangerous_proposals_are_rejected(self, change):
        reason = screen_proposal(_proposal(change=change))
        assert reason is not None, f"should have rejected: {change}"


class TestDetection:
    async def test_no_weaknesses_without_enough_data(self, store):
        engine = SelfImprovementEngine(store=store)
        engine.llm = object()  # detection must not call the model
        assert await engine.detect_weaknesses(min_samples=3) == []

    async def test_high_failure_rate_is_detected(self, store):
        for i in range(4):
            await store.save_benchmark(
                {
                    "project_id": f"p{i}",
                    "domain": "web_app",
                    "tasks_total": 10,
                    "tasks_failed": 5,
                    "criteria_rate": 0.9,
                    "test_pass_rate": 0.9,
                }
            )
        engine = SelfImprovementEngine(store=store)
        engine.llm = object()
        weaknesses = await engine.detect_weaknesses(min_samples=3)
        assert any(w.metric == "task_failure_rate" for w in weaknesses)

    async def test_low_criteria_rate_is_detected(self, store):
        for i in range(4):
            await store.save_benchmark(
                {
                    "project_id": f"p{i}",
                    "domain": "web_app",
                    "tasks_total": 10,
                    "tasks_failed": 0,
                    "criteria_rate": 0.3,
                    "test_pass_rate": 0.95,
                }
            )
        engine = SelfImprovementEngine(store=store)
        engine.llm = object()
        weaknesses = await engine.detect_weaknesses(min_samples=3)
        assert any(w.metric == "criteria_rate" for w in weaknesses)

    async def test_healthy_metrics_produce_no_weakness(self, store):
        for i in range(4):
            await store.save_benchmark(
                {
                    "project_id": f"p{i}",
                    "domain": "web_app",
                    "tasks_total": 10,
                    "tasks_failed": 0,
                    "criteria_rate": 0.95,
                    "test_pass_rate": 0.98,
                }
            )
        engine = SelfImprovementEngine(store=store)
        engine.llm = object()
        assert await engine.detect_weaknesses(min_samples=3) == []


class _ReviewerLLM:
    """Returns a canned reviewer decision and records the prompts it saw."""

    def __init__(self, decision: str, confidence: str = "medium") -> None:
        self.decision = decision
        self.confidence = confidence
        self.calls: list[str] = []

    async def chat_json(self, messages, *, temperature=0.2, max_tokens=1000):
        self.calls.append(messages[0]["content"])
        return {"decision": self.decision, "reason": "because", "confidence": self.confidence}, None


class TestIndependentReview:
    async def test_reviewer_can_accept(self, store):
        engine = SelfImprovementEngine(store=store)
        engine.llm = _ReviewerLLM("accept", "high")
        proposal = await engine.review(_proposal(), weaknesses=[])
        assert proposal.status == "accepted"
        assert proposal.review["decision"] == "accept"
        assert proposal.review["confidence"] == "high"

    async def test_reviewer_can_reject(self, store):
        engine = SelfImprovementEngine(store=store)
        engine.llm = _ReviewerLLM("reject")
        proposal = await engine.review(_proposal(), weaknesses=[])
        assert proposal.status == "rejected"
        assert proposal.rejection_reason

    async def test_reviewer_never_revives_a_screened_proposal(self, store):
        engine = SelfImprovementEngine(store=store)
        engine.llm = _ReviewerLLM("accept")
        unsafe = _proposal(change="Disable the security check before deployment.")
        # The proposer's screen has already rejected it.
        from level5.self_improvement import screen_proposal as screen

        unsafe.status = "rejected"
        unsafe.rejection_reason = screen(unsafe)
        result = await engine.review(unsafe, weaknesses=[])
        assert result.status == "rejected"
        assert engine.llm.calls == []  # the model was never consulted

    async def test_reviewer_does_not_accept_untested_proposal(self, store):
        engine = SelfImprovementEngine(store=store)
        engine.llm = _ReviewerLLM("accept")
        result = await engine.review(_proposal(required_tests=[]), weaknesses=[])
        assert result.status == "rejected"
        assert engine.llm.calls == []

    async def test_reviewer_failure_is_a_rejection(self, store):
        class _Boom:
            async def chat_json(self, *a, **k):
                raise RuntimeError("reviewer offline")

        engine = SelfImprovementEngine(store=store)
        engine.llm = _Boom()
        result = await engine.review(_proposal(), weaknesses=[])
        assert result.status == "rejected"
        assert "review failed" in (result.rejection_reason or "")
