"""Shared context-builder for the week + inbox pages and their mutation partials.

`routes/pages.py` and `routes/tasks.py` both need identical context dicts —
different entry points, same view. Centralizing keeps them in lockstep.

Public API:
  - build_week_context(...) → dict for week.html / partials/week_main.html
  - build_inbox_context(...) → dict for inbox.html / partials/inbox_main.html
  - task_to_dict(Task) → row shape used by the template
  - workspace_dict(slug, name, color, badge=0) → switcher row shape
  - week_url(slug, year, week, filter_qs="") → /w/<slug>/week/<YYYY>-W<WW>[?<qs>]
  - inbox_url(slug, filter_qs="") → /w/<slug>/inbox[?<qs>]
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlmodel import Session

from kairo_web.models import Task
from kairo_web.request_filters import filter_query_string
from kairo_web.services import queries
from kairo_web.services.queries import INBOX_SORT_KEYS, INBOX_SORT_LABELS
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


def inbox_url(slug: str, filter_qs: str = "") -> str:
    base = f"/w/{slug}/inbox"
    return f"{base}?{filter_qs}" if filter_qs else base


def _inbox_qs(filter_tag: Optional[str], filter_project: Optional[str], sort: Optional[str]) -> str:
    """Build a querystring fragment for the inbox page. Sort is omitted when
    it's the default ('newest') so /w/<slug>/inbox stays the canonical URL."""
    pairs: list[tuple[str, str]] = []
    if filter_tag:
        pairs.append(("tag", filter_tag))
    if filter_project:
        pairs.append(("project", filter_project))
    if sort and sort != "newest":
        pairs.append(("sort", sort))
    return urlencode(pairs) if pairs else ""


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
    """Shape a Task model for the template.

    `tag_names_str` is the space-joined tag names, used to pre-fill the inline
    edit form's tags input.
    """
    tag_names = [t.name for t in task.tags]
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "is_today": bool(task.is_today),
        "project": task.project,
        "estimate_hours": task.estimate_hours,
        "estimate_label": format_hours(task.estimate_hours),
        "tags": [{"name": n, "color": tag_color_for(n)} for n in tag_names],
        "tag_names_str": " ".join(tag_names),
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

    inbox_count = queries.count_inbox_tasks(session, workspace.id)

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
        "inbox_count": inbox_count,
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
        # Tab navigation (consumed by partials/_topbar.html).
        "active_tab": "week",
        "inbox_url": inbox_url(workspace.slug),
        "week_url_for_tab": week_url(workspace.slug, today_year, today_week),
        # Capture-bar config.
        "capture_action_url": f"/w/{workspace.slug}/week/{iso_year}-W{iso_week:02d}/tasks",
        "primary_destination": "week",  # Enter on the week page schedules into the viewed week.
        "main_target_id": "week-main",
        "capture_placeholder": "Capture — Enter adds to this week · supports #tag @project ~Nh",
    }


# ----- Inbox context -------------------------------------------------------


def build_inbox_context(
    session: Session,
    workspace_slug: str,
    *,
    filter_tag: Optional[str] = None,
    filter_project: Optional[str] = None,
    sort: str = "newest",
) -> dict:
    """Single source of truth for the inbox-view context.

    Mirrors `build_week_context` shape where it makes sense (same workspace
    switcher, same filter chip mechanics). Adds a `sort` selector that's
    inbox-specific.
    """
    if sort not in INBOX_SORT_KEYS:
        sort = "newest"

    workspace = queries.get_workspace(session, workspace_slug)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"workspace '{workspace_slug}' not found")
    assert workspace.id is not None

    inbox_total = queries.count_inbox_tasks(session, workspace.id)
    inbox_tasks = queries.get_inbox_tasks(
        session,
        workspace.id,
        filter_tag=filter_tag,
        filter_project=filter_project,
        sort=sort,
    )
    inbox_dicts = [task_to_dict(t) for t in inbox_tasks]

    all_workspaces = queries.list_workspaces(session)
    today_year, today_week = get_current_iso_week()

    open_count = sum(1 for t in inbox_dicts if t["status"] == "open")
    done_count = sum(1 for t in inbox_dicts if t["status"] == "completed")

    available_tags = queries.list_tag_names(session, workspace.id)
    available_projects = queries.list_project_names(session, workspace.id)

    qs = _inbox_qs(filter_tag, filter_project, sort)

    tag_options = [
        {
            "name": t,
            "url": inbox_url(workspace.slug, _inbox_qs(t, filter_project, sort)),
            "is_active": t == filter_tag,
        }
        for t in available_tags
    ]
    project_options = [
        {
            "name": p,
            "url": inbox_url(workspace.slug, _inbox_qs(filter_tag, p, sort)),
            "is_active": p == filter_project,
        }
        for p in available_projects
    ]
    sort_options = [
        {
            "key": k,
            "label": INBOX_SORT_LABELS[k],
            "url": inbox_url(workspace.slug, _inbox_qs(filter_tag, filter_project, k)),
            "is_active": k == sort,
        }
        for k in INBOX_SORT_KEYS
    ]

    return {
        "workspace": workspace_dict(workspace.slug, workspace.name, workspace.color),
        # On inbox, the workspace switcher's badge can show inbox count per ws.
        # We compute that on demand to keep the same dict shape.
        "workspaces": [
            workspace_dict(
                w.slug, w.name, w.color,
                queries.count_inbox_tasks(session, w.id) if w.id is not None else 0,
            )
            for w in all_workspaces
        ],
        "inbox_tasks": inbox_dicts,
        "inbox_total": inbox_total,
        "inbox_count": inbox_total,  # for the active workspace's tab badge
        "stats": {
            "open": open_count,
            "done": done_count,
            "total": inbox_total,
        },
        # Filter state (parallels week context).
        "filter_tag": filter_tag,
        "filter_project": filter_project,
        "filter_active": bool(filter_tag or filter_project),
        "filter_qs": qs,
        "available_tags": available_tags,
        "available_projects": available_projects,
        "tag_options": tag_options,
        "project_options": project_options,
        "tag_remove_url": inbox_url(workspace.slug, _inbox_qs(None, filter_project, sort)),
        "project_remove_url": inbox_url(workspace.slug, _inbox_qs(filter_tag, None, sort)),
        "clear_all_filters_url": inbox_url(workspace.slug, _inbox_qs(None, None, sort)),
        # Sort state.
        "sort": sort,
        "sort_label": INBOX_SORT_LABELS[sort],
        "sort_options": sort_options,
        # Tab navigation.
        "active_tab": "inbox",
        "inbox_url": inbox_url(workspace.slug),
        "week_url_for_tab": week_url(workspace.slug, today_year, today_week),
        # Capture-bar config.
        "capture_action_url": f"/w/{workspace.slug}/inbox/tasks",
        "primary_destination": "inbox",  # Enter on the inbox page captures to inbox.
        "main_target_id": "inbox-main",
        "capture_placeholder": "Capture — Enter adds to inbox · supports #tag @project ~Nh",
    }
