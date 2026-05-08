"""Tests for the week-view tag/project filters."""

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
from sqlmodel import Session, SQLModel  # noqa: E402

from kairo_web.db import engine  # noqa: E402
from kairo_web.main import app  # noqa: E402
from kairo_web.models import Tag, Task, TaskTag, Workspace  # noqa: E402

YW = "2026-W19"


@pytest.fixture(autouse=True)
def fresh_db():
    """Seed: workspace 'personal' with five week-19 tasks across two tags + two projects."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        ws = Workspace(slug="personal", name="Personal", color="#BE185D", is_default=True)
        s.add(ws)
        s.commit()
        ws_id = ws.id

        # Three tags.
        urgent = Tag(workspace_id=ws_id, name="urgent")
        admin = Tag(workspace_id=ws_id, name="admin")
        family = Tag(workspace_id=ws_id, name="family")
        s.add_all([urgent, admin, family])
        s.commit()

        # Tasks.
        # 1 — urgent + project A
        t1 = Task(workspace_id=ws_id, title="Pay credit card",
                  position=1, iso_year=2026, iso_week=19,
                  project="bills", is_today=True)
        # 2 — admin + project A
        t2 = Task(workspace_id=ws_id, title="Renew car insurance",
                  position=2, iso_year=2026, iso_week=19,
                  project="bills")
        # 3 — family, no project
        t3 = Task(workspace_id=ws_id, title="Call mom",
                  position=3, iso_year=2026, iso_week=19,
                  is_today=True)
        # 4 — no tags, project B
        t4 = Task(workspace_id=ws_id, title="Plan trip",
                  position=4, iso_year=2026, iso_week=19,
                  project="trip")
        # 5 — urgent, no project (also completed, to test stats)
        t5 = Task(workspace_id=ws_id, title="Reply to mom",
                  position=5, iso_year=2026, iso_week=19,
                  status="completed")
        s.add_all([t1, t2, t3, t4, t5])
        s.commit()

        s.add_all([
            TaskTag(task_id=t1.id, tag_id=urgent.id),
            TaskTag(task_id=t2.id, tag_id=admin.id),
            TaskTag(task_id=t3.id, tag_id=family.id),
            TaskTag(task_id=t5.id, tag_id=urgent.id),
        ])
        s.commit()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ----- No filter (baseline) -----------------------------------------------


def test_no_filter_shows_all_week_tasks(client: TestClient) -> None:
    r = client.get(f"/w/personal/week/{YW}")
    assert r.status_code == 200
    for title in ["Pay credit card", "Renew car insurance", "Call mom", "Plan trip", "Reply to mom"]:
        assert title in r.text


# ----- Tag filter ----------------------------------------------------------


def test_filter_by_tag_restricts_week_table(client: TestClient) -> None:
    """?tag=urgent shows only tasks linked to the 'urgent' tag in this workspace."""
    r = client.get(f"/w/personal/week/{YW}?tag=urgent")
    assert r.status_code == 200
    assert "Pay credit card" in r.text  # has urgent
    assert "Reply to mom" in r.text     # has urgent (completed)
    # Tasks without the urgent tag are excluded.
    assert "Renew car insurance" not in r.text
    assert "Call mom" not in r.text
    assert "Plan trip" not in r.text


def test_filter_by_tag_restricts_today_strip(client: TestClient) -> None:
    """Today strip respects the filter — only today-flagged tasks matching tag remain."""
    # task 1 (Pay credit card) is today + urgent
    # task 3 (Call mom) is today but family — should be filtered out
    r = client.get(f"/w/personal/week/{YW}?tag=urgent")
    # The unique section heading text isolates the today strip from the week table.
    _, after_today = r.text.split(">Today</span>", 1)
    today_section, _ = after_today.split(">This week</span>", 1)
    assert "Pay credit card" in today_section
    assert "Call mom" not in today_section


def test_filter_by_unknown_tag_renders_empty(client: TestClient) -> None:
    r = client.get(f"/w/personal/week/{YW}?tag=nonsense")
    assert r.status_code == 200
    assert "No tasks match this filter" in r.text


# ----- Project filter ------------------------------------------------------


def test_filter_by_project(client: TestClient) -> None:
    r = client.get(f"/w/personal/week/{YW}?project=bills")
    assert r.status_code == 200
    assert "Pay credit card" in r.text
    assert "Renew car insurance" in r.text
    assert "Plan trip" not in r.text
    assert "Call mom" not in r.text


# ----- Combined filter -----------------------------------------------------


def test_combined_filters_AND(client: TestClient) -> None:
    """tag=urgent AND project=bills → only Pay credit card."""
    r = client.get(f"/w/personal/week/{YW}?tag=urgent&project=bills")
    assert r.status_code == 200
    assert "Pay credit card" in r.text
    assert "Reply to mom" not in r.text       # urgent but no project
    assert "Renew car insurance" not in r.text  # bills but admin tag


# ----- Stats stay unfiltered -----------------------------------------------


def test_stats_stay_unfiltered_under_a_filter(client: TestClient) -> None:
    """Stats footer shows the full week count regardless of active filter."""
    r = client.get(f"/w/personal/week/{YW}?tag=urgent")
    # 5 tasks total: 4 open + 1 completed.
    # The footer shows: Open 4, Done 1, plus the percent etc.
    # We verify with explicit text patterns since the stats are inline.
    assert "Open" in r.text
    # Look for the visible "Open <strong...>4</strong>" pattern.
    assert ">4<" in r.text  # 4 open
    assert ">1<" in r.text  # 1 done
    # And the "showing N of M" indicator should reflect the filtered count.
    assert "showing" in r.text
    assert "of 5" in r.text  # M=5 (full week)


# ----- Filter UI affordances ----------------------------------------------


def test_active_filter_chip_with_remove_link(client: TestClient) -> None:
    """Active filter shows a chip with X linking to a URL that removes just that filter."""
    r = client.get(f"/w/personal/week/{YW}?tag=urgent&project=bills")
    # Removing the tag should keep the project.
    assert f"/w/personal/week/{YW}?project=bills" in r.text
    # Removing the project should keep the tag.
    assert f"/w/personal/week/{YW}?tag=urgent" in r.text


def test_clear_all_link_present_under_filter(client: TestClient) -> None:
    r = client.get(f"/w/personal/week/{YW}?tag=urgent")
    assert "Clear all" in r.text
    # Clear-all URL has no querystring (canonicalized).
    # Must be a clean /w/personal/week/<YW> with no params after it.
    assert f'href="/w/personal/week/{YW}"' in r.text


def test_clear_all_absent_when_no_filter(client: TestClient) -> None:
    r = client.get(f"/w/personal/week/{YW}")
    assert "Clear all" not in r.text
    assert "showing" not in r.text  # no "N of M" line either


def test_filter_picker_dropdowns_present(client: TestClient) -> None:
    """The chip row should expose pickers for any tag/project the workspace has."""
    r = client.get(f"/w/personal/week/{YW}")
    assert "+ Tag" in r.text
    assert "+ Project" in r.text


# ----- Capture-bar autocomplete --------------------------------------------


def test_capture_bar_includes_autocomplete_data(client: TestClient) -> None:
    """The capture form should be initialized with the workspace's tags + projects
    (used by the inline autocomplete dropdown)."""
    r = client.get(f"/w/personal/week/{YW}")
    assert r.status_code == 200
    # The Alpine x-data init call serializes available_tags + available_projects
    # via Jinja's tojson filter. Pin the function name + at least one known tag/project.
    assert "captureAutocomplete(" in r.text
    assert '"urgent"' in r.text or "'urgent'" in r.text  # tag from seed
    assert '"bills"' in r.text or "'bills'" in r.text   # project from seed


def test_capture_bar_autocomplete_present_on_inbox_page(client: TestClient) -> None:
    """Same component on the inbox page; its data also reflects the workspace."""
    r = client.get("/w/personal/inbox")
    assert r.status_code == 200
    assert "captureAutocomplete(" in r.text


def test_edit_form_autocomplete_modes_present(client: TestClient) -> None:
    """Each task row's edit form should include autocomplete in 'tags' and 'project' modes."""
    r = client.get(f"/w/personal/week/{YW}")
    assert r.status_code == 200
    # Tags input wraps captureAutocomplete(..., 'tags')
    assert '"tags")' in r.text or "'tags')" in r.text or '"tags")' in r.text
    # Project input wraps captureAutocomplete(..., 'project')
    assert '"project")' in r.text or "'project')" in r.text
    # The capture bar still uses the default (capture) mode.
    assert "captureAutocomplete(" in r.text


def test_edit_form_autocomplete_on_inbox_page(client: TestClient) -> None:
    """Inbox page's edit form also has autocomplete on tags + project."""
    from sqlmodel import select as sm_select
    from kairo_web.models import Workspace as _W

    with Session(engine) as s:
        ws = s.exec(sm_select(_W).where(_W.slug == "personal")).first()
        s.add(Task(workspace_id=ws.id, title="x", position=1))
        s.commit()
    r = client.get("/w/personal/inbox")
    assert r.status_code == 200
    assert '"tags")' in r.text
    assert '"project")' in r.text


# ----- Filter preservation through HTMX mutations --------------------------


def test_mutation_preserves_active_filter_via_hx_current_url(client: TestClient) -> None:
    """When the user is filtering and clicks 'complete', the partial response
    must continue to reflect the filter — i.e. the view doesn't snap back to unfiltered."""
    # Find a non-completed urgent task to toggle.
    with Session(engine) as s:
        from sqlmodel import select as sm_select
        target = s.exec(sm_select(Task).where(Task.title == "Pay credit card")).first()
        target_id = target.id

    r = client.post(
        f"/w/personal/week/{YW}/tasks/{target_id}/complete",
        headers={"HX-Current-URL": f"http://test/w/personal/week/{YW}?tag=urgent"},
    )
    assert r.status_code == 200
    # Partial response: only urgent-tagged tasks visible.
    assert "Pay credit card" in r.text  # the toggled one stays in view
    assert "Reply to mom" in r.text     # other urgent
    assert "Renew car insurance" not in r.text  # not urgent
    assert "Plan trip" not in r.text             # not urgent


def test_mutation_without_hx_current_url_renders_unfiltered(client: TestClient) -> None:
    """A direct (non-HTMX) POST has no current-URL, so partial is unfiltered.

    Curl/scripted mutations get the full week back; that's an acceptable trade-off
    for keeping the wire protocol stateless.
    """
    with Session(engine) as s:
        from sqlmodel import select as sm_select
        target = s.exec(sm_select(Task).where(Task.title == "Pay credit card")).first()
        target_id = target.id

    r = client.post(f"/w/personal/week/{YW}/tasks/{target_id}/complete")
    assert r.status_code == 200
    # All tasks are visible because no filter context was supplied.
    assert "Plan trip" in r.text
    assert "Renew car insurance" in r.text
