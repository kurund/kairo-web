"""Workspace switching routes (HTMX endpoints).

Stub — implementation lands in milestone 1.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/workspace", tags=["workspaces"])


@router.post("/switch/{slug}")
def switch_workspace(slug: str) -> dict:
    # TODO(milestone-1): set session.active_workspace, return HX-Redirect header.
    return {"ok": False, "todo": True, "slug": slug}
