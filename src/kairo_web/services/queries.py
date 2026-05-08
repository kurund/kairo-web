"""Database query helpers used by the week-view route.

Kept as small, focused functions over the SQLModel session — easier to test
and easier to swap for real ORM queries with eager loads later.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func
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
    *,
    filter_tag: Optional[str] = None,
    filter_project: Optional[str] = None,
) -> list[Task]:
    """Return tasks for the given week, ordered by completion then position.

    Optional `filter_tag` restricts to tasks linked to that tag in this workspace.
    Optional `filter_project` restricts to tasks where Task.project matches exactly.
    Both filters AND together when both are set.
    """
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

    if filter_project:
        stmt = stmt.where(Task.project == filter_project)

    if filter_tag:
        # Subquery: ids of tasks in this workspace that have the named tag.
        tag_subq = (
            select(TaskTag.task_id)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(Tag.workspace_id == workspace_id, Tag.name == filter_tag)
        )
        stmt = stmt.where(Task.id.in_(tag_subq))  # type: ignore[attr-defined]

    return list(session.exec(stmt).all())


def list_tag_names(session: Session, workspace_id: int) -> list[str]:
    """All tag names defined in a workspace, alphabetically. Used by the filter dropdown."""
    return list(
        session.exec(
            select(Tag.name).where(Tag.workspace_id == workspace_id).order_by(Tag.name)
        ).all()
    )


def list_project_names(session: Session, workspace_id: int) -> list[str]:
    """All distinct, non-null project names used in a workspace, alphabetically."""
    rows = session.exec(
        select(Task.project)
        .where(Task.workspace_id == workspace_id, Task.project.is_not(None))  # type: ignore[union-attr]
        .distinct()
        .order_by(Task.project)
    ).all()
    return [p for p in rows if p]


def get_inbox_tasks(
    session: Session,
    workspace_id: int,
    *,
    filter_tag: Optional[str] = None,
    filter_project: Optional[str] = None,
    sort: str = "newest",
) -> list[Task]:
    """Return inbox tasks (week IS NULL).

    Default ordering puts incomplete first (status DESC: 'open' > 'completed'),
    then applies the chosen `sort`:

      - "newest" (default): newest captures at top
      - "oldest":           oldest first (surface neglected items)
      - "project":          project ASC, then title
      - "title":            title ASC
    """
    stmt = (
        select(Task)
        .where(
            Task.workspace_id == workspace_id,
            Task.iso_year.is_(None),
            Task.iso_week.is_(None),
        )
        .options(selectinload(Task.tags))
    )

    if filter_project:
        stmt = stmt.where(Task.project == filter_project)
    if filter_tag:
        tag_subq = (
            select(TaskTag.task_id)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(Tag.workspace_id == workspace_id, Tag.name == filter_tag)
        )
        stmt = stmt.where(Task.id.in_(tag_subq))  # type: ignore[attr-defined]

    # Always: open tasks above completed.
    stmt = stmt.order_by(Task.status.desc())

    if sort == "oldest":
        stmt = stmt.order_by(Task.created_at.asc(), Task.id.asc())
    elif sort == "project":
        # COALESCE pushes null-project rows to the bottom so the named projects
        # group together at the top. SQLite has no native NULLS LAST.
        stmt = stmt.order_by(
            func.coalesce(Task.project, "￿").asc(),
            func.lower(Task.title).asc(),
        )
    elif sort == "title":
        stmt = stmt.order_by(func.lower(Task.title).asc())
    else:  # "newest" (default)
        stmt = stmt.order_by(Task.created_at.desc(), Task.id.desc())

    return list(session.exec(stmt).all())


# Sort keys allowed in URLs. Anything else falls back to 'newest'.
INBOX_SORT_KEYS: tuple[str, ...] = ("newest", "oldest", "project", "title")
INBOX_SORT_LABELS: dict[str, str] = {
    "newest": "Newest first",
    "oldest": "Oldest first",
    "project": "By project",
    "title": "Title (A–Z)",
}


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


def count_inbox_tasks(session: Session, workspace_id: int) -> int:
    """Total inbox count (unfiltered, all statuses) — drives the 'Inbox · N' tab badge."""
    return len(
        list(
            session.exec(
                select(Task.id).where(
                    Task.workspace_id == workspace_id,
                    Task.iso_year.is_(None),
                    Task.iso_week.is_(None),
                )
            ).all()
        )
    )
