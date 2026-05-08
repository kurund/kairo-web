"""Settings routes — workspace management UI.

Exposes:
  GET  /settings/workspaces                  list + forms (page)
  POST /settings/workspaces                  create a new workspace
  POST /settings/workspaces/{slug}/edit      update name + color (slug is immutable)

Slug is intentionally not editable: changing it would break bookmarked URLs and
require updating the active workspace cookie. Use `kairo-web add-workspace`
followed by manual data migration if a slug change is really needed.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, update
from sqlmodel import Session, select

from kairo_web.db import get_session
from kairo_web.models import Tag, Task, TaskTag, Workspace
from kairo_web.paths import TEMPLATE_DIR
from kairo_web.services import queries
from kairo_web.utils import get_current_iso_week
from kairo_web.workspace_meta import (
    DEFAULT_PALETTE,
    color_for_index,
    derive_bg_fg,
)

router = APIRouter(tags=["settings"])
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _enrich(ws: Workspace) -> dict:
    bg, fg = derive_bg_fg(ws.color)
    return {
        "id": ws.id,
        "slug": ws.slug,
        "name": ws.name,
        "color_hex": ws.color,
        "color_bg": bg,
        "color_fg": fg,
        "is_default": bool(ws.is_default),
    }


# ----- GET page ------------------------------------------------------------


@router.get("/settings/workspaces", response_class=HTMLResponse)
def workspaces_page(
    request: Request,
    session: Session = Depends(get_session),
    error: str | None = None,
) -> HTMLResponse:
    workspaces = queries.list_workspaces(session)
    iso_year, iso_week = get_current_iso_week()
    return templates.TemplateResponse(
        request,
        "settings/workspaces.html",
        {
            "workspaces": [_enrich(w) for w in workspaces],
            "palette": DEFAULT_PALETTE,
            "next_palette_color": color_for_index(len(workspaces)),
            "current_year_week": f"{iso_year}-W{iso_week:02d}",
            "error": error,
        },
    )


# ----- POST create ---------------------------------------------------------


@router.post("/settings/workspaces", response_class=HTMLResponse)
def create_workspace(
    slug: str = Form(""),
    name: str = Form(""),
    color: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    slug_clean = slug.strip().lower()
    name_clean = name.strip()
    color_clean = color.strip().upper()

    err = _validate_create(slug_clean, name_clean, color_clean, session)
    if err:
        return RedirectResponse(
            url=f"/settings/workspaces?error={_qs(err)}", status_code=303
        )

    session.add(Workspace(slug=slug_clean, name=name_clean, color=color_clean))
    session.commit()
    return RedirectResponse(url="/settings/workspaces", status_code=303)


def _validate_create(slug: str, name: str, color: str, session: Session) -> str | None:
    if not slug:
        return "slug is required"
    if not _SLUG_RE.fullmatch(slug):
        return (
            "slug must be lowercase, start with a letter or digit, and contain "
            "only letters, digits, hyphens, or underscores"
        )
    if not name:
        return "name is required"
    if not _HEX_RE.fullmatch(color):
        return "color must look like #RRGGBB (six hex digits)"
    existing = session.exec(select(Workspace).where(Workspace.slug == slug)).first()
    if existing:
        return f"workspace '{slug}' already exists"
    return None


# ----- POST edit -----------------------------------------------------------


@router.post("/settings/workspaces/{slug}/edit", response_class=HTMLResponse)
def update_workspace(
    slug: str,
    name: str = Form(""),
    color: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    name_clean = name.strip()
    color_clean = color.strip().upper()

    if not name_clean:
        return RedirectResponse(
            url=f"/settings/workspaces?error={_qs('name is required')}",
            status_code=303,
        )
    if not _HEX_RE.fullmatch(color_clean):
        return RedirectResponse(
            url=f"/settings/workspaces?error={_qs('color must look like #RRGGBB')}",
            status_code=303,
        )

    ws = queries.get_workspace(session, slug)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace '{slug}' not found")

    ws.name = name_clean
    ws.color = color_clean
    session.add(ws)
    session.commit()
    return RedirectResponse(url="/settings/workspaces", status_code=303)


def _qs(s: str) -> str:
    """Light percent-encoding for the redirect querystring."""
    from urllib.parse import quote
    return quote(s, safe="")


# ----- POST set as default ------------------------------------------------


@router.post("/settings/workspaces/{slug}/default", response_class=HTMLResponse)
def set_default_workspace(
    slug: str,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Mark this workspace as default; clear is_default on all others.

    Atomic from the user's perspective: a single commit applies both updates.
    """
    target = queries.get_workspace(session, slug)
    if target is None:
        raise HTTPException(status_code=404, detail=f"workspace '{slug}' not found")

    session.exec(update(Workspace).values(is_default=False))  # type: ignore[arg-type]
    target.is_default = True
    session.add(target)
    session.commit()
    return RedirectResponse(url="/settings/workspaces", status_code=303)


# ----- POST delete ---------------------------------------------------------


@router.post("/settings/workspaces/{slug}/delete", response_class=HTMLResponse)
def delete_workspace(
    slug: str,
    confirm_slug: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Delete a workspace and ALL its tasks/tags. Requires typed confirmation.

    Refuses to delete:
      - the default workspace (set another default first)
      - the only workspace (would leave the app with no landing target)
      - if `confirm_slug` doesn't match `slug` exactly
    """
    target = queries.get_workspace(session, slug)
    if target is None:
        raise HTTPException(status_code=404, detail=f"workspace '{slug}' not found")
    assert target.id is not None

    if confirm_slug.strip() != slug:
        return RedirectResponse(
            url=(
                "/settings/workspaces?error="
                + _qs(f"to delete '{slug}', type the slug exactly into the confirmation field")
            ),
            status_code=303,
        )

    if target.is_default:
        return RedirectResponse(
            url=(
                "/settings/workspaces?error="
                + _qs(f"'{slug}' is the default workspace — set another as default first")
            ),
            status_code=303,
        )

    total = len(list(session.exec(select(Workspace)).all()))
    if total <= 1:
        return RedirectResponse(
            url=(
                "/settings/workspaces?error="
                + _qs("can't delete the only workspace — add another first")
            ),
            status_code=303,
        )

    # Cascade delete: task_tag rows first (FK onto task), then tasks, then tags,
    # then the workspace itself. We don't rely on SQLite's FK ON DELETE CASCADE
    # because PRAGMA foreign_keys=ON isn't currently enforced app-wide.
    task_ids = list(
        session.exec(select(Task.id).where(Task.workspace_id == target.id)).all()
    )
    if task_ids:
        session.exec(delete(TaskTag).where(TaskTag.task_id.in_(task_ids)))  # type: ignore[arg-type, attr-defined]
    session.exec(delete(Task).where(Task.workspace_id == target.id))  # type: ignore[arg-type]
    session.exec(delete(Tag).where(Tag.workspace_id == target.id))  # type: ignore[arg-type]
    session.delete(target)
    session.commit()
    return RedirectResponse(url="/settings/workspaces", status_code=303)
