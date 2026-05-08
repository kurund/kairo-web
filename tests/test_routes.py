"""End-to-end tests for the live week view + HTMX mutation endpoints.

Uses an in-memory SQLite database with the schema set up via SQLModel.metadata
(skipping Alembic) so each test runs in isolation.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

# Configure env BEFORE the app is imported.
os.environ.setdefault("KAIRO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("KAIRO_OWNER_EMAIL", "test@example.com")

_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_TMP_DB_FD)
os.environ["KAIRO_DATABASE_URL"] = f"sqlite:///{_TMP_DB_PATH}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from kairo_web.db import engine  # noqa: E402
from kairo_web.main import app  # noqa: E402
from kairo_web.models import Tag, Task, TaskTag, Workspace  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db() -> Iterator[None]:
    """Drop + recreate all tables before each test."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Workspace(slug="fulltime", name="Full-time", color="#0F766E"))
        session.add(Workspace(slug="consulting", name="Consulting", color="#4338CA"))
        session.add(Workspace(slug="personal", name="Personal", color="#BE185D", is_default=True))
        session.commit()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _ws_id(slug: str) -> int:
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == slug)).first()
        assert ws and ws.id is not None
        return ws.id


# ----- Page route ---------------------------------------------------------


def test_root_redirects_to_current_week(client: TestClient) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("/w/personal/week/")


def test_week_page_renders(client: TestClient) -> None:
    r = client.get("/w/fulltime/week/2026-W19")
    assert r.status_code == 200
    assert "Full-time" in r.text
    assert "Week 19" in r.text


def test_unknown_workspace_404(client: TestClient) -> None:
    r = client.get("/w/nope/week/2026-W19")
    assert r.status_code == 404


def test_bad_week_400(client: TestClient) -> None:
    r = client.get("/w/fulltime/week/badweek")
    assert r.status_code == 400


# ----- Mutation endpoints --------------------------------------------------


def test_capture_defaults_to_inbox(client: TestClient) -> None:
    """No destination field → task lands in the workspace inbox (iso_year/week NULL)."""
    r = client.post(
        "/w/fulltime/week/2026-W19/tasks",
        data={"capture_text": "Fix login bug #urgent #auth @auth-rewrite ~2h"},
    )
    assert r.status_code == 200

    with Session(engine) as s:
        tasks = list(s.exec(select(Task).where(Task.workspace_id == _ws_id("fulltime"))).all())
        assert len(tasks) == 1
        t = tasks[0]
        assert t.title == "Fix login bug"
        assert t.project == "auth-rewrite"
        assert t.estimate_hours == 2.0
        assert t.iso_year is None and t.iso_week is None  # inbox
        # Tags + project + estimate still parsed correctly even for inbox tasks.
        links = list(s.exec(select(TaskTag).where(TaskTag.task_id == t.id)).all())
        assert len(links) == 2
        names = {s.exec(select(Tag).where(Tag.id == link.tag_id)).first().name for link in links}
        assert names == {"urgent", "auth"}


def test_capture_with_destination_week_schedules_into_viewed_week(client: TestClient) -> None:
    """destination=week (from the secondary 'This week' button) schedules directly."""
    r = client.post(
        "/w/fulltime/week/2026-W19/tasks",
        data={"capture_text": "Sprint planning prep ~1h", "destination": "week"},
    )
    assert r.status_code == 200
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.iso_year == 2026 and t.iso_week == 19
        assert t.estimate_hours == 1.0


def test_capture_with_explicit_destination_inbox(client: TestClient) -> None:
    """Submitting the primary '+ Inbox' button sends destination=inbox explicitly."""
    r = client.post(
        "/w/fulltime/week/2026-W19/tasks",
        data={"capture_text": "Some thought", "destination": "inbox"},
    )
    assert r.status_code == 200
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.iso_year is None and t.iso_week is None


def test_empty_capture_is_noop(client: TestClient) -> None:
    r = client.post("/w/fulltime/week/2026-W19/tasks", data={"capture_text": "   "})
    assert r.status_code == 200
    with Session(engine) as s:
        assert s.exec(select(Task)).all() == []


def test_complete_toggles_status(client: TestClient) -> None:
    client.post("/w/fulltime/week/2026-W19/tasks", data={"capture_text": "Test task"})
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id

    r1 = client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/complete")
    assert r1.status_code == 200
    with Session(engine) as s:
        assert s.exec(select(Task)).first().status == "completed"

    r2 = client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/complete")
    assert r2.status_code == 200
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.status == "open"
        assert t.completed_at is None


def test_today_toggles_flag(client: TestClient) -> None:
    client.post("/w/fulltime/week/2026-W19/tasks", data={"capture_text": "Test"})
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id
        assert s.exec(select(Task)).first().is_today is False

    client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/today")
    with Session(engine) as s:
        assert s.exec(select(Task)).first().is_today is True

    client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/today")
    with Session(engine) as s:
        assert s.exec(select(Task)).first().is_today is False


def test_schedule_round_trip(client: TestClient) -> None:
    """Inbox → week → inbox: position is reassigned, today flag cleared on inbox."""
    # Manually create an inbox task.
    with Session(engine) as s:
        s.add(Task(workspace_id=_ws_id("fulltime"), title="Inbox item", position=1))
        s.commit()
        tid = s.exec(select(Task)).first().id

    # Schedule into the week.
    r = client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/schedule")
    assert r.status_code == 200
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.iso_year == 2026 and t.iso_week == 19

    # Toggle back to inbox.
    client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/schedule")
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.iso_year is None and t.iso_week is None
        assert t.is_today is False


def test_week_table_renders_send_to_inbox_button(client: TestClient) -> None:
    """Each scheduled task row should expose a hover-only 'send to inbox' button."""
    client.post(
        "/w/fulltime/week/2026-W19/tasks",
        data={"capture_text": "Scheduled task", "destination": "week"},
    )
    r = client.get("/w/fulltime/week/2026-W19")
    assert r.status_code == 200
    assert "↩ inbox" in r.text
    # The button posts to the same /schedule endpoint that the inbox panel uses
    # for the inverse direction — the toggle is symmetric.
    assert 'aria-label="Move to inbox"' in r.text
    assert "/tasks/" in r.text and "/schedule" in r.text


def test_clearing_today_flag_when_moving_to_inbox(client: TestClient) -> None:
    """A task flagged today must lose that flag when moved back to inbox."""
    client.post(
        "/w/fulltime/week/2026-W19/tasks",
        data={"capture_text": "Test", "destination": "week"},
    )
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id
    client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/today")
    with Session(engine) as s:
        assert s.exec(select(Task)).first().is_today is True

    # Send to inbox.
    client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/schedule")
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.iso_year is None and t.iso_week is None
        assert t.is_today is False  # cleared on inbox-move


def test_delete_removes_task_and_links(client: TestClient) -> None:
    client.post(
        "/w/fulltime/week/2026-W19/tasks",
        data={"capture_text": "Bye #urgent"},
    )
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id

    r = client.post(f"/w/fulltime/week/2026-W19/tasks/{tid}/delete")
    assert r.status_code == 200
    with Session(engine) as s:
        assert s.exec(select(Task)).all() == []
        assert s.exec(select(TaskTag)).all() == []


def test_move_swaps_positions(client: TestClient) -> None:
    """Move only operates on tasks within the viewed week, so explicitly schedule both."""
    client.post(
        "/w/fulltime/week/2026-W19/tasks",
        data={"capture_text": "First", "destination": "week"},
    )
    client.post(
        "/w/fulltime/week/2026-W19/tasks",
        data={"capture_text": "Second", "destination": "week"},
    )
    with Session(engine) as s:
        tasks = list(s.exec(select(Task).order_by(Task.position.asc())).all())
        first_id, second_id = tasks[0].id, tasks[1].id

    # Move the second task up — should swap with first.
    r = client.post(
        f"/w/fulltime/week/2026-W19/tasks/{second_id}/move",
        data={"direction": "up"},
    )
    assert r.status_code == 200
    with Session(engine) as s:
        ordered = list(s.exec(select(Task).order_by(Task.position.asc())).all())
        assert ordered[0].id == second_id
        assert ordered[1].id == first_id


def test_workspace_isolation(client: TestClient) -> None:
    """A task created in 'fulltime' must not appear in 'personal'."""
    client.post("/w/fulltime/week/2026-W19/tasks", data={"capture_text": "Work thing"})
    r = client.get("/w/personal/week/2026-W19")
    assert r.status_code == 200
    assert "Work thing" not in r.text


def test_partial_response_does_not_include_full_html(client: TestClient) -> None:
    """Mutation endpoints return a partial fragment (no <html>, <head>)."""
    r = client.post("/w/fulltime/week/2026-W19/tasks", data={"capture_text": "Test"})
    assert "<html" not in r.text
    assert "<head>" not in r.text
    assert 'id="week-main"' in r.text
