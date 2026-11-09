"""LEVEL 5 local knowledge store: persistent memory and retrieval.

This is LEVEL 5's own memory. It stores project knowledge (requirements,
decisions, research findings, file notes, lessons) in SQLite and retrieves it
with a BM25 keyword ranking that needs **no model at all**. That is deliberate:
memory and retrieval must keep working when every inference backend is
unavailable, which is what makes the platform's context layer independent.

A semantic (embedding) index can be layered on later, but it is optional — the
keyword path is the baseline that always works. Nothing here calls a model or
an external service.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import aiosqlite

from level5.config import get_settings

KnowledgeKind = Literal[
    "requirement",
    "decision",
    "research",
    "artifact",
    "lesson",
    "note",
    "specification",
    "evaluation",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_project ON knowledge(project_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_kind ON knowledge(kind);
"""

_TOKEN = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class KnowledgeEntry:
    id: str
    project_id: str
    kind: str
    title: str
    text: str
    source: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "title": self.title,
            "text": self.text,
            "source": self.source,
            "created_at": self.created_at,
        }


@dataclass
class ScoredEntry:
    entry: KnowledgeEntry
    score: float


class KnowledgeStore:
    """Async SQLite knowledge store with BM25 retrieval (no model required)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_settings().db_path
        self._initialised = False

    async def init(self) -> None:
        if self._initialised:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        self._initialised = True

    async def add(
        self,
        *,
        project_id: str,
        kind: KnowledgeKind | str,
        title: str,
        text: str,
        source: str = "",
    ) -> KnowledgeEntry:
        await self.init()
        entry = KnowledgeEntry(
            id=f"kn_{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            kind=str(kind),
            title=title[:300],
            text=text,
            source=source,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO knowledge (id, project_id, kind, title, text, source, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.project_id,
                    entry.kind,
                    entry.title,
                    entry.text,
                    entry.source,
                    entry.created_at,
                ),
            )
            await db.commit()
        return entry

    async def all_for_project(self, project_id: str) -> list[KnowledgeEntry]:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM knowledge WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            )
            rows = await cursor.fetchall()
        return [_row_to_entry(r) for r in rows]

    async def search(
        self,
        query: str,
        *,
        project_id: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 8,
    ) -> list[ScoredEntry]:
        """Rank stored knowledge against a query with BM25.

        Pure Python and deterministic: the same corpus and query always give
        the same ranking, with no model and no network.
        """
        await self.init()
        sql = "SELECT * FROM knowledge"
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(kinds)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()
        entries = [_row_to_entry(r) for r in rows]
        return _bm25(query, entries, limit)


def _row_to_entry(row: aiosqlite.Row) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=row["id"],
        project_id=row["project_id"],
        kind=row["kind"],
        title=row["title"],
        text=row["text"],
        source=row["source"],
        created_at=row["created_at"],
    )


def _bm25(
    query: str, entries: list[KnowledgeEntry], limit: int, k1: float = 1.5, b: float = 0.75
) -> list[ScoredEntry]:
    """Okapi BM25 over the stored documents. No external dependency."""
    query_terms = tokenize(query)
    if not query_terms or not entries:
        return []
    docs = [tokenize(f"{e.title} {e.text}") for e in entries]
    doc_len = [len(d) for d in docs]
    avg_len = sum(doc_len) / len(docs) if docs else 0.0
    n = len(docs)
    df: Counter[str] = Counter()
    for d in docs:
        for term in set(d):
            df[term] += 1
    scored: list[ScoredEntry] = []
    for entry, tokens, length in zip(entries, docs, doc_len):
        tf = Counter(tokens)
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + k1 * (1 - b + b * (length / avg_len if avg_len else 1))
            score += idf * (tf[term] * (k1 + 1)) / denom
        if score > 0:
            scored.append(ScoredEntry(entry=entry, score=round(score, 4)))
    scored.sort(key=lambda s: (-s.score, s.entry.created_at))
    return scored[:limit]


_store: KnowledgeStore | None = None


def get_knowledge_store() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore()
    return _store
