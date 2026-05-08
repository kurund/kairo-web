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
from kairo_web.request_filters import extract_inbox_filters, extract_week_filters
from kairo_web.services import queries
from kairo_web.services.capture import parse_capture
from kairo_web.services.rollover import rollover_workspace
from kairo_web.utils import get_current_iso_week, shift_iso_week
from kairo_web.view_context import build_inbox_context, build_week_context

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


def _render_partial(
    request: Request,
    session: Session,
    workspace_slug: str,
    year_week: str,
) -> HTMLResponse:
    """Re-render the swappable #week-main partial after a mutation.

    Pulls the active filter (tag/project) out of HX-Current-URL so mutations
    preserve filter state automatically.
    """
    iso_year, iso_week = _parse_year_week(year_week)
    filter_tag, filter_project = extract_week_filters(request)
    ctx = build_week_context(
        session, workspace_slug, iso_year, iso_week,
        filter_tag=filter_tag, filter_project=filter_project,
    )
    return templates.TemplateResponse(request, "partials/week_main.html", ctx)


def _render_inbox_partial(
    request: Request,
    session: Session,
    workspace_slug: str,
) -> HTMLResponse:
    """Re-render the swappable #inbox-main partial after a mutation.

    Filter + sort state are extracted from HX-Current-URL so they survive
    mutations transparently, just like on the week page.
    """
    filter_tag, filter_project, sort = extract_inbox_filters(request)
    ctx = build_inbox_context(
        session, workspace_slug,
        filter_tag=filter_tag, filter_project=filter_project, sort=sort,
    )
    return templates.TemplateResponse(request, "partials/inbox_main.html", ctx)


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
    destination: str = Form("inbox"),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Create a new task from the capture bar. Empty input is a silent no-op.

    `destination` controls where the task lands:
      - "inbox" (default): task is unscheduled; lands in the workspace inbox
        for triage. Enter on the capture bar produces this.
      - "week": task is scheduled directly into the viewed ISO week. Submitted
        when the user clicks the secondary "This week" button.

    The default-to-inbox flow nudges good triage habits — capture cheaply now,
    decide where it belongs later.
    """
    iso_year, iso_week = _parse_year_week(year_week)
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"workspace '{workspace_slug}' not found")
    assert workspace.id is not None

    parsed = parse_capture(capture_text)
    if parsed.title.strip():
        if destination == "week":
            target_year: int | None = iso_year
            target_week: int | None = iso_week
        else:
            target_year = None
            target_week = None
        position = _next_position(session, workspace.id, target_year, target_week)
        task = Task(
            workspace_id=workspace.id,
            title=parsed.title,
            project=parsed.project,
            estimate_hours=parsed.estimate_hours,
            position=position,
            iso_year=target_year,
            iso_week=target_week,
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


_ESTIMATE_RE = re.compile(r"^(\d+(?:\.\d+)?)([hm])$", re.IGNORECASE)


def _parse_estimate_text(text: str) -> float | None:
    """Parse '2h' / '0.5h' / '30m' → hours float. Empty or unparseable → None."""
    text = text.strip().lower()
    if not text:
        return None
    m = _ESTIMATE_RE.match(text)
    if not m:
        return None
    value = float(m.group(1))
    return value if m.group(2) == "h" else value / 60.0


@router.post(
    "/w/{workspace_slug}/week/{year_week}/tasks/{task_id}/edit",
    response_class=HTMLResponse,
)
def edit_task(
    request: Request,
    workspace_slug: str,
    year_week: str,
    task_id: int,
    title: str = Form(""),
    tags: str = Form(""),
    project: str = Form(""),
    estimate: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Update a task's title, tags, project, and estimate in one POST.

    Tag input is whitespace-separated names; existing TaskTag rows are
    replaced wholesale with the new set (find-or-create per name).
    Empty title is silently ignored — HTML5 `required` already gates this
    on the client; server-side check is defense in depth.
    """
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)

    title_clean = title.strip()
    if not title_clean:
        # Refuse: an empty title would orphan the task. Re-render unchanged.
        return _render_partial(request, session, workspace_slug, year_week)

    task.title = title_clean
    task.project = project.strip() or None
    task.estimate_hours = _parse_estimate_text(estimate)

    # Reconcile tag links: drop existing, insert new. Tag names are lowercased
    # and validated (invalid characters → silently dropped, matching capture parser).
    new_names: list[str] = []
    for raw in tags.split():
        name = raw.strip().lstrip("#").lower()
        if not name:
            continue
        # Mirror the capture parser's _WORD_RE — alphanumerics, underscore, hyphen.
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
            continue
        if name not in new_names:
            new_names.append(name)

    session.exec(delete(TaskTag).where(TaskTag.task_id == task.id))  # type: ignore[arg-type]
    for tag in _ensure_tags(session, workspace.id, new_names):
        assert tag.id is not None
        session.add(TaskTag(task_id=task.id, tag_id=tag.id))

    session.add(task)
    session.commit()
    return _render_partial(request, session, workspace_slug, year_week)


@router.post(
    "/w/{workspace_slug}/week/{year_week}/rollover",
    response_class=HTMLResponse,
)
def manual_rollover(
    request: Request,
    workspace_slug: str,
    year_week: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Move open tasks from the viewed week to the next week (manual button).

    Same logic as the Sunday-night auto-rollover, but scoped to the workspace
    + week the user is currently looking at.
    """
    iso_year, iso_week = _parse_year_week(year_week)
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    to_year, to_week = shift_iso_week(iso_year, iso_week, +1)
    rollover_workspace(session, workspace.id, iso_year, iso_week, to_year, to_week)
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


# ===== Inbox endpoints =====================================================
# Paired with the week endpoints above. Same mutation logic, but the response
# renders partials/inbox_main.html instead of partials/week_main.html.


@router.post("/w/{workspace_slug}/inbox/tasks", response_class=HTMLResponse)
def inbox_create_task(
    request: Request,
    workspace_slug: str,
    capture_text: str = Form(""),
    destination: str = Form("inbox"),  # accepted for parity; inbox always uses inbox
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Capture a task into the workspace inbox. Empty input is a silent no-op."""
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail=f"workspace '{workspace_slug}' not found")

    parsed = parse_capture(capture_text)
    if parsed.title.strip():
        position = _next_position(session, workspace.id, None, None)
        task = Task(
            workspace_id=workspace.id,
            title=parsed.title,
            project=parsed.project,
            estimate_hours=parsed.estimate_hours,
            position=position,
            iso_year=None,
            iso_week=None,
            created_at=_utcnow(),
        )
        session.add(task)
        session.flush()
        assert task.id is not None
        for tag in _ensure_tags(session, workspace.id, parsed.tags):
            assert tag.id is not None
            session.add(TaskTag(task_id=task.id, tag_id=tag.id))
        session.commit()

    return _render_inbox_partial(request, session, workspace_slug)


@router.post(
    "/w/{workspace_slug}/inbox/tasks/{task_id}/complete",
    response_class=HTMLResponse,
)
def inbox_toggle_complete(
    request: Request,
    workspace_slug: str,
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
    return _render_inbox_partial(request, session, workspace_slug)


@router.post(
    "/w/{workspace_slug}/inbox/tasks/{task_id}/edit",
    response_class=HTMLResponse,
)
def inbox_edit_task(
    request: Request,
    workspace_slug: str,
    task_id: int,
    title: str = Form(""),
    tags: str = Form(""),
    project: str = Form(""),
    estimate: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Same edit logic as the week endpoint; renders the inbox partial."""
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)

    title_clean = title.strip()
    if not title_clean:
        return _render_inbox_partial(request, session, workspace_slug)

    task.title = title_clean
    task.project = project.strip() or None
    task.estimate_hours = _parse_estimate_text(estimate)

    new_names: list[str] = []
    for raw in tags.split():
        name = raw.strip().lstrip("#").lower()
        if not name:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
            continue
        if name not in new_names:
            new_names.append(name)

    session.exec(delete(TaskTag).where(TaskTag.task_id == task.id))  # type: ignore[arg-type]
    for tag in _ensure_tags(session, workspace.id, new_names):
        assert tag.id is not None
        session.add(TaskTag(task_id=task.id, tag_id=tag.id))

    session.add(task)
    session.commit()
    return _render_inbox_partial(request, session, workspace_slug)


@router.post(
    "/w/{workspace_slug}/inbox/tasks/{task_id}/delete",
    response_class=HTMLResponse,
)
def inbox_delete_task(
    request: Request,
    workspace_slug: str,
    task_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)

    session.exec(delete(TaskTag).where(TaskTag.task_id == task.id))  # type: ignore[arg-type]
    session.delete(task)
    session.commit()
    return _render_inbox_partial(request, session, workspace_slug)


@router.post(
    "/w/{workspace_slug}/inbox/tasks/{task_id}/schedule",
    response_class=HTMLResponse,
)
def inbox_schedule_to_current_week(
    request: Request,
    workspace_slug: str,
    task_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Schedule an inbox task into the current ISO week (the user's local week).

    No-op if the task is already scheduled (defensive: shouldn't happen via UI
    since this endpoint is only reachable from the inbox row).
    """
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None or workspace.id is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    task = _get_task_for_workspace(session, task_id, workspace.id)

    if task.iso_year is None and task.iso_week is None:
        target_year, target_week = get_current_iso_week()
        task.iso_year = target_year
        task.iso_week = target_week
        task.position = _next_position(session, workspace.id, target_year, target_week)
        session.add(task)
        session.commit()

    return _render_inbox_partial(request, session, workspace_slug)
