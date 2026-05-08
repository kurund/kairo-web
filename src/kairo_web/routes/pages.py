"""HTML page routes (full document responses).

Routes:
  GET /                          → redirect to active workspace's current week
  GET /login                     → magic-link login form (sending is stubbed for now)
  POST /login                    → stub (milestone 1)
  GET /w/<slug>/week/<YYYY>-W<W> → live week view (DB-backed)
  GET /preview[?ws=…]            → layout-only preview against hardcoded dummy data
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from kairo_web.db import get_session
from kairo_web.paths import TEMPLATE_DIR
from kairo_web.request_filters import extract_week_filters
from kairo_web.utils import (
    format_hours,
    format_today_label,
    format_week_label,
    get_current_iso_week,
)
from kairo_web.view_context import build_inbox_context, build_week_context, workspace_dict

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


# ----- Live week view -------------------------------------------------------


# Context-building lives in `view_context.build_week_context` so the partial
# response in routes/tasks.py renders identically.


@router.get("/w/{workspace_slug}/week/{year_week}", response_class=HTMLResponse)
def get_week(
    request: Request,
    workspace_slug: str,
    year_week: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render the week view for a workspace + ISO week (e.g. `/w/fulltime/week/2026-W19`).

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


# ----- Preview (dummy data, no DB) ------------------------------------------


def _build_preview_context(active_slug: str) -> dict:
    """Hardcoded dummy data for the week view, varying slightly by workspace."""
    if active_slug == "fulltime":
        today = [
            ("Review PR #2143 for auth-rewrite", "open", "auth-rewrite", 0.75, [("urgent", "red")]),
            ("1:1 with manager", "completed", None, 0.5, []),
            ("Ship dashboard v2 to staging", "open", None, 1.5, [("shipping", "teal")]),
        ]
        rest = [
            ("Write design doc for migration plan", "open", "migration", 2.0, [("writing", "indigo")]),
            ("Reply to grant proposal email", "open", None, 0.5, [("admin", "slate")]),
            ("Sprint planning prep", "open", "q2-roadmap", 1.0, [("planning", "indigo")]),
            ("Onboard new contractor", "completed", None, 1.5, []),
        ]
        inbox = [
            "Look into Postgres replication options",
            "Email contractor re: agreement",
            "Schedule team retro",
            "Test new monitoring tool",
        ]
        active_name = "Full-time"
    elif active_slug == "consulting":
        today = [
            ("Send draft proposal to Acme", "open", "acme", 1.0, [("urgent", "red")]),
            ("Review client feedback on dashboard", "open", "beacon", 0.5, []),
            ("Invoice Q1 work for Sigma", "open", "sigma", 0.25, [("admin", "slate")]),
        ]
        rest = [
            ("Prep pitch deck for new lead", "open", "newbiz", 2.0, [("writing", "indigo")]),
            ("Code review for Acme integration", "open", "acme", 1.5, []),
            ("Quarterly check-in with Beacon", "open", "beacon", 0.5, [("meeting", "amber")]),
        ]
        inbox = [
            "Follow up with Sigma re: scope",
            "Update consulting contract template",
            "Block out August vacation in calendar",
        ]
        active_name = "Consulting"
    else:
        active_slug = "personal"
        today = [
            ("Pay credit card", "open", None, 0.25, [("bills", "amber")]),
            ("Pick up dry cleaning", "completed", None, 0.25, []),
            ("Call mom", "open", None, 0.5, [("family", "pink")]),
        ]
        rest = [
            ("Plan weekend trip", "open", "trip", None, [("family", "pink")]),
            ("Renew car insurance", "open", None, 0.5, [("admin", "slate")]),
            ("Doctor appointment — annual checkup", "open", None, 1.0, []),
            ("Book dentist for cleaning", "open", None, 0.25, []),
            ("Sort through monsoon storage", "open", "home", 2.0, []),
        ]
        inbox = [
            "Read 'Designing Data-Intensive Applications'",
            "Try new pasta recipe from Sunday Times",
            "Order new running shoes",
        ]
        active_name = "Personal"

    # Hardcoded preview switcher — three sample workspaces with palette colors,
    # purely for showing the layout. Independent of the live DB workspaces.
    workspaces_for_switcher = [
        workspace_dict("fulltime", "Full-time", "#0F766E", 5),
        workspace_dict("consulting", "Consulting", "#4338CA", 3),
        workspace_dict("personal", "Personal", "#BE185D", 5),
    ]
    workspace = next(w for w in workspaces_for_switcher if w["slug"] == active_slug)
    workspace["badge_count"] = 0  # active tab doesn't show badge

    def _to_dict(items: list[tuple]) -> list[dict]:
        return [
            {
                "id": i,
                "title": title,
                "status": status,
                "is_today": False,
                "project": project,
                "estimate_hours": est,
                "estimate_label": format_hours(est),
                "tags": [{"name": n, "color": c} for n, c in tags],
            }
            for i, (title, status, project, est, tags) in enumerate(items)
        ]

    today_tasks = _to_dict(today)
    today_titles = {t["title"] for t in today_tasks}
    week_tasks = _to_dict(today + rest)
    for t in week_tasks:
        if t["title"] in today_titles:
            t["is_today"] = True

    inbox_tasks = [{"id": i, "title": title} for i, title in enumerate(inbox)]

    open_count = sum(1 for t in week_tasks if t["status"] == "open")
    done_count = sum(1 for t in week_tasks if t["status"] == "completed")
    total = open_count + done_count
    estimated = round(sum((t["estimate_hours"] or 0) for t in week_tasks if t["status"] == "open"), 2)
    logged = round(sum((t["estimate_hours"] or 0) for t in week_tasks if t["status"] == "completed"), 2)
    percent = int(round(100 * done_count / total)) if total else 0

    return {
        "workspace": workspace,
        "workspaces": workspaces_for_switcher,
        "iso_year": 2026,
        "iso_week": 19,
        "year_week": "2026-W19",
        "week_label": format_week_label(2026, 19),
        "prev_week_url": f"/preview?ws={active_slug}",
        "next_week_url": f"/preview?ws={active_slug}",
        "today_url": f"/preview?ws={active_slug}",
        "today_date_label": format_today_label(),
        "today_done_count": sum(1 for t in today_tasks if t["status"] == "completed"),
        "today_total_count": len(today_tasks),
        "today_tasks": today_tasks,
        "week_tasks": week_tasks,
        "week_total_count": len(week_tasks),
        "inbox_tasks": inbox_tasks,
        "inbox_count": len(inbox_tasks),
        "stats": {
            "open": open_count,
            "done": done_count,
            "estimated_hours": estimated,
            "logged_hours": logged,
            "percent_complete": percent,
        },
        # Filter state — preview is always unfiltered.
        "filter_tag": None,
        "filter_project": None,
        "filter_active": False,
        "filter_qs": "",
        "available_tags": [],
        "available_projects": [],
        "tag_options": [],
        "project_options": [],
        "tag_remove_url": "",
        "project_remove_url": "",
        "clear_all_filters_url": f"/preview?ws={active_slug}",
    }


@router.get("/preview", response_class=HTMLResponse)
def preview_week(
    request: Request,
    ws: str = Query(default="fulltime", description="Workspace slug to preview."),
) -> HTMLResponse:
    """Render the week view against hardcoded dummy data (for layout review)."""
    if ws not in {"fulltime", "consulting", "personal"}:
        ws = "fulltime"
    return templates.TemplateResponse(request, "week.html", _build_preview_context(ws))
