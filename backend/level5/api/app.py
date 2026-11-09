"""LEVEL 5 FastAPI application.

Exposes the platform over REST + Server-Sent Events and serves the built
frontend when it is present. Long-running work is dispatched to background
asyncio tasks; clients watch progress through the SSE stream.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from level5.api.routes import router
from level5.config import get_settings
from level5.runtime.agent_server import get_agent_client
from level5.storage.store import get_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("level5.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await get_store().init()
    server = await get_agent_client().healthy()
    if server:
        logger.info(
            "Agent Server reachable: v%s (sdk %s)",
            server.get("version"),
            server.get("sdk_version"),
        )
    else:
        logger.warning("Agent Server not reachable at %s", settings.agent_server_url)
    logger.info("LEVEL 5 data dir: %s", settings.data_dir)
    yield
    await get_agent_client().aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LEVEL 5",
        description=(
            "Autonomous Universal Engineering & Creation Intelligence. "
            "Research, design, build, test and deliver technical products."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=frontend_dist / "assets"),
            name="assets",
        )

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @app.get("/{full_path:path}")
        async def spa(full_path: str) -> FileResponse:
            candidate = frontend_dist / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")
    else:
        @app.get("/")
        async def placeholder() -> dict[str, str]:
            return {
                "service": "LEVEL 5",
                "status": "running",
                "note": "Frontend not built. Run the frontend dev server or build it.",
                "api_docs": "/docs",
            }

    return app


app = create_app()
