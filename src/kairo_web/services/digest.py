"""Morning + evening email digest builders.

Stubs — implementation lands in milestone 5. See TECH_SPEC §8.
"""

from __future__ import annotations

from sqlmodel import Session


def build_morning_digest(session: Session, workspace_id: int) -> dict:
    """Produce the context dict for the morning email template."""
    raise NotImplementedError


def build_evening_digest(session: Session, workspace_id: int) -> dict:
    """Produce the context dict for the evening review email template."""
    raise NotImplementedError
