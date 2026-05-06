"""Command-line interface for Kairo Web.

Subcommands:
  init           Seed workspaces and the owner user.
  migrate-v1     Import tasks from Kairo v1's SQLite database.
  rollover       Manually trigger Sunday-night rollover for all workspaces.

Run `kairo-web --help` to see usage.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from sqlmodel import Session, select

from kairo_web.config import get_settings
from kairo_web.db import engine
from kairo_web.models import Tag, Task, TaskTag, User, Workspace, utcnow

# Default workspace seeds — slug, display name, accent color (hex).
DEFAULT_WORKSPACES = [
    ("fulltime", "Full-time", "#0f766e"),
    ("consulting", "Consulting", "#7c3aed"),
    ("personal", "Personal", "#db2777"),
]


@click.group()
@click.version_option()
def cli() -> None:
    """Kairo Web management CLI."""


# ----- init ---------------------------------------------------------------


@cli.command()
def init() -> None:
    """Seed the three default workspaces and the owner user.

    Idempotent: existing rows are left untouched.
    """
    settings = get_settings()
    with Session(engine) as session:
        for slug, name, color in DEFAULT_WORKSPACES:
            existing = session.exec(select(Workspace).where(Workspace.slug == slug)).first()
            if existing:
                click.echo(f"workspace '{slug}' already exists — skipping")
                continue
            session.add(Workspace(slug=slug, name=name, color=color))
            click.echo(f"created workspace '{slug}' ({name})")

        owner = session.exec(select(User).where(User.email == settings.KAIRO_OWNER_EMAIL)).first()
        if owner:
            click.echo(f"owner user '{settings.KAIRO_OWNER_EMAIL}' already exists — skipping")
        else:
            session.add(User(email=settings.KAIRO_OWNER_EMAIL))
            click.echo(f"created owner user '{settings.KAIRO_OWNER_EMAIL}'")

        session.commit()
    click.echo("init complete.")


# ----- migrate-v1 ---------------------------------------------------------


@cli.command("migrate-v1")
@click.option(
    "--source",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path.home() / ".kairo" / "tasks.db",
    show_default=True,
    help="Path to Kairo v1's SQLite database.",
)
@click.option(
    "--workspace",
    "workspace_slug",
    type=click.Choice([w[0] for w in DEFAULT_WORKSPACES]),
    required=True,
    help="Target workspace for the imported tasks.",
)
@click.option("--dry-run", is_flag=True, help="Print a summary without writing anything.")
def migrate_v1(source: Path, workspace_slug: str, dry_run: bool) -> None:
    """Import tasks from Kairo v1 into the chosen Kairo Web workspace.

    v1 schema (verified against the v1 repo's src/kairo/database.py):
      tasks(id, title, description, status, week, year, created_at, completed_at,
            estimate INTEGER, project, position INTEGER DEFAULT 0)
      tags(id, name UNIQUE)
      task_tags(task_id, tag_id) — junction table
    """
    from datetime import datetime

    if not source.exists():
        raise click.ClickException(f"source DB not found: {source}")

    src = sqlite3.connect(source)
    src.row_factory = sqlite3.Row

    # Inspect the v1 schema defensively — older versions may lack columns.
    cols = {row["name"] for row in src.execute("PRAGMA table_info(tasks)")}
    has_project = "project" in cols
    has_estimate = "estimate" in cols
    has_position = "position" in cols
    has_completed_at = "completed_at" in cols
    # Tags live in a separate junction table in v1 (NOT a comma-string column).
    has_tag_join = bool(
        list(src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_tags'"))
    )

    rows = list(src.execute("SELECT * FROM tasks ORDER BY id"))
    click.echo(f"found {len(rows)} task(s) in {source}")

    # Pre-load tag names per task in one query (avoids N+1).
    tags_per_task: dict[int, list[str]] = {}
    if has_tag_join:
        for r in src.execute(
            """
            SELECT task_tags.task_id AS task_id, tags.name AS name
            FROM task_tags
            JOIN tags ON tags.id = task_tags.tag_id
            ORDER BY tags.name
            """
        ):
            tags_per_task.setdefault(r["task_id"], []).append(r["name"].lower())

    if dry_run:
        for r in rows[:5]:
            t_names = tags_per_task.get(r["id"], [])
            click.echo(
                f"  [{r['id']}] {r['title'][:60]}  "
                f"week={r['week']}/{r['year']}  "
                f"status={r['status']}  "
                f"tags={t_names}  "
                f"est={r['estimate'] if has_estimate else None}h  "
                f"proj={r['project'] if has_project else None}"
            )
        if len(rows) > 5:
            click.echo(f"  … and {len(rows) - 5} more")
        click.echo("(dry-run) no changes written")
        return

    with Session(engine) as session:
        ws = session.exec(select(Workspace).where(Workspace.slug == workspace_slug)).first()
        if not ws:
            raise click.ClickException(
                f"workspace '{workspace_slug}' not found — run `kairo-web init` first"
            )
        assert ws.id is not None

        # Cache tag-name → Tag for the target workspace (avoids re-querying).
        tag_cache: dict[str, Tag] = {
            t.name: t
            for t in session.exec(select(Tag).where(Tag.workspace_id == ws.id)).all()
        }

        imported = 0
        for r in rows:
            iso_year = r["year"] if r["year"] else None
            iso_week = r["week"] if r["week"] else None
            # v1 represents inbox as both NULL — preserve.
            if iso_year is None or iso_week is None:
                iso_year, iso_week = None, None

            # v1 estimate is INTEGER hours; v2 is FLOAT hours.
            est_raw = r["estimate"] if has_estimate else None
            estimate_hours = float(est_raw) if est_raw is not None else None

            # Preserve original timestamps where present.
            try:
                created_at = datetime.fromisoformat(r["created_at"])
            except (ValueError, TypeError):
                created_at = utcnow()

            completed_at = None
            if has_completed_at and r["completed_at"]:
                try:
                    completed_at = datetime.fromisoformat(r["completed_at"])
                except ValueError:
                    pass

            task = Task(
                workspace_id=ws.id,
                title=r["title"],
                description=r["description"] or None,
                project=r["project"] if has_project else None,
                estimate_hours=estimate_hours,
                status=r["status"] or "open",
                position=r["position"] if has_position and r["position"] is not None else 0,
                iso_year=iso_year,
                iso_week=iso_week,
                created_at=created_at,
                completed_at=completed_at,
            )
            session.add(task)
            session.flush()  # need task.id for the link table
            assert task.id is not None

            for tag_name in tags_per_task.get(r["id"], []):
                tag = tag_cache.get(tag_name)
                if not tag:
                    tag = Tag(workspace_id=ws.id, name=tag_name)
                    session.add(tag)
                    session.flush()
                    tag_cache[tag_name] = tag
                assert tag.id is not None
                session.add(TaskTag(task_id=task.id, tag_id=tag.id))

            imported += 1

        session.commit()
        click.echo(f"imported {imported} task(s) into workspace '{workspace_slug}'.")


# ----- rollover -----------------------------------------------------------


@cli.command()
def rollover() -> None:
    """Manually trigger rollover for all workspaces (full impl in milestone 4)."""
    click.echo("rollover: not yet implemented (milestone 4).")


if __name__ == "__main__":
    cli()
