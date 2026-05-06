"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("morning_digest_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("morning_digest_time", sa.String(), nullable=False, server_default="07:00"),
        sa.Column("evening_digest_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("evening_digest_time", sa.String(), nullable=False, server_default="18:00"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_workspace_slug"),
    )
    op.create_index("ix_workspace_slug", "workspace", ["slug"], unique=True)

    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email", name="uq_user_email"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    op.create_table(
        "login_token",
        sa.Column("token", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "session",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column(
            "active_workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspace.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_tag_ws_name"),
    )

    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("project", sa.String(), nullable=True),
        sa.Column("estimate_hours", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_today", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("iso_year", sa.Integer(), nullable=True),
        sa.Column("iso_week", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(iso_year IS NULL AND iso_week IS NULL) OR "
            "(iso_year IS NOT NULL AND iso_week IS NOT NULL)",
            name="inbox_or_scheduled",
        ),
    )
    op.create_index("ix_task_workspace_id", "task", ["workspace_id"])
    op.create_index(
        "idx_task_ws_week",
        "task",
        ["workspace_id", "iso_year", "iso_week", "position"],
    )

    op.create_table(
        "task_tag",
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("task.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tag.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "digest_action_token",
        sa.Column("token", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("digest_action_token")
    op.drop_table("task_tag")
    op.drop_index("idx_task_ws_week", table_name="task")
    op.drop_index("ix_task_workspace_id", table_name="task")
    op.drop_table("task")
    op.drop_table("tag")
    op.drop_table("session")
    op.drop_table("login_token")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")
    op.drop_index("ix_workspace_slug", table_name="workspace")
    op.drop_table("workspace")
