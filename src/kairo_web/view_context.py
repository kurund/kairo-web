"""Shared context-builder for the week-view template + its mutation partial.

`routes/pages.py::get_week` and every endpoint in `routes/tasks.py` need the
exact same context dict — different entry points, identical view. Centralizing
it here keeps them in lockstep and removes ~150 lines of duplication.

Public API:
  - build_week_context(...) → dict for week.html / partials/week_main.html
  - task_to_dict(Task) → row shape used by the template
  - workspace_dict(slug, name, color, badge=0) → switcher row shape
  - week_url(slug, year, week, filter_qs="") → /w/<slug>/week/<YYYY>-W<WW>[?<qs>]
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session

from kairo_web.models import Task
from kairo_web.request_filters import filter_query_string
from kairo_web.services import queries
from kairo_web.utils import (
    format_hours,
    format_today_label,
    format_week_label,
    get_current_iso_week,
    shift_iso_week,
    tag_color_for,
)
from kairo_web.workspace_meta import derive_bg_fg


def week_url(slug: str, year: int, week: int, filter_qs: str = "") -> str:
    base = f"/w/{slug}/week/{year}-W{week:02d}"
    return f"{base}?{filter_qs}" if filter_qs else base


def workspace_dict(slug: str, name: str, color: str, badge_count: int = 0) -> dict:
    """Shape a workspace for the template. Bg+fg derived from `color` via HSL math."""
    bg, fg = derive_bg_fg(color)
    return {
        "slug": slug,
        "name": name,
        "color_hex": color,
        "color_bg": bg,
        "color_fg": fg,
        "badge_count": badge_count,
    }


def task_to_dict(task: Task) -> dict:
    """Shape a Task model for the template."""
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


def build_week_context(
    session: Session,
    workspace_slug: str,
    iso_year: int,
    iso_week: int,
    *,
    filter_tag: Optional[str] = None,
    filter_project: Optional[str] = None,
) -> dict:
    """Single source of truth for the week-view context.

    Stats reflect the unfiltered week. Today strip + week table reflect the
    filter. `week_total_count` is included so the template can show
    "showing N of M" when a filter is active.
    """
    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"workspace '{workspace_slug}' not found")
    assert workspace.id is not None

    # Two queries when a filter is on: one unfiltered for stats, one filtered for display.
    all_week_tasks = queries.get_week_tasks(session, workspace.id, iso_year, iso_week)
    if filter_tag or filter_project:
        filtered_week_tasks = queries.get_week_tasks(
            session,
            workspace.id,
            iso_year,
            iso_week,
            filter_tag=filter_tag,
            filter_project=filter_project,
        )
    else:
        filtered_week_tasks = all_week_tasks

    inbox_tasks = queries.get_inbox_tasks(session, workspace.id)
    badge_counts = queries.get_workspace_badges(session, iso_year, iso_week)
    all_workspaces = queries.list_workspaces(session)

    all_week_task_dicts = [task_to_dict(t) for t in all_week_tasks]
    filtered_dicts = [task_to_dict(t) for t in filtered_week_tasks]
    today_task_dicts = [t for t in filtered_dicts if t["is_today"]]

    open_count = sum(1 for t in all_week_task_dicts if t["status"] == "open")
    done_count = sum(1 for t in all_week_task_dicts if t["status"] == "completed")
    total = open_count + done_count
    estimated = round(
        sum((t["estimate_hours"] or 0) for t in all_week_task_dicts if t["status"] == "open"), 2
    )
    logged = round(
        sum((t["estimate_hours"] or 0) for t in all_week_task_dicts if t["status"] == "completed"),
        2,
    )
    percent = int(round(100 * done_count / total)) if total else 0

    prev_year, prev_week = shift_iso_week(iso_year, iso_week, -1)
    next_year, next_week = shift_iso_week(iso_year, iso_week, +1)
    today_year, today_week = get_current_iso_week()

    qs = filter_query_string(filter_tag, filter_project)
    available_tags = queries.list_tag_names(session, workspace.id)
    available_projects = queries.list_project_names(session, workspace.id)

    # Each option's URL: keep the *other* filter, replace this one.
    tag_options = [
        {
            "name": t,
            "url": week_url(workspace.slug, iso_year, iso_week, filter_query_string(t, filter_project)),
            "is_active": t == filter_tag,
        }
        for t in available_tags
    ]
    project_options = [
        {
            "name": p,
            "url": week_url(workspace.slug, iso_year, iso_week, filter_query_string(filter_tag, p)),
            "is_active": p == filter_project,
        }
        for p in available_projects
    ]

    return {
        "workspace": workspace_dict(workspace.slug, workspace.name, workspace.color),
        "workspaces": [
            workspace_dict(w.slug, w.name, w.color, badge_counts.get(w.id, 0))
            for w in all_workspaces
        ],
        "iso_year": iso_year,
        "iso_week": iso_week,
        "year_week": f"{iso_year}-W{iso_week:02d}",
        "week_label": format_week_label(iso_year, iso_week),
        "prev_week_url": week_url(workspace.slug, prev_year, prev_week, qs),
        "next_week_url": week_url(workspace.slug, next_year, next_week, qs),
        "today_url": week_url(workspace.slug, today_year, today_week, qs),
        "today_date_label": format_today_label(),
        "today_done_count": sum(1 for t in today_task_dicts if t["status"] == "completed"),
        "today_total_count": len(today_task_dicts),
        "today_tasks": today_task_dicts,
        "week_tasks": filtered_dicts,
        "week_total_count": len(all_week_task_dicts),
        "inbox_tasks": [{"id": t.id, "title": t.title} for t in inbox_tasks],
        "inbox_count": len(inbox_tasks),
        "stats": {
            "open": open_count,
            "done": done_count,
            "estimated_hours": estimated,
            "logged_hours": logged,
            "percent_complete": percent,
        },
        "filter_tag": filter_tag,
        "filter_project": filter_project,
        "filter_active": bool(filter_tag or filter_project),
        "filter_qs": qs,
        "available_tags": available_tags,
        "available_projects": available_projects,
        "tag_options": tag_options,
        "project_options": project_options,
        "tag_remove_url": week_url(
            workspace.slug, iso_year, iso_week, filter_query_string(None, filter_project)
        ),
        "project_remove_url": week_url(
            workspace.slug, iso_year, iso_week, filter_query_string(filter_tag, None)
        ),
        "clear_all_filters_url": week_url(workspace.slug, iso_year, iso_week),
    }
