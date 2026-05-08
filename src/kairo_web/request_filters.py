"""Extract the active week-view filter state (tag, project) from a request.

Filters live in the URL querystring (`?tag=urgent&project=auth-rewrite`) on the
week page. HTMX mutation endpoints don't see those query params directly, but
HTMX sends an `HX-Current-URL` header with the page the user is viewing — we
parse the filter out of that so mutations preserve the active filter automatically.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, urlparse

from fastapi import Request


def extract_week_filters(request: Request) -> tuple[Optional[str], Optional[str]]:
    """Return (filter_tag, filter_project). Either or both may be None."""
    hx_url = request.headers.get("HX-Current-URL")
    if hx_url:
        params = parse_qs(urlparse(hx_url).query)
        return (
            _first_or_none(params.get("tag")),
            _first_or_none(params.get("project")),
        )
    return (
        request.query_params.get("tag") or None,
        request.query_params.get("project") or None,
    )


def _first_or_none(values: Optional[list[str]]) -> Optional[str]:
    if not values:
        return None
    v = values[0].strip()
    return v or None


def filter_query_string(tag: Optional[str], project: Optional[str]) -> str:
    """Build a 'tag=urgent&project=auth-rewrite' fragment for use in URLs.

    Returns an empty string when no filter is active. Used to build clickable
    chip URLs (so each chip's link preserves the *other* filter).
    """
    from urllib.parse import urlencode
    pairs = []
    if tag:
        pairs.append(("tag", tag))
    if project:
        pairs.append(("project", project))
    return urlencode(pairs) if pairs else ""
