"""Populate the dev DB with a few sample tasks. Run after `kairo-web init`."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from kairo_web.db import engine
from kairo_web.models import Tag, Task, TaskTag, Workspace, utcnow


def main() -> None:
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()

    # Each entry: (title, tags, estimate_hours, is_today, project, status)
    plan: dict[str, list[tuple]] = {
        "fulltime": [
            ("Review PR #2143 for auth-rewrite", ["urgent"], 0.75, True, "auth-rewrite", "open"),
            ("1:1 with manager", [], 0.5, False, None, "completed"),
            ("Ship dashboard v2 to staging", ["shipping"], 1.5, True, None, "open"),
            ("Write design doc for migration plan", ["writing"], 2.0, False, "migration", "open"),
            ("Reply to grant proposal email", ["admin"], 0.5, False, None, "open"),
            ("Sprint planning prep", ["planning"], 1.0, False, "q2-roadmap", "open"),
            ("Onboard new contractor", [], 1.5, False, None, "completed"),
        ],
        "consulting": [
            ("Send draft proposal to Acme", ["urgent"], 1.0, True, "acme", "open"),
            ("Review client feedback on dashboard", [], 0.5, False, "beacon", "open"),
            ("Invoice Q1 work for Sigma", ["admin"], 0.25, False, "sigma", "open"),
        ],
        "personal": [
            ("Pay credit card", ["bills"], 0.25, True, None, "open"),
            ("Pick up dry cleaning", [], 0.25, False, None, "completed"),
            ("Call mom", ["family"], 0.5, False, None, "open"),
            ("Plan weekend trip", ["family"], None, False, "trip", "open"),
            ("Renew car insurance", ["admin"], 0.5, False, None, "open"),
        ],
    }
    inbox: dict[str, list[str]] = {
        "fulltime": [
            "Look into Postgres replication options",
            "Schedule team retro",
        ],
        "consulting": [
            "Follow up with Sigma re: scope",
        ],
        "personal": [
            "Read 'Designing Data-Intensive Applications'",
            "Order new running shoes",
        ],
    }

    with Session(engine) as session:
        for slug, samples in plan.items():
            ws = session.exec(select(Workspace).where(Workspace.slug == slug)).first()
            if not ws or ws.id is None:
                print(f"workspace '{slug}' missing — run `kairo-web init` first")
                continue
            for i, (title, tag_names, estimate, is_today, project, status) in enumerate(samples):
                task = Task(
                    workspace_id=ws.id,
                    title=title,
                    estimate_hours=estimate,
                    position=i,
                    iso_year=iso_year,
                    iso_week=iso_week,
                    is_today=is_today,
                    project=project,
                    status=status,
                    created_at=utcnow(),
                    completed_at=utcnow() if status == "completed" else None,
                )
                session.add(task)
                session.flush()
                for tname in tag_names:
                    tag = session.exec(
                        select(Tag).where(Tag.workspace_id == ws.id, Tag.name == tname)
                    ).first()
                    if not tag:
                        tag = Tag(workspace_id=ws.id, name=tname)
                        session.add(tag)
                        session.flush()
                    assert tag.id is not None
                    session.add(TaskTag(task_id=task.id, tag_id=tag.id))
            for j, title in enumerate(inbox.get(slug, [])):
                session.add(
                    Task(
                        workspace_id=ws.id,
                        title=title,
                        position=j,
                        iso_year=None,
                        iso_week=None,
                        created_at=utcnow(),
                    )
                )
        session.commit()
    print(f"seeded dev tasks for ISO week {iso_year}-W{iso_week:02d}.")


if __name__ == "__main__":
    main()
