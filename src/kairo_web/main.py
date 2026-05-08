"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlmodel import Session

from kairo_web import __version__
from kairo_web.config import get_settings
from kairo_web.db import engine, get_session
from kairo_web.paths import STATIC_DIR
from kairo_web.routes import digest as digest_routes
from kairo_web.routes import pages as page_routes
from kairo_web.routes import settings as settings_routes
from kairo_web.routes import tasks as task_routes
from kairo_web.routes import workspaces as workspace_routes
from kairo_web.services.rollover import rollover_all_workspaces

logger = structlog.get_logger(__name__)


def _scheduled_rollover() -> None:
    """APScheduler job body — picks current ISO week and rolls every workspace forward.

    Errors are caught and logged so a transient failure (e.g. DB locked) doesn't
    take the scheduler thread down with it.
    """
    try:
        with Session(engine) as session:
            summaries = rollover_all_workspaces(session)
        moved = sum(s.moved for s in summaries)
        logger.info(
            "auto_rollover_complete",
            workspaces=len(summaries),
            tasks_moved=moved,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto_rollover_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 — app param is part of the protocol
    """Start the rollover scheduler on app boot, shut it down on exit."""
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone=settings.KAIRO_TIMEZONE)
    scheduler.add_job(
        _scheduled_rollover,
        trigger=CronTrigger(
            day_of_week="sun",
            hour=23,
            minute=59,
            timezone=settings.KAIRO_TIMEZONE,
        ),
        id="weekly_rollover",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,  # if the box was off, run within an hour of comeback
    )
    scheduler.start()
    logger.info("scheduler_started", timezone=settings.KAIRO_TIMEZONE)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")


def create_app() -> FastAPI:
    settings = get_settings()  # noqa: F841 — fail fast on bad config

    app = FastAPI(
        title="Kairo Web",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
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
