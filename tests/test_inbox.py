"""Tests for the inbox page, its mutation endpoints, filter, and sort."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

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
from kairo_web.utils import get_current_iso_week  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Workspace(slug="personal", name="Personal", color="#BE185D", is_default=True))
        s.commit()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _ws_id() -> int:
    with Session(engine) as s:
        return s.exec(select(Workspace).where(Workspace.slug == "personal")).first().id


# ----- Page render --------------------------------------------------------


def test_inbox_page_renders(client: TestClient) -> None:
    r = client.get("/w/personal/inbox")
    assert r.status_code == 200
    assert "Inbox" in r.text
    # Active tab is inbox.
    assert 'aria-selected="true"' in r.text
    # Capture bar visible; no "This week" button on inbox page.
    assert "+ Inbox" in r.text
    assert "This week" not in r.text or r.text.count("This week") == 0


def test_inbox_page_404_for_unknown_workspace(client: TestClient) -> None:
    r = client.get("/w/nope/inbox")
    assert r.status_code == 404


def test_inbox_tab_links_from_week_page(client: TestClient) -> None:
    """The Week page topbar should contain a link to /w/<slug>/inbox."""
    r = client.get("/w/personal/week/2026-W19")
    assert r.status_code == 200
    assert 'href="/w/personal/inbox"' in r.text


def test_week_tab_links_from_inbox_page(client: TestClient) -> None:
    """The Inbox page should link to the current ISO week's view."""
    cy, cw = get_current_iso_week()
    r = client.get("/w/personal/inbox")
    assert r.status_code == 200
    assert f'href="/w/personal/week/{cy}-W{cw:02d}"' in r.text


def test_week_view_no_longer_renders_inbox_sidebar(client: TestClient) -> None:
    """The right-side inbox panel must be gone from the week view."""
    # Seed an inbox task; if the sidebar still existed it would show up.
    with Session(engine) as s:
        s.add(Task(workspace_id=_ws_id(), title="Should not appear", position=1))
        s.commit()
    r = client.get("/w/personal/week/2026-W19")
    assert r.status_code == 200
    # Inbox panel previously rendered "Click any inbox item to schedule it into this week"
    assert "Click any inbox item to schedule" not in r.text
    # The inbox task should NOT be in the response (it's only on /inbox now).
    assert "Should not appear" not in r.text


def test_inbox_count_appears_in_tab_badge(client: TestClient) -> None:
    """Tab badge should reflect the inbox open count."""
    with Session(engine) as s:
        for i in range(3):
            s.add(Task(workspace_id=_ws_id(), title=f"item{i}", position=i))
        s.commit()
    r = client.get("/w/personal/week/2026-W19")
    # Look for the badge "3" next to the Inbox tab.
    assert ">3<" in r.text


def test_inbox_tab_badge_excludes_completed(client: TestClient) -> None:
    """Tab badge counts open tasks only — completed inbox items don't bloat it."""
    with Session(engine) as s:
        s.add(Task(workspace_id=_ws_id(), title="open1", position=1))
        s.add(Task(workspace_id=_ws_id(), title="open2", position=2))
        s.add(Task(workspace_id=_ws_id(), title="done", position=3, status="completed"))
        s.commit()
    r = client.get("/w/personal/week/2026-W19")
    # 2 open inbox tasks → badge shows 2, not 3.
    assert ">2<" in r.text
    assert ">3<" not in r.text


def test_week_tab_badge_shows_open_count(client: TestClient) -> None:
    """Week tab gets a count of open tasks in the *current* ISO week."""
    cy, cw = get_current_iso_week()
    with Session(engine) as s:
        s.add(Task(workspace_id=_ws_id(), title="open1",
                   iso_year=cy, iso_week=cw, position=1))
        s.add(Task(workspace_id=_ws_id(), title="open2",
                   iso_year=cy, iso_week=cw, position=2))
        s.add(Task(workspace_id=_ws_id(), title="done",
                   iso_year=cy, iso_week=cw, position=3, status="completed"))
        s.commit()

    # On the inbox page, the Week tab still shows the badge.
    r_inbox = client.get("/w/personal/inbox")
    assert ">2<" in r_inbox.text

    # On the week page (current week), same.
    r_week = client.get(f"/w/personal/week/{cy}-W{cw:02d}")
    assert ">2<" in r_week.text


def test_week_tab_badge_uses_current_not_viewed_week(client: TestClient) -> None:
    """Even when browsing a past week with tasks, the badge reflects the *current* week."""
    cy, cw = get_current_iso_week()
    with Session(engine) as s:
        # 5 open in current week (drives the badge).
        for i in range(5):
            s.add(Task(workspace_id=_ws_id(), title=f"now{i}",
                       iso_year=cy, iso_week=cw, position=i))
        # 0 in some past week we view.
        s.commit()

    r = client.get("/w/personal/week/2026-W01")  # arbitrary past week
    # Badge should show 5, regardless of which week the user is viewing.
    assert ">5<" in r.text


def test_no_tab_badge_when_count_is_zero(client: TestClient) -> None:
    """Tab badges hide (display:none via Tailwind 'hidden' class) when count is 0.

    The badge spans always render so HTMX OOB swaps have stable id targets,
    but they get the `hidden` class when their count is zero.
    """
    r = client.get("/w/personal/week/2026-W19")
    topbar = r.text.split('placeholder="', 1)[0]
    # Badge spans exist (with stable ids) but are hidden.
    assert 'id="inbox-tab-badge"' in topbar
    assert 'id="week-tab-badge"' in topbar
    # Both should have the `hidden` class when zero.
    inbox_badge_block = topbar.split('id="inbox-tab-badge"')[1].split("</span>")[0]
    week_badge_block = topbar.split('id="week-tab-badge"')[1].split("</span>")[0]
    assert "hidden" in inbox_badge_block
    assert "hidden" in week_badge_block


def test_workspace_dropdown_has_no_count_badges(client: TestClient) -> None:
    """The workspace switcher pill + dropdown menu items render without numeric badges."""
    # Seed two workspaces with tasks so badges WOULD have shown up under the old design.
    cy, cw = get_current_iso_week()
    with Session(engine) as s:
        s.add(Workspace(slug="work", name="Work", color="#0F766E"))
        s.commit()
        for i in range(3):
            s.add(Task(workspace_id=_ws_id(), title=f"p{i}",
                       iso_year=cy, iso_week=cw, position=i))
        ws_work = s.exec(select(Workspace).where(Workspace.slug == "work")).first()
        for i in range(2):
            s.add(Task(workspace_id=ws_work.id, title=f"w{i}",
                       iso_year=cy, iso_week=cw, position=i))
        s.commit()

    r = client.get(f"/w/personal/week/{cy}-W{cw:02d}")
    # Find the dropdown region (between the dropdown's Alpine x-show and the tab nav).
    # A simpler check: the workspaces list rendered as `role="menuitem"` links should
    # not contain badge count spans for those workspaces. We verify by ensuring no
    # rounded-full pill element appears inside any role="menuitem" anchor.
    dropdown_section = r.text.split('role="menu"', 1)[1].split("</nav>", 1)[0]
    # Tags pills also use rounded-full; a simpler signal — no occurrence of '>3<'
    # or '>2<' inside a menuitem anchor.
    menuitem_blobs = []
    rest = dropdown_section
    while 'role="menuitem"' in rest:
        rest = rest.split('role="menuitem"', 1)[1]
        blob = rest.split("</a>", 1)[0]
        menuitem_blobs.append(blob)
    for blob in menuitem_blobs:
        assert ">3<" not in blob, "Personal's task count should not appear in the dropdown"
        assert ">2<" not in blob, "Work's task count should not appear in the dropdown"


def test_mutation_response_includes_oob_tab_badge_swaps(client: TestClient) -> None:
    """Every mutation partial must include hx-swap-oob spans for the tab badges
    so the topbar updates in place without a refresh."""
    cy, cw = get_current_iso_week()
    # Capture into the inbox so a complete-toggle target exists.
    client.post("/w/personal/inbox/tasks", data={"capture_text": "x"})
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id

    r = client.post(f"/w/personal/inbox/tasks/{tid}/complete")
    assert r.status_code == 200
    # Mutation response carries OOB fragments.
    assert 'hx-swap-oob="true"' in r.text
    assert r.text.count('hx-swap-oob="true"') >= 2


def test_full_page_render_does_not_include_oob_swaps(client: TestClient) -> None:
    """Initial page render (GET) must not emit OOB elements — they'd render visibly.

    OOB belongs only in mutation responses; the topbar already renders the
    canonical badge spans at the top.
    """
    for url in ["/w/personal/week/2026-W19", "/w/personal/inbox"]:
        r = client.get(url)
        assert r.status_code == 200
        # Topbar renders one inbox-tab-badge and one week-tab-badge — that's it.
        assert r.text.count('id="inbox-tab-badge"') == 1
        assert r.text.count('id="week-tab-badge"') == 1
        # No hx-swap-oob anywhere on initial render.
        assert "hx-swap-oob" not in r.text


def _badge_block(html: str, badge_id: str) -> str:
    """Return the full <span id='badge_id' …>…</span> element as a substring."""
    start = html.find(f'id="{badge_id}"')
    assert start != -1, f"badge {badge_id} not found in HTML"
    end = html.find("</span>", start) + len("</span>")
    # Walk back to the opening `<` to capture the full element.
    open_pos = html.rfind("<span", 0, start)
    return html[open_pos:end]


def test_complete_decrements_inbox_tab_badge_via_oob(client: TestClient) -> None:
    """The OOB span returned by /inbox/.../complete should reflect the new open count."""
    with Session(engine) as s:
        # Two open inbox tasks.
        s.add(Task(workspace_id=_ws_id(), title="a", position=1))
        s.add(Task(workspace_id=_ws_id(), title="b", position=2))
        s.commit()
        first_id = s.exec(select(Task).where(Task.title == "a")).first().id

    # Initial page → badge shows 2.
    r0 = client.get("/w/personal/inbox")
    assert ">2</span>" in _badge_block(r0.text, "inbox-tab-badge")

    # Complete one → OOB fragment should now contain 1.
    r1 = client.post(f"/w/personal/inbox/tasks/{first_id}/complete")
    oob = _badge_block(r1.text, "inbox-tab-badge")
    assert ">1</span>" in oob
    assert 'hx-swap-oob="true"' in oob


# ----- POST /inbox/tasks (create) -----------------------------------------


def test_inbox_create_lands_in_inbox(client: TestClient) -> None:
    r = client.post(
        "/w/personal/inbox/tasks",
        data={"capture_text": "Triage this #urgent @review ~30m"},
    )
    assert r.status_code == 200
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.title == "Triage this"
        assert t.iso_year is None and t.iso_week is None
        assert t.project == "review"
        assert t.estimate_hours == 0.5


def test_inbox_create_empty_is_noop(client: TestClient) -> None:
    r = client.post("/w/personal/inbox/tasks", data={"capture_text": "   "})
    assert r.status_code == 200
    with Session(engine) as s:
        assert s.exec(select(Task)).all() == []


def test_inbox_create_returns_inbox_partial(client: TestClient) -> None:
    """Response should be the inbox partial, not the week partial."""
    r = client.post("/w/personal/inbox/tasks", data={"capture_text": "Test"})
    assert r.status_code == 200
    assert 'id="inbox-main"' in r.text
    assert 'id="week-main"' not in r.text


# ----- POST /inbox/tasks/<id>/complete -----------------------------------


def test_inbox_complete_toggles_status(client: TestClient) -> None:
    client.post("/w/personal/inbox/tasks", data={"capture_text": "Test"})
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id

    client.post(f"/w/personal/inbox/tasks/{tid}/complete")
    with Session(engine) as s:
        assert s.exec(select(Task)).first().status == "completed"
    client.post(f"/w/personal/inbox/tasks/{tid}/complete")
    with Session(engine) as s:
        assert s.exec(select(Task)).first().status == "open"


# ----- POST /inbox/tasks/<id>/edit ---------------------------------------


def test_inbox_edit_updates_fields(client: TestClient) -> None:
    client.post("/w/personal/inbox/tasks", data={"capture_text": "Original"})
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id

    r = client.post(
        f"/w/personal/inbox/tasks/{tid}/edit",
        data={"title": "Renamed", "tags": "urgent auth", "project": "x", "estimate": "1h"},
    )
    assert r.status_code == 200
    assert 'id="inbox-main"' in r.text  # inbox partial, not week
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.title == "Renamed"
        assert t.project == "x"
        assert t.estimate_hours == 1.0
        names = sorted([s.exec(select(Tag).where(Tag.id == link.tag_id)).first().name
                        for link in s.exec(select(TaskTag)).all()])
        assert names == ["auth", "urgent"]


def test_inbox_edit_empty_title_noop(client: TestClient) -> None:
    client.post("/w/personal/inbox/tasks", data={"capture_text": "Keep me"})
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id
    client.post(
        f"/w/personal/inbox/tasks/{tid}/edit",
        data={"title": "  ", "tags": "x", "project": "y", "estimate": "1h"},
    )
    with Session(engine) as s:
        assert s.exec(select(Task)).first().title == "Keep me"


# ----- POST /inbox/tasks/<id>/delete -------------------------------------


def test_inbox_delete_removes_task(client: TestClient) -> None:
    client.post("/w/personal/inbox/tasks", data={"capture_text": "Bye"})
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id
    client.post(f"/w/personal/inbox/tasks/{tid}/delete")
    with Session(engine) as s:
        assert s.exec(select(Task)).all() == []


# ----- POST /inbox/tasks/<id>/schedule -----------------------------------


def test_inbox_schedule_moves_to_current_iso_week(client: TestClient) -> None:
    client.post("/w/personal/inbox/tasks", data={"capture_text": "Schedule me"})
    with Session(engine) as s:
        tid = s.exec(select(Task)).first().id

    r = client.post(f"/w/personal/inbox/tasks/{tid}/schedule")
    assert r.status_code == 200
    cy, cw = get_current_iso_week()
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert t.iso_year == cy and t.iso_week == cw


def test_inbox_schedule_already_scheduled_is_noop(client: TestClient) -> None:
    """Defensive: if somehow the task is already scheduled, /schedule shouldn't move it."""
    with Session(engine) as s:
        s.add(Task(workspace_id=_ws_id(), title="Already in W19",
                   iso_year=2026, iso_week=19, position=1))
        s.commit()
        tid = s.exec(select(Task)).first().id

    client.post(f"/w/personal/inbox/tasks/{tid}/schedule")
    with Session(engine) as s:
        t = s.exec(select(Task)).first()
        assert (t.iso_year, t.iso_week) == (2026, 19)


# ----- Filter / sort ------------------------------------------------------


def _seed_inbox_with_tags_projects():
    """Three inbox tasks, varied tags/projects for filter+sort tests."""
    with Session(engine) as s:
        ws_id = _ws_id()
        urgent = Tag(workspace_id=ws_id, name="urgent")
        admin = Tag(workspace_id=ws_id, name="admin")
        s.add_all([urgent, admin])
        s.commit()

        # We'll set created_at explicitly to test sort.
        now = datetime.now(timezone.utc)
        # Older first in insertion, newer last.
        a = Task(workspace_id=ws_id, title="Apple thing", position=1, project="alpha",
                 created_at=now - timedelta(hours=2))
        b = Task(workspace_id=ws_id, title="Banana", position=2, project="beta",
                 created_at=now - timedelta(hours=1))
        c = Task(workspace_id=ws_id, title="Cherry", position=3, project=None,
                 created_at=now)
        s.add_all([a, b, c])
        s.commit()

        s.add_all([
            TaskTag(task_id=a.id, tag_id=urgent.id),
            TaskTag(task_id=b.id, tag_id=admin.id),
        ])
        s.commit()


def test_filter_by_tag_on_inbox(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    r = client.get("/w/personal/inbox?tag=urgent")
    assert r.status_code == 200
    assert "Apple thing" in r.text
    assert "Banana" not in r.text
    assert "Cherry" not in r.text


def test_filter_by_project_on_inbox(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    r = client.get("/w/personal/inbox?project=alpha")
    assert "Apple thing" in r.text
    assert "Banana" not in r.text


def test_combined_filter_on_inbox(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    r = client.get("/w/personal/inbox?tag=urgent&project=alpha")
    assert "Apple thing" in r.text
    assert "Banana" not in r.text


def test_sort_newest_default(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    r = client.get("/w/personal/inbox")
    # Cherry (newest) should appear before Banana, which should appear before Apple.
    pos_c = r.text.find("Cherry")
    pos_b = r.text.find("Banana")
    pos_a = r.text.find("Apple thing")
    assert pos_c < pos_b < pos_a


def test_sort_oldest(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    r = client.get("/w/personal/inbox?sort=oldest")
    pos_a = r.text.find("Apple thing")
    pos_b = r.text.find("Banana")
    pos_c = r.text.find("Cherry")
    assert pos_a < pos_b < pos_c


def test_sort_title(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    r = client.get("/w/personal/inbox?sort=title")
    pos_a = r.text.find("Apple thing")
    pos_b = r.text.find("Banana")
    pos_c = r.text.find("Cherry")
    assert pos_a < pos_b < pos_c


def test_sort_project_groups_named_first(client: TestClient) -> None:
    """Named projects should appear before null-project tasks."""
    _seed_inbox_with_tags_projects()
    r = client.get("/w/personal/inbox?sort=project")
    pos_a = r.text.find("Apple thing")  # alpha
    pos_b = r.text.find("Banana")       # beta
    pos_c = r.text.find("Cherry")       # null project
    assert pos_a < pos_b
    assert pos_b < pos_c  # null sorts last via COALESCE


def test_invalid_sort_falls_back_to_newest(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    r = client.get("/w/personal/inbox?sort=garbage")
    # Should render normally; newest order applies.
    pos_c = r.text.find("Cherry")
    pos_a = r.text.find("Apple thing")
    assert pos_c < pos_a


# ----- HX-Current-URL preserves filter through inbox mutations ------------


def test_mutation_preserves_filter_via_hx_current_url(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    with Session(engine) as s:
        target = s.exec(select(Task).where(Task.title == "Apple thing")).first()
        tid = target.id

    r = client.post(
        f"/w/personal/inbox/tasks/{tid}/complete",
        headers={"HX-Current-URL": "http://test/w/personal/inbox?tag=urgent"},
    )
    assert r.status_code == 200
    # Filter must persist: only urgent-tagged shown.
    assert "Apple thing" in r.text
    assert "Banana" not in r.text


def test_mutation_preserves_sort_via_hx_current_url(client: TestClient) -> None:
    _seed_inbox_with_tags_projects()
    with Session(engine) as s:
        tid = s.exec(select(Task).where(Task.title == "Cherry")).first().id

    r = client.post(
        f"/w/personal/inbox/tasks/{tid}/complete",
        headers={"HX-Current-URL": "http://test/w/personal/inbox?sort=oldest"},
    )
    # Oldest-first ordering preserved in the partial.
    pos_a = r.text.find("Apple thing")
    pos_b = r.text.find("Banana")
    pos_c = r.text.find("Cherry")
    assert pos_a < pos_b < pos_c
