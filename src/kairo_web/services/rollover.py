"""Sunday-night rollover service.

Stub — implementation lands in milestone 4. See TECH_SPEC §7.
"""

from __future__ import annotations

from sqlmodel import Session


def rollover_workspace(session: Session, workspace_id: int) -> int:
    """Move open tasks from the closing week into the next week. Returns count moved."""
    # TODO(milestone-4): real implementation.
    raise NotImplementedError
