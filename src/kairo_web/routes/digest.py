"""Email-digest one-click action routes.

Stubs — full implementation lands in milestone 5.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/digest", tags=["digest"])


@router.get("/act/{token}")
def act(token: str) -> dict:
    # TODO(milestone-5): consume token, perform action, render confirmation page.
    return {"ok": False, "todo": True, "token": token}
