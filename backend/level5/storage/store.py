"""Persistent project storage backed by SQLite.

Projects are stored as JSON documents with a few indexed columns for listing
and search. This keeps the schema stable while the domain model evolves, and
it lets an unfinished project resume after a restart.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from level5.config import get_settings
from level5.models import Project, ProjectStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    domain TEXT NOT NULL,
    caber_module TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    document TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_domain ON projects(domain);

CREATE TABLE IF NOT EXISTS improvements (
    id TEXT PRIMARY KEY,
    area TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    suite TEXT NOT NULL,
    task TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document TEXT NOT NULL
);
"""


class ProjectStore:
    """Async repository for LEVEL 5 projects."""

    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self.db_path = db_path or settings.db_path
        self._initialised = False

    async def init(self) -> None:
        if self._initialised:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        self._initialised = True

    async def save(self, project: Project) -> None:
        await self.init()
        project.updated_at = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO projects
                  (id, name, status, domain, caber_module, created_at, updated_at, document)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  status=excluded.status,
                  domain=excluded.domain,
                  caber_module=excluded.caber_module,
                  updated_at=excluded.updated_at,
                  document=excluded.document
                """,
                (
                    project.id,
                    project.name,
                    project.status.value,
                    project.specification.domain.value,
                    project.specification.caber_module.value,
                    project.created_at.isoformat(),
                    project.updated_at.isoformat(),
                    project.model_dump_json(),
                ),
            )
            await db.commit()

    async def get(self, project_id: str) -> Project | None:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT document FROM projects WHERE id = ?", (project_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return Project.model_validate_json(row[0])

    async def list(
        self, *, limit: int = 100, status: str | None = None
    ) -> list[dict[str, Any]]:
        await self.init()
        query = (
            "SELECT id, name, status, domain, caber_module, created_at, updated_at "
            "FROM projects"
        )
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "status": r[2],
                "domain": r[3],
                "caber_module": r[4],
                "created_at": r[5],
                "updated_at": r[6],
            }
            for r in rows
        ]

    async def delete(self, project_id: str) -> bool:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def count_by_status(self) -> dict[str, int]:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT status, COUNT(*) FROM projects GROUP BY status"
            ) as cursor:
                rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    # -- improvement records (self-improvement loop) ------------------------ #
    async def save_improvement(self, record: dict[str, Any]) -> None:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO improvements (id, area, title, status, created_at, document)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  area=excluded.area, title=excluded.title,
                  status=excluded.status, document=excluded.document
                """,
                (
                    record["id"],
                    record.get("area", "general"),
                    record.get("title", ""),
                    record.get("status", "proposed"),
                    record.get("created_at", datetime.now(timezone.utc).isoformat()),
                    json.dumps(record),
                ),
            )
            await db.commit()

    async def list_improvements(self, limit: int = 100) -> list[dict[str, Any]]:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT document FROM improvements ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [json.loads(r[0]) for r in rows]

    # -- benchmark records -------------------------------------------------- #
    async def save_benchmark(self, record: dict[str, Any]) -> None:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO benchmarks (id, suite, task, created_at, document)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET document=excluded.document
                """,
                (
                    record["id"],
                    record.get("suite", "default"),
                    record.get("task", ""),
                    record.get("created_at", datetime.now(timezone.utc).isoformat()),
                    json.dumps(record),
                ),
            )
            await db.commit()

    async def list_benchmarks(self, limit: int = 200) -> list[dict[str, Any]]:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT document FROM benchmarks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [json.loads(r[0]) for r in rows]


_store: ProjectStore | None = None


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        _store = ProjectStore()
    return _store
