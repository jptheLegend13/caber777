"""Tests for the research engine's keyless retrieval providers.

The parsers run against recorded responses (a real Wikipedia JSON body and a
real arXiv Atom body) so the parsing code is exercised, not stubbed. The merge
and term-extraction logic is pure and tested directly. One live smoke test hits
the real public APIs and is skipped when the network is unavailable.
"""

from __future__ import annotations

import json

import httpx
import pytest

from level5.config import Settings
from level5.intelligence.research import (
    ResearchEngine,
    SearchHit,
    _query_terms,
)

_WIKIPEDIA_BODY = {
    "query": {
        "search": [
            {
                "title": "Retrieval-augmented generation",
                "snippet": 'a <span class="searchmatch">retrieval</span> technique',
            },
            {"title": "Transformer (deep learning)", "snippet": "a model"},
        ]
    }
}

_ARXIV_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2402.11626v1</id>
    <title>  A Survey of RAG
      Evaluation </title>
    <summary>We survey retrieval-augmented generation evaluation methods.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2410.12812v1</id>
    <title>Second Paper</title>
    <summary>Another abstract.</summary>
  </entry>
</feed>
"""


class _FakeResponse:
    def __init__(self, *, text: str = "", json_data=None, status: int = 200) -> None:
        self.text = text
        self._json = json_data
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]


class _FakeClient:
    """Stands in for httpx.AsyncClient, returning a canned response."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url: str, **kwargs) -> _FakeResponse:
        return self._response


def _engine_with(monkeypatch, response: _FakeResponse) -> ResearchEngine:
    engine = ResearchEngine(settings=Settings())

    def factory(*a, **k):
        return _FakeClient(response)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return engine


class TestQueryTerms:
    def test_drops_stopwords_and_short_tokens(self):
        assert _query_terms("how to build the best RAG system") == ["rag"]

    def test_preserves_order_and_dedupes(self):
        assert _query_terms("alpha beta alpha gamma") == ["alpha", "beta", "gamma"]

    def test_caps_terms(self):
        assert len(_query_terms("one two three four five six seven eight")) == 6


class TestWikipediaParser:
    async def test_parses_search_results(self, monkeypatch):
        engine = _engine_with(monkeypatch, _FakeResponse(json_data=_WIKIPEDIA_BODY))
        hits = await engine._wikipedia("retrieval", 5)
        assert len(hits) == 2
        assert hits[0].url == "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"
        assert hits[0].provider == "wikipedia"
        # HTML in the snippet must be stripped.
        assert "<span" not in hits[0].snippet

    async def test_error_status_returns_empty(self, monkeypatch):
        engine = _engine_with(monkeypatch, _FakeResponse(json_data={}, status=403))
        assert await engine._wikipedia("retrieval", 5) == []


class TestArxivParser:
    async def test_parses_atom_feed(self, monkeypatch):
        engine = _engine_with(monkeypatch, _FakeResponse(text=_ARXIV_BODY))
        hits = await engine._arxiv("rag evaluation", 5)
        assert len(hits) == 2
        assert hits[0].url == "http://arxiv.org/abs/2402.11626v1"
        # Whitespace inside the title is collapsed.
        assert hits[0].title == "A Survey of RAG Evaluation"
        assert hits[0].provider == "arxiv"

    async def test_malformed_xml_returns_empty(self, monkeypatch):
        engine = _engine_with(monkeypatch, _FakeResponse(text="<feed>not closed"))
        assert await engine._arxiv("rag", 5) == []


class TestSearchMerge:
    async def test_round_robin_dedupes_and_caps(self, monkeypatch):
        engine = ResearchEngine(settings=Settings())

        async def fake_a(q, limit):
            return [SearchHit(title="a1", url="http://x/1", provider="a"),
                    SearchHit(title="a2", url="http://x/2", provider="a")]

        async def fake_b(q, limit):
            return [SearchHit(title="b1", url="http://x/1", provider="b"),  # duplicate url
                    SearchHit(title="b2", url="http://x/3", provider="b")]

        async def empty(q, limit):
            return []

        monkeypatch.setattr(engine, "_tavily", empty)
        monkeypatch.setattr(engine, "_brave", empty)
        monkeypatch.setattr(engine, "_wikipedia", fake_a)
        monkeypatch.setattr(engine, "_arxiv", fake_b)
        monkeypatch.setattr(engine, "_crossref", empty)
        monkeypatch.setattr(engine, "_github", empty)
        monkeypatch.setattr(engine, "_stackexchange", empty)
        monkeypatch.setattr(engine, "_duckduckgo", empty)

        hits = await engine.search("q", limit=3)
        # a1, b1(dup url dropped), a2, b2 -> capped at 3, providers interleaved.
        assert [h.url for h in hits] == ["http://x/1", "http://x/2", "http://x/3"]
        assert hits[0].provider == "a" and hits[1].provider == "a" and hits[2].provider == "b"

    async def test_provider_exception_does_not_break_search(self, monkeypatch):
        engine = ResearchEngine(settings=Settings())

        async def boom(q, limit):
            raise RuntimeError("network down")

        async def good(q, limit):
            return [SearchHit(title="ok", url="http://ok/1", provider="g")]

        for name in ("_tavily", "_brave", "_wikipedia", "_arxiv", "_crossref",
                     "_github", "_stackexchange", "_duckduckgo"):
            monkeypatch.setattr(engine, name, boom)
        monkeypatch.setattr(engine, "_github", good)
        hits = await engine.search("q", limit=5)
        assert [h.url for h in hits] == ["http://ok/1"]


@pytest.mark.network
class TestLiveKeylessApis:
    """Smoke test against the real public APIs (no credential required)."""

    async def test_search_returns_sources_without_any_key(self):
        engine = ResearchEngine(settings=Settings())
        hits = await engine.search("retrieval augmented generation", limit=6)
        if not hits:
            pytest.skip("no network egress to the public APIs")
        providers = {h.provider for h in hits}
        assert providers & {"wikipedia", "arxiv", "crossref", "github", "stackexchange"}
        assert all(h.url for h in hits)
