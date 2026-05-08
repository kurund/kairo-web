"""Sunday-night rollover service.

Moves incomplete tasks from a closing week into the next week:

  - Status must be 'open' (completed tasks stay where they were finished)
  - `is_today` is cleared (a fresh week needs a fresh today commitment)
  - Position is reassigned (appended to the end of the destination week)
  - Tags + project + estimate + description are preserved
  - The task's id stays the same so links/bookmarks don't break

Two entry points:

  - `rollover_workspace(...)`: roll a single workspace's specific week. Used
    by both the auto-rollover scheduler (via `rollover_all_workspaces`) and
    the manual "Roll forward" button in the UI.
  - `rollover_all_workspaces(session)`: at run time, picks the current local
    ISO week as the closing week and rolls every workspace forward one week.
    Called from the APScheduler job and from `kairo-web rollover`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import Session, select

from kairo_web.models import Task, Workspace
from kairo_web.utils import get_current_iso_week, shift_iso_week


@dataclass
class RolloverSummary:
    workspace_slug: str
    from_year: int
    from_week: int
    to_year: int
    to_week: int
    moved: int


def rollover_workspace(
    session: Session,
    workspace_id: int,
    from_year: int,
    from_week: int,
    to_year: int,
    to_week: int,
) -> int:
    """Move open tasks from (from_year, from_week) → (to_year, to_week). Return count moved.

    Idempotent in the sense that re-running with no remaining open tasks is a no-op.
    """
    if (from_year, from_week) == (to_year, to_week):
        return 0

    open_tasks = list(
        session.exec(
            select(Task)
            .where(
                Task.workspace_id == workspace_id,
                Task.iso_year == from_year,
                Task.iso_week == from_week,
                Task.status == "open",
            )
            .order_by(Task.position.asc(), Task.created_at.asc())
        ).all()
    )

    if not open_tasks:
        return 0

    # Append to the end of the destination week.
    next_position = (
        session.exec(
            select(func.max(Task.position)).where(
                Task.workspace_id == workspace_id,
                Task.iso_year == to_year,
                Task.iso_week == to_week,
            )
        ).one_or_none()
        or 0
    ) + 1

    for t in open_tasks:
        t.iso_year = to_year
        t.iso_week = to_week
        t.is_today = False  # next week starts fresh
        t.position = next_position
        next_position += 1
        session.add(t)

    session.commit()
    return len(open_tasks)


def rollover_all_workspaces(session: Session) -> list[RolloverSummary]:
    """Roll every workspace's current ISO week forward by one. Returns per-workspace summaries.

    Intended for the Sunday-23:59 scheduled job and the `kairo-web rollover` CLI.
    """
    from_year, from_week = get_current_iso_week()
    to_year, to_week = shift_iso_week(from_year, from_week, +1)

    summaries: list[RolloverSummary] = []
    for ws in session.exec(select(Workspace).order_by(Workspace.id)).all():
        if ws.id is None:
            continue
        moved = rollover_workspace(session, ws.id, from_year, from_week, to_year, to_week)
        summaries.append(
            RolloverSummary(
                workspace_slug=ws.slug,
                from_year=from_year,
                from_week=from_week,
                to_year=to_year,
                to_week=to_week,
                moved=moved,
            )
        )
    return summaries
