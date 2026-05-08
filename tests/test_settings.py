"""HTTP tests for the workspace settings routes."""

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
from kairo_web.models import Workspace  # noqa: E402


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


# ----- GET page ------------------------------------------------------------


def test_get_settings_page(client: TestClient) -> None:
    r = client.get("/settings/workspaces")
    assert r.status_code == 200
    assert "Workspaces" in r.text
    assert "Personal" in r.text
    assert "personal" in r.text  # slug
    assert "#BE185D" in r.text or "#be185d" in r.text.lower()


def test_get_settings_with_error_query(client: TestClient) -> None:
    r = client.get("/settings/workspaces?error=test+message")
    assert r.status_code == 200
    assert "test message" in r.text


# ----- POST create ---------------------------------------------------------


def test_create_workspace_happy_path(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces",
        data={"slug": "work", "name": "Work", "color": "#0F766E"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings/workspaces"
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "work")).first()
        assert ws is not None
        assert ws.name == "Work"
        assert ws.color == "#0F766E"


def test_create_workspace_lowercases_slug_uppercases_color(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces",
        data={"slug": "  Work  ", "name": "  Work  ", "color": "#0f766e"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "work")).first()
        assert ws.name == "Work"   # trimmed
        assert ws.color == "#0F766E"  # uppercased


def test_create_workspace_rejects_duplicate_slug(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces",
        data={"slug": "personal", "name": "Other", "color": "#0F766E"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    assert "already%20exists" in r.headers["location"]


def test_create_workspace_rejects_invalid_slug(client: TestClient) -> None:
    # Note: the web route lowercases before validating, so "WithCaps" → "withcaps"
    # is accepted as a UX convenience. Truly invalid: spaces, leading hyphen,
    # special chars, empty.
    for bad in ["With Space", "-leading-hyphen", "with/slash", ""]:
        r = client.post(
            "/settings/workspaces",
            data={"slug": bad, "name": "X", "color": "#0F766E"},
            follow_redirects=False,
        )
        assert r.status_code == 303, f"slug '{bad}' should fail validation"
        assert "error=" in r.headers["location"], f"slug '{bad}' should redirect with error"


def test_create_workspace_lowercases_uppercase_slug(client: TestClient) -> None:
    """Web UX: typing 'Work' in the slug field is fine — auto-lowercased."""
    r = client.post(
        "/settings/workspaces",
        data={"slug": "WithCaps", "name": "X", "color": "#0F766E"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" not in r.headers["location"]
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "withcaps")).first()
        assert ws is not None


def test_create_workspace_rejects_invalid_color(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces",
        data={"slug": "foo", "name": "Foo", "color": "red"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


def test_create_workspace_rejects_empty_name(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces",
        data={"slug": "foo", "name": "  ", "color": "#0F766E"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


# ----- POST edit -----------------------------------------------------------


def test_edit_workspace_happy_path(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces/personal/edit",
        data={"name": "Life", "color": "#16A34A"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings/workspaces"
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        assert ws.name == "Life"
        assert ws.color == "#16A34A"


def test_edit_workspace_404_for_unknown_slug(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces/nope/edit",
        data={"name": "X", "color": "#0F766E"},
    )
    assert r.status_code == 404


def test_edit_workspace_rejects_invalid_color(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces/personal/edit",
        data={"name": "Personal", "color": "not-a-hex"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    # No mutation should have happened.
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        assert ws.color == "#BE185D"


def test_edit_workspace_rejects_empty_name(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces/personal/edit",
        data={"name": "   ", "color": "#0F766E"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        assert ws.name == "Personal"  # unchanged


# ----- Dropdown link from week page ----------------------------------------


def test_dropdown_links_to_settings_page(client: TestClient) -> None:
    r = client.get("/w/personal/week/2026-W19")
    assert r.status_code == 200
    assert 'href="/settings/workspaces"' in r.text
    assert "Manage workspaces" in r.text


# ----- Set-as-default ------------------------------------------------------


def test_set_default_atomically_clears_other_defaults(client: TestClient) -> None:
    """Marking 'work' default must clear is_default on 'personal' (the existing default)."""
    with Session(engine) as s:
        s.add(Workspace(slug="work", name="Work", color="#0F766E", is_default=False))
        s.commit()

    r = client.post("/settings/workspaces/work/default", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/settings/workspaces"

    with Session(engine) as s:
        rows = {w.slug: w.is_default for w in s.exec(select(Workspace)).all()}
        assert rows == {"personal": False, "work": True}


def test_set_default_404_for_unknown_slug(client: TestClient) -> None:
    r = client.post("/settings/workspaces/nope/default")
    assert r.status_code == 404


def test_root_redirects_to_default_workspace(client: TestClient) -> None:
    """Root '/' picks whichever workspace has is_default=True."""
    with Session(engine) as s:
        s.add(Workspace(slug="work", name="Work", color="#0F766E", is_default=False))
        s.commit()
    r1 = client.get("/", follow_redirects=False)
    assert r1.status_code == 302
    assert r1.headers["location"].startswith("/w/personal/week/")

    # Move default to 'work' and confirm root follows.
    client.post("/settings/workspaces/work/default")
    r2 = client.get("/", follow_redirects=False)
    assert r2.status_code == 302
    assert r2.headers["location"].startswith("/w/work/week/")


def test_root_falls_back_to_first_workspace_when_no_default(client: TestClient) -> None:
    """If for some reason no workspace is marked default, root picks the lowest-id one."""
    with Session(engine) as s:
        s.exec(select(Workspace).where(Workspace.slug == "personal")).first().is_default = False  # type: ignore[union-attr]
        s.commit()
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("/w/personal/week/")  # only one exists


# ----- Delete --------------------------------------------------------------


def _add_workspace(slug: str, name: str = "X", color: str = "#0F766E", is_default: bool = False) -> int:
    with Session(engine) as s:
        ws = Workspace(slug=slug, name=name, color=color, is_default=is_default)
        s.add(ws)
        s.commit()
        return ws.id  # type: ignore[return-value]


def test_delete_workspace_happy_path_with_cascade(client: TestClient) -> None:
    """Delete cascades through tasks + tags + task_tag rows."""
    from kairo_web.models import Tag, Task, TaskTag

    ws_id = _add_workspace("work", "Work")
    with Session(engine) as s:
        s.add(Task(workspace_id=ws_id, title="t1", position=1, iso_year=2026, iso_week=19))
        s.add(Task(workspace_id=ws_id, title="t2", position=2))  # inbox
        tag = Tag(workspace_id=ws_id, name="urgent")
        s.add(tag)
        s.commit()
        # Link first task to the tag.
        first_task = s.exec(select(Task).where(Task.workspace_id == ws_id)).first()
        s.add(TaskTag(task_id=first_task.id, tag_id=tag.id))
        s.commit()

    r = client.post(
        "/settings/workspaces/work/delete",
        data={"confirm_slug": "work"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings/workspaces"

    with Session(engine) as s:
        assert s.exec(select(Workspace).where(Workspace.slug == "work")).first() is None
        # Cascaded: no orphan tasks, tags, or task_tag rows for this ws.
        assert s.exec(select(Task).where(Task.workspace_id == ws_id)).all() == []
        assert s.exec(select(Tag).where(Tag.workspace_id == ws_id)).all() == []
        assert s.exec(select(TaskTag)).all() == []
        # 'personal' still here.
        assert s.exec(select(Workspace).where(Workspace.slug == "personal")).first() is not None


def test_delete_rejects_slug_mismatch(client: TestClient) -> None:
    _add_workspace("work")
    r = client.post(
        "/settings/workspaces/work/delete",
        data={"confirm_slug": "wrong"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    with Session(engine) as s:
        assert s.exec(select(Workspace).where(Workspace.slug == "work")).first() is not None


def test_delete_rejects_default_workspace(client: TestClient) -> None:
    """The default workspace must be unmarked (set another default) before deletion."""
    r = client.post(
        "/settings/workspaces/personal/delete",
        data={"confirm_slug": "personal"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    assert "default" in r.headers["location"]
    with Session(engine) as s:
        assert s.exec(select(Workspace).where(Workspace.slug == "personal")).first() is not None


def test_delete_rejects_only_workspace(client: TestClient) -> None:
    """Even after un-defaulting, deleting the only remaining workspace is refused."""
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        ws.is_default = False
        s.commit()
    r = client.post(
        "/settings/workspaces/personal/delete",
        data={"confirm_slug": "personal"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    assert "only" in r.headers["location"]
    with Session(engine) as s:
        assert s.exec(select(Workspace).where(Workspace.slug == "personal")).first() is not None


def test_delete_404_for_unknown_slug(client: TestClient) -> None:
    r = client.post(
        "/settings/workspaces/nope/delete",
        data={"confirm_slug": "nope"},
    )
    assert r.status_code == 404


def test_delete_does_not_touch_other_workspaces_data(client: TestClient) -> None:
    """Deleting 'work' must leave 'personal's tasks intact."""
    from kairo_web.models import Task

    ws_work = _add_workspace("work", "Work")
    with Session(engine) as s:
        personal = s.exec(select(Workspace).where(Workspace.slug == "personal")).first()
        s.add(Task(workspace_id=personal.id, title="personal task", position=1))
        s.add(Task(workspace_id=ws_work, title="work task", position=1))
        s.commit()

    client.post(
        "/settings/workspaces/work/delete",
        data={"confirm_slug": "work"},
    )

    with Session(engine) as s:
        remaining = list(s.exec(select(Task)).all())
        assert len(remaining) == 1
        assert remaining[0].title == "personal task"


# ----- UI affordance presence ----------------------------------------------


def test_settings_page_shows_default_badge(client: TestClient) -> None:
    r = client.get("/settings/workspaces")
    assert r.status_code == 200
    # The 'personal' row in fresh_db is the default.
    assert ">Default<" in r.text


def test_settings_page_hides_delete_button_on_default_workspace(client: TestClient) -> None:
    """The default workspace must not show a Delete button (would dead-end the app)."""
    _add_workspace("work", "Work")
    r = client.get("/settings/workspaces")
    assert r.status_code == 200
    # Both rows present; only 'work' (non-default) gets a delete button visible.
    delete_targets = [
        line for line in r.text.split("\n") if "/delete" in line
    ]
    # The action lives on the form; one form per non-default workspace.
    assert any("/work/delete" in t for t in delete_targets)
    assert not any("/personal/delete" in t for t in delete_targets)
