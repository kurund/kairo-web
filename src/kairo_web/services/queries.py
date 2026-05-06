"""Database query helpers used by the week-view route.

Kept as small, focused functions over the SQLModel session — easier to test
and easier to swap for real ORM queries with eager loads later.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from kairo_web.models import Tag, Task, TaskTag, Workspace


def get_workspace(session: Session, slug: str) -> Optional[Workspace]:
    return session.exec(select(Workspace).where(Workspace.slug == slug)).first()


def list_workspaces(session: Session) -> list[Workspace]:
    return list(session.exec(select(Workspace).order_by(Workspace.id)).all())


def get_week_tasks(
    session: Session,
    workspace_id: int,
    iso_year: int,
    iso_week: int,
) -> list[Task]:
    """Return tasks for the given week, ordered by completion then position."""
    stmt = (
        select(Task)
        .where(
            Task.workspace_id == workspace_id,
            Task.iso_year == iso_year,
            Task.iso_week == iso_week,
        )
        .options(selectinload(Task.tags))
        .order_by(Task.status.desc(), Task.position.asc(), Task.created_at.asc())
    )
    return list(session.exec(stmt).all())


def get_inbox_tasks(session: Session, workspace_id: int) -> list[Task]:
    """Return inbox tasks (week IS NULL)."""
    stmt = (
        select(Task)
        .where(
            Task.workspace_id == workspace_id,
            Task.iso_year.is_(None),
            Task.iso_week.is_(None),
        )
        .options(selectinload(Task.tags))
        .order_by(Task.status.desc(), Task.position.asc(), Task.created_at.asc())
    )
    return list(session.exec(stmt).all())


def get_workspace_badges(
    session: Session,
    iso_year: int,
    iso_week: int,
) -> dict[int, int]:
    """Open-task count per workspace for the given week. Used in the switcher badges."""
    stmt = (
        select(Task.workspace_id, Task.id)
        .where(
            Task.iso_year == iso_year,
            Task.iso_week == iso_week,
            Task.status == "open",
        )
    )
    counts: dict[int, int] = {}
    for ws_id, _ in session.exec(stmt).all():
        counts[ws_id] = counts.get(ws_id, 0) + 1
    return counts
