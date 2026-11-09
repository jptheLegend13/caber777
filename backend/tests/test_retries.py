"""Tests for bounded, transient-only task retries.

The orchestrator must retry infrastructure faults (gateway timeouts, rate
limits) and must NOT retry the agent's own failures (failed tests, syntax
errors), because retrying those burns budget and hides a real defect.
"""

from __future__ import annotations

from level5.models import Task
from level5.orchestrator import Orchestrator


def _orch() -> Orchestrator:
    return Orchestrator.__new__(Orchestrator)


def _task(max_attempts: int = 2) -> Task:
    t = Task(title="Do work", objective="Do the work")
    t.max_attempts = max_attempts
    return t


class TestShouldRetry:
    def test_gateway_timeout_is_retried(self):
        t = _task()
        t.attempts = 1
        assert _orch()._should_retry(t, "gateway 504: Agent run timed out") is True

    def test_rate_limit_is_retried(self):
        t = _task()
        t.attempts = 1
        assert _orch()._should_retry(t, "429 rate limit exceeded") is True

    def test_failed_tests_are_not_retried(self):
        t = _task()
        t.attempts = 1
        assert _orch()._should_retry(t, "the test suite failed: 3 tests failed") is False

    def test_syntax_error_is_not_retried(self):
        t = _task()
        t.attempts = 1
        assert _orch()._should_retry(t, "SyntaxError: invalid syntax") is False

    def test_retries_are_bounded_by_max_attempts(self):
        t = _task(max_attempts=2)
        t.attempts = 2
        assert _orch()._should_retry(t, "gateway 504 timed out") is False

    def test_unknown_error_is_not_retried(self):
        t = _task()
        t.attempts = 1
        assert _orch()._should_retry(t, "the agent gave up") is False

    def test_retry_delay_is_bounded_and_increasing(self):
        orch = _orch()
        assert orch._retry_delay(1) < orch._retry_delay(2)
        assert orch._retry_delay(10) <= 30.0


class TestServerRetryabilityVerdict:
    """When the agent server classifies an error, that verdict is authoritative."""

    def test_server_says_not_retryable_overrides_transient_wording(self):
        t = _task()
        t.attempts = 1
        # "timed out" alone would be retried, but the server said no.
        assert (
            _orch()._should_retry(t, "gateway 504 timed out", retryable=False) is False
        )

    def test_server_says_retryable_overrides_permanent_wording(self):
        t = _task()
        t.attempts = 1
        assert (
            _orch()._should_retry(t, "the test suite failed", retryable=True) is True
        )

    def test_max_iterations_reached_is_not_retryable(self):
        """The server marks MaxIterationsReached non-retryable; retrying it
        would just hit the same ceiling."""
        t = _task()
        t.attempts = 1
        err = "MaxIterationsReached: Agent reached maximum iterations limit (120)."
        assert _orch()._should_retry(t, err, retryable=False) is False

    def test_verdict_none_falls_back_to_string_matching(self):
        t = _task()
        t.attempts = 1
        assert _orch()._should_retry(t, "504 gateway timeout", retryable=None) is True

    def test_verdict_none_and_unknown_error_is_not_retried(self):
        t = _task()
        t.attempts = 1
        assert _orch()._should_retry(t, "the agent gave up", retryable=None) is False

    def test_attempt_budget_still_wins_over_retryable_verdict(self):
        t = _task(max_attempts=2)
        t.attempts = 2
        assert _orch()._should_retry(t, "504", retryable=True) is False

