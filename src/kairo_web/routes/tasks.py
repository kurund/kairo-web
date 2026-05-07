"""HTMX task-mutation endpoints.

All endpoints follow the same pattern:
  - Mutate the task in the chosen workspace + week
  - Re-render and return the week_main.html partial for that view
  - HTMX swaps it into #week-main on the client

Endpoints share the URL prefix /w/{slug}/week/{year_week}/tasks/...
so the request path itself encodes which view should be re-rendered.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func
from sqlmodel import Session, select

from kairo_web.db import get_session
from kairo_web.models import Tag, Task, TaskTag
from kairo_web.paths import TEMPLATE_DIR
from kairo_web.services import queries
from kairo_web.services.capture import parse_capture
from kairo_web.utils import (
    format_hours,
    format_today_label,
    format_week_label,
    get_current_iso_week,
    shift_iso_week,
    tag_color_for,
)
from kairo_web.workspace_meta import derive_bg_fg

router = APIRouter(tags=["tasks"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

_WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$")


# ----- Helpers -------------------------------------------------------------


def _parse_year_week(year_week: str) -> tuple[int, int]:
    m = _WEEK_RE.match(year_week)
    if not m:
        raise HTTPException(status_code=400, detail="week must look like 2026-W19")
    iso_year = int(m.group(1))
    iso_week = int(m.group(2))
    if not (1 <= iso_week <= 53):
        raise HTTPException(status_code=400, detail="iso week must be 1–53")
    return iso_year, iso_week


def _week_url(slug: str, year: int, week: int) -> str:
    return f"/w/{slug}/week/{year}-W{week:02d}"


def _workspace_dict(slug: str, name: str, color: str, badge_count: int = 0) -> dict:
    bg, fg = derive_bg_fg(color)
    return {
        "slug": slug,
        "name": name,
        "color_hex": color,
        "color_bg": bg,
        "color_fg": fg,
        "badge_count": badge_count,
    }


def _task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "is_today": bool(task.is_today),
        "project": task.project,
        "estimate_hours": task.estimate_hours,
        "estimate_label": format_hours(task.estimate_hours),
        "tags": [{"name": t.name, "color": tag_color_for(t.name)} for t in task.tags],
    }


def _build_partial_context(
    session: Session,
    workspace_slug: str,
    iso_year: int,
    iso_week: int,
) -> dict:
    """Rebuild the same context the GET week route uses, so the partial renders identically."""
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"workspace '{workspace_slug}' not found")
    assert workspace.id is not None

    week_tasks = queries.get_week_tasks(session, workspace.id, iso_year, iso_week)
    inbox_tasks = queries.get_inbox_tasks(session, workspace.id)
    badge_counts = queries.get_workspace_badges(session, iso_year, iso_week)
    all_workspaces = queries.list_workspaces(session)

    week_task_dicts = [_task_to_dict(t) for t in week_tasks]
    today_task_dicts = [t for t in week_task_dicts if t["is_today"]]

    open_count = sum(1 for t in week_task_dicts if t["status"] == "open")
    done_count = sum(1 for t in week_task_dicts if t["status"] == "completed")
    total = open_count + done_count
    estimated = round(
        sum((t["estimate_hours"] or 0) for t in week_task_dicts if t["status"] == "open"), 2
    )
    logged = round(
        sum((t["estimate_hours"] or 0) for t in week_task_dicts if t["status"] == "completed"), 2
    )
    percent = int(round(100 * done_count / total)) if total else 0

    prev_year, prev_week = shift_iso_week(iso_year, iso_week, -1)
    next_year, next_week = shift_iso_week(iso_year, iso_week, +1)
    today_year, today_week = get_current_iso_week()

    return {
        "workspace": _workspace_dict(workspace.slug, workspace.name, workspace.color),
        "workspaces": [
            _workspace_dict(w.slug, w.name, w.color, badge_counts.get(w.id, 0))
            for w in all_workspaces
        ],
        "iso_year": iso_year,
        "iso_week": iso_week,
        "year_week": f"{iso_year}-W{iso_week:02d}",
        "week_label": format_week_label(iso_year, iso_week),
        "prev_week_url": _week_url(workspace.slug, prev_year, prev_week),
        "next_week_url": _week_url(workspace.slug, next_year, next_week),
        "today_url": _week_url(workspace.slug, today_year, today_week),
        "today_date_label": format_today_label(),
        "today_done_count": sum(1 for t in today_task_dicts if t["status"] == "completed"),
        "today_total_count": len(today_task_dicts),
        "today_tasks": today_task_dicts,
        "week_tasks": week_task_dicts,
        "inbox_tasks": [{"id": t.id, "title": t.title} for t in inbox_tasks],
        "inbox_count": len(inbox_tasks),
        "stats": {
            "open": open_count,
            "done": done_count,
            "estimated_hours": estimated,
            "logged_hours": logged,
            "percent_complete": percent,
        },
    }


def _render_partial(
    request: Request,
    session: Session,
    workspace_slug: str,
    year_week: str,
) -> HTMLResponse:
    iso_year, iso_week = _parse_year_week(year_week)
    ctx = _build_partial_context(session, workspace_slug, iso_year, iso_week)
    return templates.TemplateResponse(request, "partials/week_main.html", ctx)


def _next_position(session: Session, workspace_id: int, iso_year: int | None, iso_week: int | None) -> int:
    """MAX(position) + 1 for the given (workspace, week) bucket. Inbox uses NULL/NULL."""
    stmt = select(func.max(Task.position)).where(Task.workspace_id == workspace_id)
    if iso_year is None:
        stmt = stmt.where(Task.iso_year.is_(None), Task.iso_week.is_(None))
    else:
        stmt = stmt.where(Task.iso_year == iso_year, Task.iso_week == iso_week)
    current_max = session.exec(stmt).one_or_none()
    return (current_max or 0) + 1


def _ensure_tags(session: Session, workspace_id: int, names: list[str]) -> list[Tag]:
    """Find-or-create tags by name, scoped to workspace."""
    out: list[Tag] = []
    for name in names:
        existing = session.exec(
            select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == name)
        ).first()
        if existing:
            out.append(existing)
        else:
            tag = Tag(workspace_id=workspace_id, name=name)
            session.add(tag)
            session.flush()
            out.append(tag)
    return out


def _get_task_for_workspace(session: Session, task_id: int, workspace_id: int) -> Task:
    task = session.exec(
        select(Task).where(Task.id == task_id, Task.workspace_id == workspace_id)
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----- Endpoints -----------------------------------------------------------


@router.post("/w/{workspace_slug}/week/{year_week}/tasks", response_class=HTMLResponse)
def create_task(
    request: Request,
    workspace_slug: str,
    year_week: str,
    capture_text: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Create a new task from the capture bar. Empty input is a silent no-op."""
    iso_year, iso_week = _parse_year_week(year_week)
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"workspace '{workspace_slug}' not found")
    assert workspace.id is not None

    parsed = parse_capture(capture_text)
    if parsed.title.strip():
        position = _next_position(session, workspace.id, iso_year, iso_week)
        task = Task(
            workspace_id=workspace.id,
            title=parsed.title,
            project=parsed.project,
            estimate_hours=parsed.estimate_hours,
            position=position,
            iso_year=iso_year,
            iso_week=iso_week,
            created_at=_utcnow(),
        )
        session.add(task)
        session.flush()
        assert task.id is not None
        for tag in _ensure_tags(session, workspace.id, parsed.tags):
            assert tag.id is not None
            session.add(TaskTag(task_id=task.id, tag_id=tag.id))
        session.commit()

    return _render_partial(request, session, workspace_slug, year_week)


@router.post(
    "/w/{workspace_slug}/week/{year_week}/tasks/{task_id}/complete",
    response_class=HTMLResponse,
)
def toggle_complete(
    request: Request,
    workspace_slug: str,
    year_week: str,
    task_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)

    if task.status == "completed":
        task.status = "open"
        task.completed_at = None
    else:
        task.status = "completed"
        task.completed_at = _utcnow()
    session.add(task)
    session.commit()

    return _render_partial(request, session, workspace_slug, year_week)


@router.post(
    "/w/{workspace_slug}/week/{year_week}/tasks/{task_id}/today",
    response_class=HTMLResponse,
)
def toggle_today(
    request: Request,
    workspace_slug: str,
    year_week: str,
    task_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)
    task.is_today = not task.is_today
    session.add(task)
    session.commit()

    return _render_partial(request, session, workspace_slug, year_week)


@router.post(
    "/w/{workspace_slug}/week/{year_week}/tasks/{task_id}/schedule",
    response_class=HTMLResponse,
)
def toggle_schedule(
    request: Request,
    workspace_slug: str,
    year_week: str,
    task_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Toggle a task between inbox and the viewed week."""
    iso_year, iso_week = _parse_year_week(year_week)
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)

    if task.iso_year is None and task.iso_week is None:
        # Inbox → schedule into viewed week
        task.iso_year = iso_year
        task.iso_week = iso_week
        task.position = _next_position(session, workspace.id, iso_year, iso_week)
    else:
        # Scheduled → move back to inbox
        task.iso_year = None
        task.iso_week = None
        task.is_today = False  # inbox tasks shouldn't carry the today flag
        task.position = _next_position(session, workspace.id, None, None)
    session.add(task)
    session.commit()

    return _render_partial(request, session, workspace_slug, year_week)


@router.post(
    "/w/{workspace_slug}/week/{year_week}/tasks/{task_id}/move",
    response_class=HTMLResponse,
)
def move_task(
    request: Request,
    workspace_slug: str,
    year_week: str,
    task_id: int,
    direction: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Swap position with the adjacent task in the same week (direction='up'|'down')."""
    if direction not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="direction must be 'up' or 'down'")
    iso_year, iso_week = _parse_year_week(year_week)
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)
    if task.iso_year != iso_year or task.iso_week != iso_week:
        raise HTTPException(status_code=400, detail="task is not in the viewed week")

    if direction == "up":
        neighbor = session.exec(
            select(Task)
            .where(
                Task.workspace_id == workspace.id,
                Task.iso_year == iso_year,
                Task.iso_week == iso_week,
                Task.position < task.position,
            )
            .order_by(Task.position.desc())
            .limit(1)
        ).first()
    else:
        neighbor = session.exec(
            select(Task)
            .where(
                Task.workspace_id == workspace.id,
                Task.iso_year == iso_year,
                Task.iso_week == iso_week,
                Task.position > task.position,
            )
            .order_by(Task.position.asc())
            .limit(1)
        ).first()

    if neighbor is not None:
        task.position, neighbor.position = neighbor.position, task.position
        session.add_all([task, neighbor])
        session.commit()

    return _render_partial(request, session, workspace_slug, year_week)


@router.post(
    "/w/{workspace_slug}/week/{year_week}/tasks/{task_id}/delete",
    response_class=HTMLResponse,
)
def delete_task(
    request: Request,
    workspace_slug: str,
    year_week: str,
    task_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)

    # Cascade-delete the task_tag rows manually (the migration sets ON DELETE
    # CASCADE on the FKs, but SQLite needs PRAGMA foreign_keys=ON which we
    # don't currently enforce; doing it explicitly is safer).
    session.exec(delete(TaskTag).where(TaskTag.task_id == task.id))  # type: ignore[arg-type]
    session.delete(task)
    session.commit()

    return _render_partial(request, session, workspace_slug, year_week)
