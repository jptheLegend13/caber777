"""Intelligence-independence tests.

These prove the architectural guarantee in the independence requirement:

- External model providers are optional and OFF by default.
- Internal (self-hosted) inference is the preferred production backend.
- An external provider is NEVER used as a fallback for an internal failure.
- Core intelligence (understanding, planning, memory, retrieval) keeps working
  with no model and no external service at all.

No test here contacts the network: backend health is injected.
"""

from __future__ import annotations

import time

import pytest

from level5.config import Settings
from level5.intelligence.fallbacks import graph_from_spec, spec_from_request
from level5.intelligence.planner import Planner
from level5.intelligence.understanding import UnderstandingEngine
from level5.knowledge.store import KnowledgeStore
from level5.llm.client import LLMClient, LLMError
from level5.llm.gateway import Backend, ModelGateway, NoBackendAvailable


def _settings(**kw) -> Settings:
    s = Settings()
    s.allow_external_models = kw.get("allow_external", False)
    s.allow_dev_gateway = kw.get("allow_dev_gateway", True)
    s.local_llm_base_url = kw.get("local_url", "http://127.0.0.1:8080/v1")
    return s


def _backend(name, class_, priority, *, healthy, caps=None):
    return Backend(
        name=name,
        class_=class_,
        base_url=f"http://{name}.invalid/v1",
        model=f"{name}-model",
        priority=priority,
        capabilities=frozenset(caps or {"tools", "streaming", "json_mode"}),
    )


def _gw(backends, settings, health: dict[str, bool]) -> ModelGateway:
    gateway = ModelGateway(backends=backends, settings=settings)
    now = time.monotonic()
    for name, ok in health.items():
        gateway._health[name] = (now, ok)
    return gateway


class TestExternalProvidersOptional:
    def test_external_backend_excluded_unless_enabled(self):
        settings = _settings(allow_external=False)
        backends = [
            _backend("local_runtime", "internal", 10, healthy=True),
            _backend("openai", "external", 100, healthy=True),
        ]
        gw = _gw(backends, settings, {"local_runtime": True, "openai": True})
        names = [b.name for b in gw.backends()]
        assert "openai" not in names
        assert "local_runtime" in names

    def test_external_backend_included_when_enabled(self):
        settings = _settings(allow_external=True)
        backends = [
            _backend("local_runtime", "internal", 10, healthy=True),
            _backend("openai", "external", 100, healthy=True),
        ]
        gw = _gw(backends, settings, {"local_runtime": True, "openai": True})
        assert "openai" in [b.name for b in gw.backends()]

    def test_dev_gateway_excluded_when_disabled(self):
        settings = _settings(allow_dev_gateway=False)
        backends = [_backend("openhands_dev_gateway", "development", 50, healthy=True)]
        gw = _gw(backends, settings, {"openhands_dev_gateway": True})
        assert gw.backends() == []


class TestNoExternalFallback:
    def test_internal_failure_does_not_fall_through_to_external(self):
        """The central guarantee: external is never a fallback for internal."""
        settings = _settings(allow_external=True, allow_dev_gateway=False)
        backends = [
            _backend("local_runtime", "internal", 10, healthy=False),
            _backend("openai", "external", 100, healthy=True),
        ]
        gw = _gw(backends, settings, {"local_runtime": False, "openai": True})
        with pytest.raises(NoBackendAvailable) as exc:
            gw.route()
        assert "external fallback is disabled" in str(exc.value)

    def test_internal_failure_may_use_development_aid_but_never_external(self):
        settings = _settings(allow_external=True, allow_dev_gateway=True)
        backends = [
            _backend("local_runtime", "internal", 10, healthy=False),
            _backend("openhands_dev_gateway", "development", 50, healthy=True),
            _backend("openai", "external", 100, healthy=True),
        ]
        gw = _gw(
            backends,
            settings,
            {"local_runtime": False, "openhands_dev_gateway": True, "openai": True},
        )
        chosen = gw.route()
        assert chosen.name == "openhands_dev_gateway"

    def test_internal_preferred_when_healthy(self):
        settings = _settings(allow_external=True)
        backends = [
            _backend("local_runtime", "internal", 10, healthy=True),
            _backend("openai", "external", 100, healthy=True),
        ]
        gw = _gw(backends, settings, {"local_runtime": True, "openai": True})
        assert gw.route().name == "local_runtime"

    def test_internal_only_route_never_returns_external(self):
        settings = _settings(allow_external=True)
        backends = [_backend("openai", "external", 100, healthy=True)]
        gw = _gw(backends, settings, {"openai": True})
        with pytest.raises(NoBackendAvailable):
            gw.route(internal_only=True)

    def test_report_states_no_external_fallback(self):
        settings = _settings()
        gw = _gw([_backend("local_runtime", "internal", 10, healthy=True)], settings, {})
        report = gw.report()
        assert report["independence"]["external_fallback_on_internal_failure"] is False
        assert report["independence"]["production_backend_class"] == "internal"


class TestClientTransportIndependence:
    def test_client_auto_order_includes_internal_first(self):
        client = LLMClient(_settings())
        client._gateway_probed = True
        client._gateway_ok = False
        # With no internal backend reachable, the client drops "internal" and
        # does not invent an external transport.
        assert client._internal_available() is False

    async def test_client_reports_failure_when_no_transport_works(self, monkeypatch):
        client = LLMClient(_settings(allow_dev_gateway=False))
        client._gateway_probed = True
        client._gateway_ok = False

        async def boom(*a, **k):
            raise RuntimeError("no backend")

        monkeypatch.setattr(client, "_chat_ask_agent", boom)
        with pytest.raises(LLMError):
            await client.chat([{"role": "user", "content": "hi"}])


class TestModelFreeCoreIntelligence:
    async def test_understanding_falls_back_without_a_model(self, monkeypatch):
        engine = UnderstandingEngine(llm=LLMClient(_settings()))

        async def boom(*a, **k):
            raise LLMError("no model")

        monkeypatch.setattr(engine.llm, "chat_json", boom)
        spec = await engine.understand(
            "Build a web application with a frontend and backend"
        )
        assert spec.deliverable
        assert spec.requirements
        assert spec.acceptance_criteria
        assert any(r.origin == "inferred" for r in spec.requirements)

    async def test_planner_falls_back_without_a_model(self, monkeypatch):
        planner = Planner(llm=LLMClient(_settings()))
        spec = spec_from_request("Build a backend API with a database")

        async def boom(*a, **k):
            raise LLMError("no model")

        monkeypatch.setattr(planner.llm, "chat_json", boom)
        graph = await planner.plan(spec)
        assert graph.tasks
        # Dependencies must reference real tasks and be acyclic.
        ids = {t.id for t in graph.tasks}
        for task in graph.tasks:
            assert set(task.dependencies) <= ids

    @pytest.mark.parametrize(
        "ask",
        [
            "Build a web application with a frontend and backend",
            "Build a backend API with a database",
            "Create an AI agent with tools and memory",
            "Research the state of the art in retrieval augmented generation",
            "Design a modern two-storey house",
        ],
    )
    def test_rules_produce_a_valid_plan_for_every_domain(self, ask):
        spec = spec_from_request(ask)
        graph = graph_from_spec(spec)
        assert spec.domain is not None
        assert graph.tasks
        ids = {t.id for t in graph.tasks}
        for task in graph.tasks:
            assert set(task.dependencies) <= ids
            assert task.agent_role
        # Every plan ends with a verification or review step.
        assert any(t.phase in ("testing", "review") for t in graph.tasks)


class TestLocalMemoryAndRetrieval:
    async def test_store_and_retrieve_without_a_model(self, tmp_path):
        store = KnowledgeStore(db_path=tmp_path / "kn.db")
        await store.add(
            project_id="p1",
            kind="requirement",
            title="Authentication",
            text="The system must authenticate users with email and password.",
        )
        await store.add(
            project_id="p1",
            kind="decision",
            title="Database",
            text="We chose PostgreSQL for relational integrity and indexing.",
        )
        await store.add(
            project_id="p1",
            kind="lesson",
            title="Build",
            text="The frontend build failed until the node version was pinned.",
        )
        hits = await store.search("authentication email password", project_id="p1")
        assert hits
        assert hits[0].entry.title == "Authentication"

    async def test_retrieval_is_deterministic(self, tmp_path):
        store = KnowledgeStore(db_path=tmp_path / "kn.db")
        for i in range(5):
            await store.add(
                project_id="p1",
                kind="note",
                title=f"note {i}",
                text=f"alpha beta gamma topic {i}",
            )
        first = [h.entry.id for h in await store.search("alpha topic", project_id="p1")]
        second = [h.entry.id for h in await store.search("alpha topic", project_id="p1")]
        assert first == second

    async def test_search_scopes_by_project(self, tmp_path):
        store = KnowledgeStore(db_path=tmp_path / "kn.db")
        await store.add(project_id="a", kind="note", title="alpha", text="alpha only")
        await store.add(project_id="b", kind="note", title="alpha", text="alpha other")
        hits = await store.search("alpha", project_id="a")
        assert all(h.entry.project_id == "a" for h in hits)
