"""Workspace UI metadata (accent colors, badge backgrounds).

Source-of-truth for visual styling per workspace, keyed by slug. Mirrors the
default workspaces seeded by `kairo-web init`.

Hex values are pinned to specific Tailwind ramps so the UI stays consistent
even though the values are inlined as `style="color: #..."` rather than class
names — Tailwind's Play CDN can't always pick up dynamic class names.
"""

from __future__ import annotations

WORKSPACE_META: dict[str, dict[str, object]] = {
    "fulltime": {
        "color_hex": "#0F766E",   # teal-700
        "color_bg": "#CCFBF1",    # teal-100
        "color_fg": "#134E4A",    # teal-900
    },
    "consulting": {
        "color_hex": "#4338CA",   # indigo-700
        "color_bg": "#E0E7FF",    # indigo-100
        "color_fg": "#312E81",    # indigo-900
    },
    "personal": {
        "color_hex": "#BE185D",   # pink-700
        "color_bg": "#FCE7F3",    # pink-100
        "color_fg": "#831843",    # pink-900
    },
}

_FALLBACK = {
    "color_hex": "#475569",       # slate-600
    "color_bg": "#E2E8F0",        # slate-200
    "color_fg": "#1E293B",        # slate-800
}


def meta_for(slug: str) -> dict[str, object]:
    return WORKSPACE_META.get(slug, _FALLBACK)
