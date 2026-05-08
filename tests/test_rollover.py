"""Tests for the auto-rollover service + manual rollover route."""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("KAIRO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("KAIRO_OWNER_EMAIL", "test@example.com")
if "KAIRO_DATABASE_URL" not in os.environ:
    _fd, _path = tempfile.mkstemp(suffix=".db")
    os.close(_fd)
    os.environ["KAIRO_DATABASE_URL"] = f"sqlite:///{_path}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from kairo_web.db import engine  # noqa: E402
from kairo_web.main import app  # noqa: E402
from kairo_web.models import Tag, Task, TaskTag, Workspace  # noqa: E402
from kairo_web.services.rollover import rollover_workspace  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Workspace(slug="personal", name="Personal", color="#BE185D", is_default=True))
        s.commit()
    yield


def _add_task(
    session: Session,
    title: str,
    *,
    iso_year: int = 2026,
    iso_week: int = 19,
    status: str = "open",
    is_today: bool = False,
    position: int = 1,
    project: str | None = None,
) -> Task:
    workspace = session.exec(select(Workspace).where(Workspace.slug == "personal")).first()
    t = Task(
        workspace_id=workspace.id,
        title=title,
        iso_year=iso_year,
        iso_week=iso_week,
        status=status,
        is_today=is_today,
        position=position,
        project=project,
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


# ----- rollover_workspace ----------------------------------------------------


def test_rollover_moves_open_tasks() -> None:
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        _add_task(s, "open task", position=1)
        moved = rollover_workspace(s, ws.id, 2026, 19, 2026, 20)
        assert moved == 1
        rolled = s.exec(select(Task).where(Task.title == "open task")).first()
        assert rolled.iso_year == 2026 and rolled.iso_week == 20


def test_rollover_skips_completed_tasks() -> None:
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        _add_task(s, "open one", position=1)
        _add_task(s, "done one", status="completed", position=2)
        moved = rollover_workspace(s, ws.id, 2026, 19, 2026, 20)
        assert moved == 1
        # Completed task stays in week 19.
        done = s.exec(select(Task).where(Task.title == "done one")).first()
        assert done.iso_year == 2026 and done.iso_week == 19


def test_rollover_clears_today_flag() -> None:
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        _add_task(s, "today task", is_today=True, position=1)
        rollover_workspace(s, ws.id, 2026, 19, 2026, 20)
        rolled = s.exec(select(Task).where(Task.title == "today task")).first()
        assert rolled.is_today is False


def test_rollover_appends_positions_to_destination() -> None:
    """Rolled tasks land at the end of the destination week's existing tasks."""
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        # Pre-existing task in destination week.
        _add_task(s, "already there", iso_year=2026, iso_week=20, position=7)
        # Two open tasks in source week, positions 1 and 2.
        _add_task(s, "src first", position=1)
        _add_task(s, "src second", position=2)

        rollover_workspace(s, ws.id, 2026, 19, 2026, 20)

        # All week-20 tasks ordered by position.
        wk20 = list(
            s.exec(
                select(Task)
                .where(Task.iso_year == 2026, Task.iso_week == 20)
                .order_by(Task.position)
            ).all()
        )
        titles = [t.title for t in wk20]
        assert titles == ["already there", "src first", "src second"]


def test_rollover_noop_when_no_open_tasks() -> None:
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        moved = rollover_workspace(s, ws.id, 2026, 19, 2026, 20)
        assert moved == 0


def test_rollover_year_boundary() -> None:
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        _add_task(s, "year-end", iso_year=2026, iso_week=53, position=1)
        moved = rollover_workspace(s, ws.id, 2026, 53, 2027, 1)
        assert moved == 1
        rolled = s.exec(select(Task).where(Task.title == "year-end")).first()
        assert rolled.iso_year == 2027 and rolled.iso_week == 1


def test_rollover_preserves_tags_project_estimate() -> None:
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        tag = Tag(workspace_id=ws.id, name="urgent")
        s.add(tag)
        s.commit()
        t = _add_task(s, "rich task", project="bills", position=1)
        t.estimate_hours = 1.5
        s.add(t)
        s.add(TaskTag(task_id=t.id, tag_id=tag.id))
        s.commit()

        rollover_workspace(s, ws.id, 2026, 19, 2026, 20)

        rolled = s.exec(select(Task).where(Task.title == "rich task")).first()
        assert rolled.project == "bills"
        assert rolled.estimate_hours == 1.5
        assert len([link for link in s.exec(select(TaskTag)).all()]) == 1


def test_rollover_inbox_not_affected() -> None:
    """Inbox tasks (iso_year/iso_week NULL) must not be touched."""
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        # Manually create an inbox task — the helper requires year/week.
        s.add(Task(workspace_id=ws.id, title="inbox", position=1))
        s.commit()

        rollover_workspace(s, ws.id, 2026, 19, 2026, 20)
        inbox = s.exec(select(Task).where(Task.title == "inbox")).first()
        assert inbox.iso_year is None and inbox.iso_week is None


def test_rollover_other_workspace_untouched() -> None:
    with Session(engine) as s:
        ws_personal = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        s.add(Workspace(slug="work", name="Work", color="#0F766E"))
        s.commit()
        ws_work = s.exec(select(Workspace).where(Workspace.slug == "work")).first()
        s.add(
            Task(workspace_id=ws_work.id, title="work task", iso_year=2026, iso_week=19, position=1)
        )
        _add_task(s, "personal task", position=1)
        s.commit()

        rollover_workspace(s, ws_personal.id, 2026, 19, 2026, 20)
        work_task = s.exec(select(Task).where(Task.title == "work task")).first()
        assert work_task.iso_year == 2026 and work_task.iso_week == 19


def test_rollover_same_week_is_noop() -> None:
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        _add_task(s, "x", position=1)
        moved = rollover_workspace(s, ws.id, 2026, 19, 2026, 19)
        assert moved == 0


# ----- Manual rollover route ------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_manual_rollover_route_moves_tasks(client: TestClient) -> None:
    with Session(engine) as s:
        _add_task(s, "rolled", position=1)
    r = client.post("/w/personal/week/2026-W19/rollover")
    assert r.status_code == 200
    # Response is the partial; the task should now be empty in week 19.
    assert "Nothing scheduled this week" in r.text or "rolled" not in r.text.split('id="week-main"')[1].split("This week")[1].split("Inbox")[0]
    with Session(engine) as s:
        rolled = s.exec(select(Task).where(Task.title == "rolled")).first()
        assert rolled.iso_week == 20


def test_manual_rollover_route_404_for_unknown_workspace(client: TestClient) -> None:
    r = client.post("/w/nope/week/2026-W19/rollover")
    assert r.status_code == 404


# ----- rollover_all_workspaces ----------------------------------------------


def test_rollover_all_workspaces_iterates() -> None:
    """rollover_all uses the *current* ISO week as the from-week. We seed a task
    in that week and verify it gets moved."""
    from kairo_web.services.rollover import rollover_all_workspaces
    from kairo_web.utils import get_current_iso_week

    cy, cw = get_current_iso_week()
    with Session(engine) as s:
        s.add(Workspace(slug="work", name="Work", color="#0F766E"))
        s.commit()
        # One open task in the current week, one in personal too.
        ws_personal = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        ws_work = s.exec(select(Workspace).where(Workspace.slug == "work")).first()
        s.add_all([
            Task(workspace_id=ws_personal.id, title="p task",
                 iso_year=cy, iso_week=cw, position=1),
            Task(workspace_id=ws_work.id, title="w task",
                 iso_year=cy, iso_week=cw, position=1),
        ])
        s.commit()

        summaries = rollover_all_workspaces(s)
        assert len(summaries) == 2
        assert sum(s.moved for s in summaries) == 2

        # Both tasks shifted forward one week.
        from kairo_web.utils import shift_iso_week
        ny, nw = shift_iso_week(cy, cw, +1)
        for title in ("p task", "w task"):
            t = s.exec(select(Task).where(Task.title == title)).first()
            assert t.iso_year == ny and t.iso_week == nw
