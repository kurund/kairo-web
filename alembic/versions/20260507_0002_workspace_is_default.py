"""add workspace.is_default

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-07

Adds an `is_default` boolean column to the `workspace` table and backfills the
oldest workspace (lowest id) as the default. The root '/' redirect picks the
default workspace; an explicit per-row "Set as default" action in the UI
toggles which one wins.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401  (required: SQLModel column types in autogenerate output)
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    # Backfill: oldest workspace by id becomes the default. Safe even on an
    # empty table (UPDATE on no rows is a no-op).
    op.execute(
        "UPDATE workspace SET is_default = 1 "
        "WHERE id = (SELECT MIN(id) FROM workspace)"
    )


def downgrade() -> None:
    with op.batch_alter_table("workspace") as batch_op:
        batch_op.drop_column("is_default")
