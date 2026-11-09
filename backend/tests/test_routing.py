"""Tests for command-box routing into the specialised CABER engines.

A natural-language request must reach the right intelligence: buildings to the
3D creation engine, novel ideas to the innovation pipeline, everything else to
the generic engineering task graph. These tests pin the routing decision, which
is the integration point between the command box and the three intelligences.
"""

from __future__ import annotations

from level5.api.routes import _looks_like_innovation
from level5.models import Specification


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
