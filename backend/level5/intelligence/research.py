"""Universal Research Intelligence.

Performs real retrieval (web search + page fetch) and produces cited reports.
Every finding carries provenance and an evidence classification, so verified
information is never confused with a hypothesis. When no retrieval provider is
configured the engine says so explicitly instead of inventing sources.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

from level5.config import Settings, get_settings
from level5.llm.client import LLMClient, get_llm_client
from level5.models import EvidenceKind, ResearchReport, Source

logger = logging.getLogger("level5.intelligence.research")

# A descriptive User-Agent is required by the Wikimedia robot policy and is
# good practice for the other public APIs; httpx's default UA is rejected.
_UA = "LEVEL5ResearchBot/1.0 (https://github.com/jptheLegend13/caber777; level5@localhost)"


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""
    provider: str = ""


@dataclass
class RetrievedPage:
    url: str
    title: str
    text: str = ""
    ok: bool = False


@dataclass
class ResearchEngine:
    """Retrieval-backed research with structured, classified output."""

    llm: LLMClient | None = None
    settings: Settings | None = None
    _pages: list[RetrievedPage] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.settings = self.settings or get_settings()
        self.llm = self.llm or get_llm_client()

    # -- public API --------------------------------------------------------- #
    async def investigate(self, question: str) -> ResearchReport:
        """Research one question and return a cited report."""
        hits = await self.search(question, limit=self.settings.research_max_sources)
        if not hits:
            return await self._knowledge_only(question)

        pages = await self._fetch_all([h.url for h in hits[:5]])
        sources = self._build_sources(hits, pages)
        context = self._render_context(sources, pages)
        return await self._synthesize(question, sources, context)

    async def investigate_many(self, questions: list[str]) -> list[ResearchReport]:
        reports: list[ResearchReport] = []
        for question in questions[:6]:
            try:
                reports.append(await self.investigate(question))
            except Exception as exc:  # noqa: BLE001 - one failure must not stop all
                logger.warning("research failed for %r: %s", question, exc)
                reports.append(
                    ResearchReport(
                        question=question,
                        status="failed",
                        summary=f"Research failed: {exc}",
                        method="error",
                    )
                )
        return reports

    # -- retrieval ---------------------------------------------------------- #
    async def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        """Query every available provider and merge the results.

        Paid/keyed providers (Tavily, Brave) come first when configured; the
        keyless official APIs (Wikipedia, arXiv, Crossref, GitHub, Stack
        Exchange) always run and are merged in, so retrieval works with no key
        at all. Duplicate URLs are collapsed, preserving provider order.
        """
        providers = (
            ("tavily", self._tavily),
            ("brave", self._brave),
            ("wikipedia", self._wikipedia),
            ("arxiv", self._arxiv),
            ("crossref", self._crossref),
            ("github", self._github),
            ("stackexchange", self._stackexchange),
            ("duckduckgo", self._duckduckgo),
        )
        results = await asyncio.gather(
            *(provider(query, limit) for _, provider in providers),
            return_exceptions=True,
        )
        per_provider: list[list[SearchHit]] = []
        for (name, _), result in zip(providers, results):
            if isinstance(result, BaseException):
                logger.debug("provider %s failed: %s", name, result)
                continue
            if result:
                per_provider.append(list(result))
        # Round-robin so no single provider dominates a short result list; this
        # keeps a report's sources diverse (a paper, an article, a repo, a Q&A).
        merged: list[SearchHit] = []
        seen: set[str] = set()
        index = 0
        while len(merged) < limit and any(index < len(group) for group in per_provider):
            for group in per_provider:
                if index >= len(group):
                    continue
                hit = group[index]
                key = hit.url.split("#", 1)[0].rstrip("/")
                if key and key not in seen:
                    seen.add(key)
                    merged.append(hit)
                if len(merged) >= limit:
                    break
            index += 1
        if merged:
            logger.info(
                "search merged %d hits across %d providers",
                len(merged),
                len(per_provider),
            )
        return merged

    async def _tavily(self, query: str, limit: int) -> list[SearchHit]:
        api_key = self.settings_research_key("TAVILY_API_KEY")
        if not api_key:
            return []
        async with httpx.AsyncClient(timeout=self.settings.research_timeout) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "advanced",
                },
            )
            response.raise_for_status()
            data = response.json()
        return [
            SearchHit(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", "")[:600],
                provider="tavily",
            )
            for r in data.get("results", [])
            if r.get("url")
        ]

    async def _brave(self, query: str, limit: int) -> list[SearchHit]:
        api_key = self.settings_research_key("BRAVE_API_KEY")
        if not api_key:
            return []
        async with httpx.AsyncClient(timeout=self.settings.research_timeout) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": limit},
                headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        results = (data.get("web") or {}).get("results") or []
        return [
            SearchHit(
                title=re.sub("<[^>]+>", "", r.get("title", "")),
                url=r.get("url", ""),
                snippet=re.sub("<[^>]+>", "", r.get("description", ""))[:600],
                provider="brave",
            )
            for r in results
            if r.get("url")
        ]

    async def _duckduckgo(self, query: str, limit: int) -> list[SearchHit]:
        """Keyless fallback using the DuckDuckGo HTML endpoint."""
        async with httpx.AsyncClient(
            timeout=self.settings.research_timeout,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        ) as client:
            response = await client.get(
                f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            )
            response.raise_for_status()
            body = response.text
        hits: list[SearchHit] = []
        for match in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S
        ):
            url = html.unescape(match.group(1))
            title = html.unescape(re.sub("<[^>]+>", "", match.group(2))).strip()
            if url.startswith("//duckduckgo.com/l/"):
                continue
            hits.append(SearchHit(title=title, url=url, provider="duckduckgo"))
            if len(hits) >= limit:
                break
        return hits

    def settings_research_key(self, name: str) -> str:
        import os

        return os.environ.get(name, "")

    # -- keyless official APIs (no credential required) --------------------- #
    async def _wikipedia(self, query: str, limit: int) -> list[SearchHit]:
        """Wikipedia search API — official, keyless, CC-BY-SA content."""
        async with httpx.AsyncClient(
            timeout=self.settings.research_timeout,
            headers={"User-Agent": _UA},
        ) as client:
            response = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": min(limit, 5),
                },
            )
            if response.status_code >= 400:
                return []
            data = response.json()
        hits: list[SearchHit] = []
        for item in data.get("query", {}).get("search", []):
            title = item.get("title", "")
            if not title:
                continue
            hits.append(
                SearchHit(
                    title=title,
                    url=f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                    snippet=_html_to_text(item.get("snippet", "")),
                    provider="wikipedia",
                )
            )
        return hits

    async def _arxiv(self, query: str, limit: int) -> list[SearchHit]:
        """arXiv Atom API — official, keyless; peer-facing preprints."""
        terms = _query_terms(query)
        search = " AND ".join(f"all:{t}" for t in terms[:4]) or "all:machine learning"
        async with httpx.AsyncClient(
            timeout=self.settings.research_timeout,
            headers={"User-Agent": _UA},
        ) as client:
            response = await client.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": search, "max_results": min(limit, 5)},
            )
            if response.status_code >= 400:
                return []
            body = response.text
        ns = {"a": "http://www.w3.org/2005/Atom"}
        hits: list[SearchHit] = []
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return []
        for entry in root.findall("a:entry", ns):
            url = (entry.findtext("a:id", "", ns) or "").strip()
            title = _WS.sub(" ", (entry.findtext("a:title", "", ns) or "")).strip()
            summary = _WS.sub(" ", (entry.findtext("a:summary", "", ns) or "")).strip()
            if url:
                hits.append(
                    SearchHit(
                        title=title or url,
                        url=url,
                        snippet=summary[:600],
                        provider="arxiv",
                    )
                )
        return hits

    async def _crossref(self, query: str, limit: int) -> list[SearchHit]:
        """Crossref REST API — official, keyless; published scholarly works."""
        async with httpx.AsyncClient(
            timeout=self.settings.research_timeout,
            headers={"User-Agent": _UA},
        ) as client:
            response = await client.get(
                "https://api.crossref.org/works",
                params={"query": query, "rows": min(limit, 5)},
            )
            response.raise_for_status()
            data = response.json()
        hits: list[SearchHit] = []
        for item in data.get("message", {}).get("items", []):
            title = " ".join(item.get("title", []) or []) or item.get("DOI", "")
            url = item.get("URL") or (
                f"https://doi.org/{item['DOI']}" if item.get("DOI") else ""
            )
            if not url:
                continue
            year = ""
            parts = (item.get("issued", {}) or {}).get("date-parts") or [[]]
            if parts and parts[0]:
                year = str(parts[0][0])
            publisher = item.get("publisher", "")
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    snippet=f"{publisher} {year}".strip(),
                    provider="crossref",
                )
            )
        return hits

    async def _github(self, query: str, limit: int) -> list[SearchHit]:
        """GitHub repository search — official, keyless (rate-limited).

        Uses GITHUB_TOKEN when present to raise the rate limit; never required.
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": _UA,
        }
        token = self.settings_research_key("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(
            timeout=self.settings.research_timeout, headers=headers
        ) as client:
            response = await client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "per_page": min(limit, 5)},
            )
            if response.status_code >= 400:
                return []
            data = response.json()
        hits: list[SearchHit] = []
        for item in data.get("items", []):
            url = item.get("html_url", "")
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=item.get("full_name", url),
                    url=url,
                    snippet=(item.get("description") or "")[:600],
                    provider="github",
                )
            )
        return hits

    async def _stackexchange(self, query: str, limit: int) -> list[SearchHit]:
        """Stack Exchange search API — official, keyless; practitioner answers."""
        async with httpx.AsyncClient(
            timeout=self.settings.research_timeout,
            headers={"User-Agent": _UA},
        ) as client:
            response = await client.get(
                "https://api.stackexchange.com/2.3/search/advanced",
                params={
                    "order": "desc",
                    "sort": "relevance",
                    "q": query,
                    "site": "stackoverflow",
                    "pagesize": min(limit, 5),
                },
            )
            if response.status_code >= 400:
                return []
            data = response.json()
        hits: list[SearchHit] = []
        for item in data.get("items", []):
            url = item.get("link", "")
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=_html_to_text(item.get("title", "")),
                    url=url,
                    snippet=f"score {item.get('score', 0)}, "
                    f"{'answered' if item.get('is_answered') else 'unanswered'}",
                    provider="stackexchange",
                )
            )
        return hits

    async def _fetch_all(self, urls: list[str]) -> list[RetrievedPage]:
        results = await asyncio.gather(
            *(self.fetch_page(url) for url in urls), return_exceptions=True
        )
        pages: list[RetrievedPage] = []
        for url, result in zip(urls, results):
            if isinstance(result, RetrievedPage):
                pages.append(result)
            else:
                pages.append(RetrievedPage(url=url, title="", ok=False))
        return pages

    async def fetch_page(self, url: str) -> RetrievedPage:
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.research_timeout,
                follow_redirects=True,
                headers={"User-Agent": _UA},
            ) as client:
                response = await client.get(url)
                if response.status_code >= 400:
                    return RetrievedPage(url=url, title="", ok=False)
                text = _html_to_text(response.text)
                title = _extract_title(response.text) or urlparse(url).netloc
                return RetrievedPage(url=url, title=title, text=text[:12000], ok=True)
        except Exception as exc:  # noqa: BLE001 - a fetch failure is data too
            logger.debug("fetch failed for %s: %s", url, exc)
            return RetrievedPage(url=url, title="", ok=False)

    # -- synthesis ---------------------------------------------------------- #
    def _build_sources(
        self, hits: list[SearchHit], pages: list[RetrievedPage]
    ) -> list[Source]:
        page_by_url = {p.url: p for p in pages}
        sources: list[Source] = []
        for hit in hits:
            page = page_by_url.get(hit.url)
            retrieved = bool(page and page.ok)
            sources.append(
                Source(
                    url=hit.url,
                    title=hit.title or (page.title if page else ""),
                    publisher=f"{urlparse(hit.url).netloc}"
                    + (f" via {hit.provider}" if hit.provider else ""),
                    finding=hit.snippet,
                    kind=EvidenceKind.PUBLISHED if retrieved else EvidenceKind.UNSUPPORTED,
                    reliability="high" if retrieved else "low",
                )
            )
        return sources

    def _render_context(
        self, sources: list[Source], pages: list[RetrievedPage]
    ) -> str:
        blocks: list[str] = []
        for index, source in enumerate(sources, 1):
            page = next((p for p in pages if p.url == source.url), None)
            excerpt = (page.text[:2500] if page and page.ok else source.finding)
            blocks.append(
                f"[{index}] {source.title}\nURL: {source.url}\n"
                f"RETRIEVED: {'yes' if source.kind == EvidenceKind.PUBLISHED else 'no'}\n"
                f"EXCERPT: {excerpt}"
            )
        return "\n\n".join(blocks)

    async def _synthesize(
        self, question: str, sources: list[Source], context: str
    ) -> ResearchReport:
        system = (
            "You are the research engine of LEVEL 5. Summarise the evidence for "
            "the question using ONLY the numbered sources provided. Cite sources "
            "as [1], [2]. Classify each finding as one of: verified (the source "
            "states it plainly), published (reported but not independently "
            "confirmed), experimental, assumption, hypothesis, unsupported. "
            "If the sources do not answer the question, say so and list it as a "
            "gap. Never invent sources or facts.\n\n"
            'Respond as JSON: {"summary": str, "findings": [{"text": str, '
            '"kind": str, "citations": [int]}], "hypotheses": [str], '
            '"gaps": [str], "recommendations": [str]}'
        )
        user = f"QUESTION: {question}\n\nSOURCES:\n{context}"
        data, _ = await self.llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=3000,
        )
        findings: list[str] = []
        for item in data.get("findings", []) or []:
            if isinstance(item, dict):
                kind = str(item.get("kind", "published"))
                cites = item.get("citations") or []
                cite_text = "".join(f"[{c}]" for c in cites if isinstance(c, int))
                findings.append(f"({kind}) {item.get('text', '')} {cite_text}".strip())
            elif isinstance(item, str):
                findings.append(item)

        retrieved_count = sum(1 for s in sources if s.kind == EvidenceKind.PUBLISHED)
        status = "completed" if retrieved_count else "partial"
        return ResearchReport(
            question=question,
            status=status,
            summary=str(data.get("summary", "")),
            findings=findings,
            sources=sources,
            hypotheses=[str(h) for h in (data.get("hypotheses") or [])],
            gaps=[str(g) for g in (data.get("gaps") or [])],
            recommendations=[str(r) for r in (data.get("recommendations") or [])],
            method="web_search",
        )

    async def _knowledge_only(self, question: str) -> ResearchReport:
        """No retrieval available: produce clearly-labelled hypotheses only."""
        system = (
            "You are the research engine of LEVEL 5. No web retrieval is "
            "available, so you MUST NOT claim any source exists. Provide only "
            "clearly-labelled prior-knowledge hypotheses, the uncertainties, and "
            "what would need to be verified. Respond as JSON: "
            '{"summary": str, "hypotheses": [str], "gaps": [str], '
            '"recommendations": [str]}'
        )
        data, _ = await self.llm.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        return ResearchReport(
            question=question,
            status="partial",
            summary=str(data.get("summary", "")),
            findings=[],
            sources=[],
            hypotheses=[str(h) for h in (data.get("hypotheses") or [])],
            gaps=[
                "No retrieval provider configured; findings are unverified.",
                *[str(g) for g in (data.get("gaps") or [])],
            ],
            recommendations=[str(r) for r in (data.get("recommendations") or [])],
            method="model_prior_no_retrieval",
        )


_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_ANY_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}")


def _query_terms(query: str, limit: int = 6) -> list[str]:
    """Extract meaningful search terms from a natural-language question.

    arXiv's query syntax needs bare terms, so stopwords and very short tokens
    are dropped and the order of first appearance is preserved.
    """
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "into", "how",
        "what", "why", "when", "does", "can", "are", "is", "of", "to", "in",
        "on", "a", "an", "be", "by", "or", "as", "at", "it", "we", "you",
        "best", "using", "use", "build", "create", "make", "design", "system",
    }
    seen: list[str] = []
    for token in _WORD.findall(query.lower()):
        if token in stop or token in seen:
            continue
        seen.append(token)
        if len(seen) >= limit:
            break
    return seen


def _html_to_text(raw: str) -> str:
    text = _TAG.sub(" ", raw)
    text = _ANY_TAG.sub(" ", text)
    text = html.unescape(text)
    return _WS.sub(" ", text).strip()


def _extract_title(raw: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    if match:
        return html.unescape(_WS.sub(" ", _ANY_TAG.sub("", match.group(1)))).strip()[:200]
    return ""
