"""Workspace UI metadata — accent + derived background/foreground colors.

Workspaces store a single accent hex (`workspace.color` in DB). The web UI
needs three related colors per workspace:

  - color_hex: the accent itself, used for borders, the active tab underline,
    today-card left edge, "★ today" indicator.
  - color_bg:  a light tint, used as the background of the badge pill.
  - color_fg:  a dark shade, used as the text color on the badge pill.

Rather than store all three in the DB (and require the user to pick three
matching colors), we derive `color_bg` and `color_fg` from `color_hex` via
HSL transforms. The result mimics Tailwind's 100/900 stops for any hue.

`DEFAULT_PALETTE` is a small list of pleasing accent hexes used by the
`kairo-web add-workspace` CLI as the default color for newly created
workspaces (cycled by current count).
"""

from __future__ import annotations

from typing import Mapping

# Pinned to specific Tailwind 700-stops for visual consistency.
DEFAULT_PALETTE: list[str] = [
    "#BE185D",  # pink-700
    "#0F766E",  # teal-700
    "#4338CA",  # indigo-700
    "#9333EA",  # purple-600
    "#0891B2",  # cyan-600
    "#CA8A04",  # yellow-600
    "#16A34A",  # green-600
    "#DC2626",  # red-600
]


def color_for_index(index: int) -> str:
    """Pick a palette color by index (wraps). Used when the user adds a workspace
    without specifying a color — the slot is determined by current workspace count."""
    return DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)]


# ----- Color math (hex ↔ HSL) ----------------------------------------------


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    rf, gf, bf = r / 255, g / 255, b / 255
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == rf:
        h = (gf - bf) / d + (6 if gf < bf else 0)
    elif mx == gf:
        h = (bf - rf) / d + 2
    else:
        h = (rf - gf) / d + 4
    return h / 6, s, l


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    if s == 0:
        v = round(l * 255)
        return v, v, v

    def hue2rgb(p: float, q: float, t: float) -> float:
        t %= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    r = hue2rgb(p, q, h + 1 / 3)
    g = hue2rgb(p, q, h)
    b = hue2rgb(p, q, h - 1 / 3)
    return round(r * 255), round(g * 255), round(b * 255)


def derive_bg_fg(color_hex: str) -> tuple[str, str]:
    """Given an accent hex, return (bg, fg) — a light tint and a dark shade.

    The light bg has high lightness (≈0.92) and slightly capped saturation so
    it never gets gaudy. The dark fg has low lightness (≈0.20) and floored
    saturation so contrast against the bg is always strong.
    """
    h, s, _ = _rgb_to_hsl(*_hex_to_rgb(color_hex))
    bg = _rgb_to_hex(*_hsl_to_rgb(h, min(s, 0.5), 0.92))
    fg = _rgb_to_hex(*_hsl_to_rgb(h, max(s, 0.4), 0.20))
    return bg, fg


# ----- Public lookup -------------------------------------------------------

# Type alias: anything with a `.color` (str) and `.slug` (str) attribute.
class _HasColor:  # protocol-shaped, but kept minimal so SQLModel rows fit
    color: str
    slug: str


def meta_for_workspace(workspace: _HasColor) -> Mapping[str, str]:
    """Build the (color_hex, color_bg, color_fg) trio used by templates.

    Reads `workspace.color` (the accent) from the DB row and derives the
    other two via HSL math. Always returns a dict — never None.
    """
    accent = workspace.color or DEFAULT_PALETTE[0]
    bg, fg = derive_bg_fg(accent)
    return {
        "color_hex": accent,
        "color_bg": bg,
        "color_fg": fg,
    }


# Legacy compat: a few code paths still call meta_for(slug). They get a
# slate-toned fallback so the UI doesn't crash if a Workspace row is missing.
_FALLBACK = {
    "color_hex": "#475569",  # slate-600
    "color_bg": "#E2E8F0",   # slate-200
    "color_fg": "#1E293B",   # slate-800
}


def meta_for(slug: str) -> Mapping[str, str]:  # pragma: no cover — compat shim
    """Deprecated. Prefer `meta_for_workspace(workspace)`."""
    return _FALLBACK
