"""Filesystem paths used across the app (templates, static)."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR: Path = Path(__file__).resolve().parent
TEMPLATE_DIR: Path = PACKAGE_DIR / "templates"
STATIC_DIR: Path = PACKAGE_DIR / "static"
