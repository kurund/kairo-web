"""FastAPI application entry point."""

from __future__ import annotations

import structlog
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlmodel import Session

from kairo_web import __version__
from kairo_web.config import get_settings
from kairo_web.db import get_session
from kairo_web.paths import STATIC_DIR
from kairo_web.routes import digest as digest_routes
from kairo_web.routes import pages as page_routes
from kairo_web.routes import settings as settings_routes
from kairo_web.routes import tasks as task_routes
from kairo_web.routes import workspaces as workspace_routes

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()  # noqa: F841 — fail fast on bad config

    app = FastAPI(
        title="Kairo Web",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(page_routes.router)
    app.include_router(workspace_routes.router)
    app.include_router(task_routes.router)
    app.include_router(digest_routes.router)
    app.include_router(settings_routes.router)

    @app.get("/healthz", tags=["meta"])
    def healthz(session: Session = Depends(get_session)) -> JSONResponse:
        """Liveness + DB ping."""
        try:
            session.exec(text("SELECT 1"))  # type: ignore[arg-type]
            db_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("healthz_db_fail", error=str(exc))
            db_ok = False
        return JSONResponse({"ok": True, "version": __version__, "db": db_ok})

    return app


app = create_app()
