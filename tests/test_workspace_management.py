"""Tests for the dynamic workspace model.

Covers:
  - workspace_meta color math: derived bg/fg are valid hex, contrast where expected
  - add-workspace CLI: happy path, duplicate detection, slug validation
"""

from __future__ import annotations

import os
import tempfile

import pytest

# Reuse the env setup from test_routes (same DB path, fresh schema per test).
os.environ.setdefault("KAIRO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("KAIRO_OWNER_EMAIL", "test@example.com")

if "KAIRO_DATABASE_URL" not in os.environ:
    _fd, _path = tempfile.mkstemp(suffix=".db")
    os.close(_fd)
    os.environ["KAIRO_DATABASE_URL"] = f"sqlite:///{_path}"

from click.testing import CliRunner  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from kairo_web.cli import cli  # noqa: E402
from kairo_web.db import engine  # noqa: E402
from kairo_web.models import Workspace  # noqa: E402
from kairo_web.workspace_meta import (  # noqa: E402
    DEFAULT_PALETTE,
    color_for_index,
    derive_bg_fg,
)


@pytest.fixture(autouse=True)
def fresh_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield


# ----- Color math ----------------------------------------------------------


def test_palette_index_wraps():
    assert color_for_index(0) == DEFAULT_PALETTE[0]
    assert color_for_index(len(DEFAULT_PALETTE)) == DEFAULT_PALETTE[0]
    assert color_for_index(len(DEFAULT_PALETTE) + 1) == DEFAULT_PALETTE[1]


def test_derive_bg_fg_returns_valid_hex():
    bg, fg = derive_bg_fg("#0F766E")
    assert bg.startswith("#") and len(bg) == 7
    assert fg.startswith("#") and len(fg) == 7
    assert all(c in "0123456789ABCDEF" for c in bg[1:])
    assert all(c in "0123456789ABCDEF" for c in fg[1:])


def test_derive_bg_fg_bg_is_lighter_than_fg():
    """Sanity: the bg should be perceptually lighter than the fg."""
    def _luma(hex_str: str) -> float:
        h = hex_str.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return 0.299 * r + 0.587 * g + 0.114 * b
    for accent in DEFAULT_PALETTE:
        bg, fg = derive_bg_fg(accent)
        assert _luma(bg) > _luma(fg), f"bg should be lighter than fg for {accent}"


def test_derive_bg_fg_short_hex():
    bg, fg = derive_bg_fg("#abc")
    assert len(bg) == 7
    assert len(fg) == 7


# ----- add-workspace CLI ---------------------------------------------------


def _run(*args: str):
    return CliRunner().invoke(cli, list(args), catch_exceptions=False)


def test_add_workspace_happy_path():
    r = _run("add-workspace", "--slug=work", "--name=Work")
    assert r.exit_code == 0, r.output
    assert "created workspace 'work'" in r.output

    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "work")).first()
        assert ws is not None
        assert ws.name == "Work"
        # Auto-picked from palette[0] since count was 0.
        assert ws.color == DEFAULT_PALETTE[0]


def test_add_workspace_picks_next_palette_color_by_count():
    # Pre-seed one workspace, so the next add gets palette[1].
    with Session(engine) as s:
        s.add(Workspace(slug="personal", name="Personal", color=DEFAULT_PALETTE[0]))
        s.commit()
    r = _run("add-workspace", "--slug=work", "--name=Work")
    assert r.exit_code == 0
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "work")).first()
        assert ws.color == DEFAULT_PALETTE[1]


def test_add_workspace_explicit_color():
    r = _run("add-workspace", "--slug=blue", "--name=Blue", "--color=#0066CC")
    assert r.exit_code == 0
    with Session(engine) as s:
        ws = s.exec(select(Workspace).where(Workspace.slug == "blue")).first()
        assert ws.color == "#0066CC"


def test_add_workspace_rejects_duplicate_slug():
    _run("add-workspace", "--slug=work", "--name=Work")
    r = _run("add-workspace", "--slug=work", "--name=Other")
    assert r.exit_code != 0
    assert "already exists" in r.output


def test_add_workspace_rejects_invalid_slug():
    for bad in ["With Space", "WithCaps", "-leading-hyphen", "with/slash"]:
        r = _run("add-workspace", "--slug", bad, "--name", "X")
        assert r.exit_code != 0, f"slug '{bad}' should be rejected"


def test_add_workspace_rejects_invalid_color():
    r = _run("add-workspace", "--slug=foo", "--name=Foo", "--color=red")
    assert r.exit_code != 0
    assert "color" in r.output.lower()


def test_list_workspaces_empty():
    r = _run("list-workspaces")
    assert r.exit_code == 0
    assert "no workspaces yet" in r.output


def test_list_workspaces_after_add():
    _run("add-workspace", "--slug=work", "--name=Work")
    r = _run("list-workspaces")
    assert r.exit_code == 0
    assert "work" in r.output
    assert "Work" in r.output
