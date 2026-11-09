"""Tests for the competitive benchmark suite (directive §17).

The suite must never fabricate a comparison. These tests pin the honesty rules:
criteria without evidence fail, a task is solved only when every criterion
passes, missing runs are counted separately, and no external system is scored.
"""

from __future__ import annotations

import pytest

from level5 import benchmark_suite as bs


class TestSuiteDefinition:
    def test_tasks_are_fixed_and_versioned(self):
        assert bs.SUITE_VERSION
        assert len(bs.list_tasks()) == len(bs.task_ids()) >= 5

    def test_every_task_has_objective_checks(self):
        for task in bs.list_tasks():
            assert task["criteria"], task["id"]
            for criterion in task["criteria"]:
                assert criterion["key"] and criterion["description"]

    def test_unknown_task_raises(self):
        with pytest.raises(KeyError):
            bs.score_transcript(system="x", task_id="nope", evidence={})


class TestScoring:
    def test_absent_evidence_is_never_assumed(self):
        result = bs.score_transcript(system="s", task_id="webapp_crud", evidence={})
        assert result.status == "scored"
        assert result.passed == 0
        assert not result.success
        assert all(v is False for v in result.checks.values())

    def test_full_evidence_solves_the_task(self):
        keys = [c["key"] for c in bs.list_tasks()[0]["criteria"]]
        result = bs.score_transcript(
            system="s", task_id="webapp_crud", evidence={k: True for k in keys}
        )
        assert result.success
        assert result.passed == result.total

    def test_partial_evidence_is_not_success(self):
        keys = [c["key"] for c in bs.list_tasks()[0]["criteria"]]
        evidence = {k: True for k in keys[:-1]}
        evidence[keys[-1]] = False
        result = bs.score_transcript(system="s", task_id="webapp_crud", evidence=evidence)
        assert not result.success
        assert result.passed == result.total - 1


class TestExternalSystemsAreNotFaked:
    def test_external_system_is_recorded_as_not_run(self):
        result = bs.run_external_system(system="claude-code", task_id="bugfix")
        assert result.status == "not_run"
        assert result.passed == 0
        assert not result.success
        assert "Not run" in result.notes or "not" in result.notes.lower()

    def test_not_run_validates_task_id(self):
        with pytest.raises(KeyError):
            bs.run_external_system(system="x", task_id="does-not-exist")


class TestAggregate:
    def test_missing_runs_do_not_count_as_failures(self):
        records = [
            bs.score_transcript(
                system="level5",
                task_id="bugfix",
                evidence={"root_cause": True, "patch": True, "regression_test": True,
                          "tests_run": True, "tests_pass": True},
            ).as_dict(),
            bs.run_external_system(system="codex", task_id="bugfix").as_dict(),
        ]
        summary = bs.aggregate(records)
        by = {s["system"]: s for s in summary["systems"]}
        assert by["level5"]["success_rate"] == 1.0
        assert by["level5"]["tasks_scored"] == 1
        # codex has no scored task, so its rate is null, not 0.0
        assert by["codex"]["success_rate"] is None
        assert by["codex"]["tasks_not_run"] == 1

    def test_aggregate_is_stable_with_no_records(self):
        summary = bs.aggregate([])
        assert summary["systems"] == []
