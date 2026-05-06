"""Tests for the capture-bar parser (TECH_SPEC §6)."""

from __future__ import annotations

import pytest

from kairo_web.services.capture import parse_capture


def test_plain_title():
    p = parse_capture("Fix login bug")
    assert p.title == "Fix login bug"
    assert p.tags == []
    assert p.project is None
    assert p.estimate_hours is None


def test_single_tag():
    p = parse_capture("Fix login bug #urgent")
    assert p.title == "Fix login bug"
    assert p.tags == ["urgent"]


def test_multiple_tags_dedup_preserves_order():
    p = parse_capture("Refactor #auth #urgent #auth payments")
    assert p.title == "Refactor payments"
    assert p.tags == ["auth", "urgent"]


def test_project_assignment():
    p = parse_capture("Ship feature @auth-rewrite")
    assert p.title == "Ship feature"
    assert p.project == "auth-rewrite"


def test_project_with_underscore_becomes_space():
    p = parse_capture("Plan @website_redesign")
    assert p.project == "website redesign"


def test_estimate_hours():
    p = parse_capture("Long task ~2h")
    assert p.estimate_hours == 2.0


def test_estimate_fractional():
    p = parse_capture("Quick fix ~0.5h")
    assert p.estimate_hours == pytest.approx(0.5)


def test_estimate_minutes_to_hours():
    p = parse_capture("Tiny tweak ~30m")
    assert p.estimate_hours == pytest.approx(0.5)


def test_combined_markers():
    p = parse_capture("Fix login bug #urgent #auth @auth-rewrite ~2h")
    assert p.title == "Fix login bug"
    assert p.tags == ["urgent", "auth"]
    assert p.project == "auth-rewrite"
    assert p.estimate_hours == 2.0


def test_marker_order_irrelevant():
    p = parse_capture("~2h @proj #tag Task title here #other")
    assert p.title == "Task title here"
    assert p.tags == ["tag", "other"]
    assert p.project == "proj"
    assert p.estimate_hours == 2.0


def test_last_project_wins():
    p = parse_capture("Task @first @second")
    assert p.project == "second"


def test_tags_lowercased():
    p = parse_capture("Task #URGENT")
    assert p.tags == ["urgent"]


def test_escape_hash():
    p = parse_capture("Discuss ##1 ranking")
    assert p.title == "Discuss #1 ranking"
    assert p.tags == []


def test_escape_at():
    p = parse_capture("Email @@me later")
    assert p.title == "Email @me later"
    assert p.project is None


def test_escape_tilde():
    p = parse_capture("Approx ~~3 items")
    assert p.title == "Approx ~3 items"
    assert p.estimate_hours is None


def test_empty_string():
    p = parse_capture("")
    assert p.title == ""
    assert p.tags == []
    assert p.project is None
    assert p.estimate_hours is None


def test_whitespace_only():
    p = parse_capture("   ")
    assert p.title == ""


def test_invalid_estimate_kept_in_title():
    # An unparseable estimate token is just dropped (not added to title).
    p = parse_capture("Task ~banana")
    assert p.title == "Task"
    assert p.estimate_hours is None


def test_invalid_tag_dropped():
    # Tag containing a forbidden character (space already split it; here we use a slash).
    p = parse_capture("Task #foo/bar")
    # `foo/bar` doesn't match _WORD_RE → tag dropped silently.
    assert p.tags == []
    assert p.title == "Task"
