"""HTML page routes (full document responses).

Routes:
  GET /                          → redirect to default workspace's current week
  GET /login                     → magic-link login form (sending is stubbed for now)
  POST /login                    → stub (milestone 1)
  GET /w/<slug>/week/<YYYY>-W<W> → live week view (DB-backed)
  GET /w/<slug>/inbox            → workspace inbox (DB-backed)
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from kairo_web.db import get_session
from kairo_web.paths import TEMPLATE_DIR
from kairo_web.request_filters import extract_week_filters
from kairo_web.utils import get_current_iso_week
from kairo_web.view_context import build_inbox_context, build_week_context

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Hardcoded fallback used only when the DB has no workspaces at all (e.g. a
# fresh install before `kairo-web init`). Once init runs, the seeded workspace
# is marked is_default=True and `_default_workspace_slug()` returns it.
_FALLBACK_WORKSPACE_SLUG = "personal"

_WEEK_PATH_RE = re.compile(r"^(\d{4})-W(\d{1,2})$")


# ----- Login (still skeletal) -----------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"sent": False})


@router.post("/login", response_class=HTMLResponse)
def login_post(request: Request) -> HTMLResponse:
    # TODO(milestone-auth): generate magic-link token, send via Resend.
    return templates.TemplateResponse(request, "login.html", {"sent": True})


# ----- Root: redirect to current week ---------------------------------------


def _default_workspace_slug(session: Session) -> str:
    """Pick the default workspace slug. Order of preference:

    1. The workspace where `is_default = true`
    2. The first workspace by id (lowest)
    3. The hardcoded fallback (only if the DB is completely empty)
    """
    from kairo_web.models import Workspace
    ws = session.exec(
        select(Workspace).where(Workspace.is_default == True).order_by(Workspace.id)  # noqa: E712
    ).first()
    if ws is None:
        ws = session.exec(select(Workspace).order_by(Workspace.id)).first()
    return ws.slug if ws else _FALLBACK_WORKSPACE_SLUG  # type: ignore[no-any-return]


@router.get("/", include_in_schema=False)
def root(session: Session = Depends(get_session)) -> RedirectResponse:
    iso_year, iso_week = get_current_iso_week()
    slug = _default_workspace_slug(session)
    return RedirectResponse(
        url=f"/w/{slug}/week/{iso_year}-W{iso_week:02d}",
        status_code=302,
    )


# ----- Live pages -----------------------------------------------------------
# Context-building lives in `kairo_web.view_context` so the partial responses
# in `routes/tasks.py` render identically.


@router.get("/w/{workspace_slug}/week/{year_week}", response_class=HTMLResponse)
def get_week(
    request: Request,
    workspace_slug: str,
    year_week: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render the week view for a workspace + ISO week (e.g. `/w/personal/week/2026-W19`).

    Optional query params:
      ?tag=<name>      — restrict Today strip + week table to tasks with this tag
      ?project=<name>  — restrict to tasks under this project
    Stats footer remains unfiltered (shows the full week).
    """
    m = _WEEK_PATH_RE.match(year_week)
    if not m:
        raise HTTPException(status_code=400, detail="week must look like 2026-W19")
    iso_year = int(m.group(1))
    iso_week = int(m.group(2))
    if not (1 <= iso_week <= 53):
        raise HTTPException(status_code=400, detail="iso week must be 1–53")

    filter_tag, filter_project = extract_week_filters(request)
    ctx = build_week_context(
        session, workspace_slug, iso_year, iso_week,
        filter_tag=filter_tag, filter_project=filter_project,
    )
    return templates.TemplateResponse(request, "week.html", ctx)


@router.get("/w/{workspace_slug}/inbox", response_class=HTMLResponse)
def get_inbox(
    request: Request,
    workspace_slug: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Inbox page for a workspace — capture-and-triage view, peer of the week page.

    Optional query params:
      ?tag=<name>      — restrict to inbox tasks with that tag
      ?project=<name>  — restrict to that project
      ?sort=<key>      — newest|oldest|project|title (default: newest)
    """
    filter_tag, filter_project = extract_week_filters(request)
    sort = request.query_params.get("sort") or "newest"
    ctx = build_inbox_context(
        session, workspace_slug,
        filter_tag=filter_tag, filter_project=filter_project, sort=sort,
    )
    return templates.TemplateResponse(request, "inbox.html", ctx)
