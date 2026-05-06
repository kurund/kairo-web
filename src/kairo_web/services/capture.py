"""Capture-bar parser.

See TECH_SPEC.md §6 for the full grammar. Summary:

  - `#word`   → tag (lowercase)
  - `@word`   → project (last `@token` wins; spaces escaped with `_`)
  - `~Nh` / `~N.Nh` / `~Nm` → estimate (always normalized to hours, float)
  - Doubled marker (`##`, `@@`, `~~`) is a literal `#`/`@`/`~` in the title
  - Everything else is the title (whitespace-trimmed)
  - Marker order is irrelevant
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A "word" for tags/projects: letters, digits, hyphen, underscore.
_WORD_RE = re.compile(r"[A-Za-z0-9_\-]+")
_ESTIMATE_RE = re.compile(r"^(\d+(?:\.\d+)?)([hm])$", re.IGNORECASE)


@dataclass
class ParsedCapture:
    title: str
    tags: list[str] = field(default_factory=list)
    project: str | None = None
    estimate_hours: float | None = None


def parse_capture(text: str) -> ParsedCapture:
    """Parse a capture-bar string into structured fields.

    Tokenization is whitespace-based, with escape support for doubled markers.
    Last-write-wins for project and estimate; tags accumulate (deduped, order
    preserved).
    """
    if not text or not text.strip():
        return ParsedCapture(title="")

    tags: list[str] = []
    project: str | None = None
    estimate_hours: float | None = None
    title_parts: list[str] = []

    for token in text.split():
        # Escape: doubled marker becomes the literal marker plus the rest.
        if token.startswith("##"):
            title_parts.append("#" + token[2:])
            continue
        if token.startswith("@@"):
            title_parts.append("@" + token[2:])
            continue
        if token.startswith("~~"):
            title_parts.append("~" + token[2:])
            continue

        if token.startswith("#") and len(token) > 1:
            tag = token[1:].lower()
            if _WORD_RE.fullmatch(tag) and tag not in tags:
                tags.append(tag)
            continue

        if token.startswith("@") and len(token) > 1:
            candidate = token[1:].replace("_", " ")
            if candidate:
                project = candidate
            continue

        if token.startswith("~") and len(token) > 1:
            m = _ESTIMATE_RE.match(token[1:])
            if m:
                value = float(m.group(1))
                unit = m.group(2).lower()
                estimate_hours = value if unit == "h" else value / 60.0
            continue

        title_parts.append(token)

    title = " ".join(title_parts).strip()
    return ParsedCapture(
        title=title,
        tags=tags,
        project=project,
        estimate_hours=estimate_hours,
    )
