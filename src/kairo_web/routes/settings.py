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
from sqlmodel import Session, select

from kairo_web.db import get_session
from kairo_web.models import Workspace
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
