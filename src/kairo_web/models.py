"""SQLModel data models for Kairo Web.

Schema mirrors TECH_SPEC.md §3. SQLModel sits on SQLAlchemy 2.x; metadata is shared
with Alembic via `SQLModel.metadata`.

NOTE: Do NOT add `from __future__ import annotations` here. SQLAlchemy 2.x
relationship resolution needs the type hints evaluated at class-creation time;
PEP 563 string-evaluation breaks `list["Task"]` Relationship targets.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    """Timezone-aware UTC now (avoids the deprecated naive `datetime.utcnow()`)."""
    return datetime.now(timezone.utc)


# ----- Link tables ---------------------------------------------------------


class TaskTag(SQLModel, table=True):
    """Many-to-many link between tasks and tags."""

    __tablename__ = "task_tag"

    task_id: int = Field(foreign_key="task.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


# ----- Core entities -------------------------------------------------------


class Workspace(SQLModel, table=True):
    """Top-level container — a fully isolated namespace for tasks/tags/projects.

    `kairo-web init` seeds a single 'personal' workspace; users add more via
    `kairo-web add-workspace`. Each workspace's accent color is stored here
    (the badge bg + text colors are derived from it via HSL math at render time).
    """

    __tablename__ = "workspace"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)  # 'fulltime' | 'consulting' | 'personal'
    name: str
    color: str  # hex, used in UI accents

    morning_digest_enabled: bool = Field(default=True)
    morning_digest_time: str = Field(default="07:00")  # HH:MM, local
    evening_digest_enabled: bool = Field(default=True)
    evening_digest_time: str = Field(default="18:00")

    created_at: datetime = Field(default_factory=utcnow)

    tasks: List["Task"] = Relationship(back_populates="workspace")
    tags: List["Tag"] = Relationship(back_populates="workspace")


class Task(SQLModel, table=True):
    """A single task. Belongs to one workspace; lives in a week or in the inbox."""

    __tablename__ = "task"
    __table_args__ = (
        CheckConstraint(
            "(iso_year IS NULL AND iso_week IS NULL) OR "
            "(iso_year IS NOT NULL AND iso_week IS NOT NULL)",
            name="inbox_or_scheduled",
        ),
        Index("idx_task_ws_week", "workspace_id", "iso_year", "iso_week", "position"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)

    title: str
    description: Optional[str] = None
    project: Optional[str] = None
    estimate_hours: Optional[float] = None

    status: str = Field(default="open")  # 'open' | 'completed'
    position: int  # per (workspace_id, iso_year, iso_week)
    is_today: bool = Field(default=False)

    iso_year: Optional[int] = None  # NULL together with iso_week ⇒ inbox
    iso_week: Optional[int] = None

    created_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None

    workspace: Optional["Workspace"] = Relationship(back_populates="tasks")
    tags: List["Tag"] = Relationship(back_populates="tasks", link_model=TaskTag)


class Tag(SQLModel, table=True):
    """A user-defined label, scoped per workspace (Personal `urgent` ≠ Work `urgent`)."""

    __tablename__ = "tag"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tag_ws_name"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id")
    name: str

    workspace: Optional["Workspace"] = Relationship(back_populates="tags")
    tasks: List["Task"] = Relationship(back_populates="tags", link_model=TaskTag)


# ----- Auth / session ------------------------------------------------------


class User(SQLModel, table=True):
    """Single-user app: only one row in practice."""

    __tablename__ = "user"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class LoginToken(SQLModel, table=True):
    """Magic-link token. Single-use, signed, short-lived."""

    __tablename__ = "login_token"

    token: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    expires_at: datetime
    used_at: Optional[datetime] = None


class Session(SQLModel, table=True):
    """Server-side session, keyed by random ID stored in an HttpOnly cookie."""

    __tablename__ = "session"

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    active_workspace_id: Optional[int] = Field(default=None, foreign_key="workspace.id")
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)


class DigestActionToken(SQLModel, table=True):
    """One-click action token for evening-digest links (e.g. 'roll to tomorrow')."""

    __tablename__ = "digest_action_token"

    token: str = Field(primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id")
    action: str  # 'roll_to_tomorrow' | 'roll_to_next_week' | 'noop'
    expires_at: datetime
    used_at: Optional[datetime] = None
