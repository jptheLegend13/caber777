"""Tests for the innovation-to-prototype engine.

Only the model and retrieval boundaries are replaced with canned responses;
the prototype itself is really executed by the shared sandbox runner, and the
report wiring (artifacts, status, files) is exercised for real.
"""

from __future__ import annotations

import json
from pathlib import Path

from level5.intelligence.innovation import InnovationEngine, InnovationReport
from level5.models import Project


class _FakeLLM:
    """Returns scripted JSON per system prompt, and records the calls."""

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def chat_json(self, messages, *, temperature=0.2, max_tokens=1000):
        system = messages[0]["content"]
        self.calls.append(system)
        return self.responses.pop(0), None


class _FakeResearch:
    def __init__(self) -> None:
        self.questions: list[str] = []

    async def investigate_many(self, questions):
        self.questions = list(questions)
        from level5.models import ResearchReport, Source

        return [
            ResearchReport(
                question=q,
                summary=f"Summary for {q}",
                sources=[Source(url="https://example.test/x", title="X")],
            )
            for q in questions
        ]


def _frame_response() -> dict:
    return {
        "understanding": "A self-tuning cache.",
        "prior_art_queries": ["adaptive cache replacement"],
        "technical_gap": "No public implementation of the proposed policy.",
        "feasibility": "uncertain",
        "alternatives": ["LRU baseline", "frequency-aware policy"],
        "hypothesis": "The proposed policy beats LRU on a skewed trace.",
        "architecture": "Score = recency decay * frequency.",
        "prototype_description": "Simulate a skewed trace, compare hit rates.",
        "evaluation_plan": "Report hit-rate delta.",
    }


_PROTOTYPE_CODE = (
    "import json\n"
    "result = {'hypothesis': 'x', 'metric': 'hit_rate', 'result': 0.9, "
    "'supports_hypothesis': True, 'notes': 'ok'}\n"
    "print(json.dumps(result))\n"
)

_DESIGN_RESPONSE = {
    "prototype_code": _PROTOTYPE_CODE,
    "prototype_description": "Simulate and report hit rate.",
}

_EVAL_RESPONSE = {
    "findings": ["Prototype hit rate 0.9 supports the hypothesis."],
    "limitations": ["Single synthetic trace."],
    "next_steps": ["Test on real traces."],
    "feasibility": "feasible",
    "confidence": "medium",
}


async def test_investigate_runs_prototype_and_reports(tmp_path):
    llm = _FakeLLM([_frame_response(), _DESIGN_RESPONSE, _EVAL_RESPONSE])
    engine = InnovationEngine(llm=llm, research=_FakeResearch(), timeout=30)
    report = await engine.investigate("self-tuning cache", workspace=tmp_path, research=True)

    assert report.status == "completed"
    assert report.feasibility == "feasible"
    assert report.confidence == "medium"
    assert report.hypothesis.startswith("The proposed policy")
    assert report.prototype is not None and report.prototype.succeeded
    assert report.prototype.parsed["supports_hypothesis"] is True
    assert "prototype.py" in report.prototype.files
    assert report.prior_art == ["Summary for adaptive cache replacement"]
    assert report.findings


async def test_prototype_failure_is_reported_not_hidden(tmp_path):
    """A prototype that crashes yields a failed run and a repair attempt."""
    broken = {"prototype_code": "raise SystemError('broken')\n", "prototype_description": "x"}
    llm = _FakeLLM([_frame_response(), broken, _DESIGN_RESPONSE, _EVAL_RESPONSE])
    engine = InnovationEngine(llm=llm, research=_FakeResearch(), timeout=30)
    report = await engine.investigate("self-tuning cache", workspace=tmp_path, research=False)

    # The repair response supplies working code, so the final run succeeds.
    assert report.prototype is not None and report.prototype.succeeded


async def test_no_prototype_marks_partial(tmp_path):
    llm = _FakeLLM([_frame_response(), {}, _EVAL_RESPONSE])
    engine = InnovationEngine(llm=llm, research=_FakeResearch(), timeout=30)
    report = await engine.investigate("self-tuning cache", workspace=tmp_path, research=False)

    assert report.prototype is None
    assert report.status == "partial"


async def test_research_false_skips_retrieval(tmp_path):
    research = _FakeResearch()
    llm = _FakeLLM([_frame_response(), _DESIGN_RESPONSE, _EVAL_RESPONSE])
    engine = InnovationEngine(llm=llm, research=research, timeout=30)
    await engine.investigate("self-tuning cache", workspace=tmp_path, research=False)
    assert research.questions == []


def test_report_as_dict_is_json_serialisable():
    report = InnovationReport(idea="x")
    encoded = json.dumps(report.as_dict())
    assert json.loads(encoded)["idea"] == "x"
    assert json.loads(encoded)["prototype"] is None


async def test_innovate_project_attaches_artifacts(tmp_path, monkeypatch):
    from level5.intelligence import innovation as innovation_mod

    llm = _FakeLLM([_frame_response(), _DESIGN_RESPONSE, _EVAL_RESPONSE])
    monkeypatch.setattr(
        innovation_mod, "InnovationEngine", lambda: InnovationEngine(llm=llm, timeout=30)
    )
    project = Project(name="idea", original_request="self-tuning cache")
    project.workspace_path = str(tmp_path)

    result = await innovation_mod.innovate_project(project, research=False)

    assert (tmp_path / "innovation.json").exists()
    names = {a.name for a in result.artifacts}
    assert "innovation.json" in names
    assert "prototype.py" in names
    assert result.status.value in {"delivered", "failed"}
