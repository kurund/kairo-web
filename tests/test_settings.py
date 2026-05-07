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
        s.add(Workspace(slug="personal", name="Personal", color="#BE185D"))
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
