"""Tests for command-box routing into the specialised CABER engines.

A natural-language request must reach the right intelligence: buildings to the
3D creation engine, novel ideas to the innovation pipeline, everything else to
the generic engineering task graph. These tests pin the routing decision, which
is the integration point between the command box and the three intelligences.
"""

from __future__ import annotations

import pytest

from level5.api import routes
from level5.api.routes import _looks_like_innovation
from level5.models import CABERModule, Project, Specification


def _spec(deliverable: str = "", intent: str = "") -> Specification:
    return Specification(deliverable=deliverable, intent=intent)


class TestInnovationRouting:
    def test_invention_wording_routes_to_innovation(self):
        assert _looks_like_innovation(
            "Develop a novel new kind of memory for agents", _spec()
        )

    def test_prior_art_wording_routes_to_innovation(self):
        assert _looks_like_innovation(
            "Investigate the prior art for a self-tuning cache and prototype it",
            _spec(),
        )

    def test_plain_research_stays_on_generic_path(self):
        assert not _looks_like_innovation(
            "Determine whether this queueing system is stable and model it",
            _spec(deliverable="A queueing stability analysis with a simulation"),
        )

    def test_specification_can_trigger_routing(self):
        assert _looks_like_innovation(
            "Build the thing", _spec(intent="Create an original idea prototype")
        )


class TestPipelineDispatch:
    """`_run_full_pipeline` must route before running the generic path.

    A building request is classified, then handed straight to the 3D engine.
    The generic research and plan steps must *not* run first, or they would
    duplicate the specialist engine's own work and delay the route.
    """

    async def _run(self, store, monkeypatch, module: CABERModule, **kw):
        project = Project(name="t", original_request="request text")
        await store.save(project)

        called: list[str] = []

        async def fake_understand(proj, **kwargs):
            proj.specification = Specification(deliverable="d", intent="i")
            proj.specification.caber_module = module
            return proj

        async def fake_research(proj, **kwargs):
            called.append("research")
            return proj

        async def fake_plan(proj, **kwargs):
            called.append("plan")
            return proj

        async def fake_execute(proj, **kwargs):
            called.append("execute")
            return proj

        monkeypatch.setattr(routes._orchestrator, "understand", fake_understand)
        monkeypatch.setattr(routes._orchestrator, "run_research", fake_research)
        monkeypatch.setattr(routes._orchestrator, "plan", fake_plan)
        monkeypatch.setattr(routes._orchestrator, "execute", fake_execute)
        monkeypatch.setattr(routes, "get_store", lambda: store)

        if module == CABERModule.BUILDING:
            from level5.caber import service as caber_service

            async def fake_build(self, proj, **kwargs):
                called.append("building")
                return proj

            monkeypatch.setattr(caber_service.CABERBuildingService, "build", fake_build)
        elif kw.get("innovation"):
            from level5.intelligence import innovation as innovation_mod

            async def fake_innovate(proj, **kwargs):
                called.append("innovation")
                return proj

            monkeypatch.setattr(innovation_mod, "innovate_project", fake_innovate)

        await routes._run_full_pipeline(project.id, None)
        return called

    async def test_building_request_goes_to_building_engine_only(self, store, monkeypatch):
        called = await self._run(store, monkeypatch, CABERModule.BUILDING)
        assert called == ["building"]

    async def test_generic_request_runs_research_plan_execute(self, store, monkeypatch):
        called = await self._run(store, monkeypatch, CABERModule.APPLICATION)
        assert called == ["research", "plan", "execute"]
