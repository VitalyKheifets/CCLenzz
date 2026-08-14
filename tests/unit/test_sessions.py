"""Unit tests for cclenzz.sessions — discovery, metadata, liveness."""

import os
import shutil

import pytest

from cclenzz.paths import AppPaths
from cclenzz.sessions import (
    LIVE_MINUTES_DEFAULT,
    MAX_SESSIONS_DEFAULT,
    Session,
    discover_sessions,
    is_live,
)

from helpers.jsonl import fixture_path


def test_defaults():
    assert LIVE_MINUTES_DEFAULT == 5
    assert MAX_SESSIONS_DEFAULT == 40


def _make_projects(tmp_path):
    """Create a projects tree with three session files at distinct mtimes.
    Returns (AppPaths, {name: path})."""
    proj = os.path.join(str(tmp_path), "projects", "-home-u-proj")
    os.makedirs(proj, exist_ok=True)
    src = fixture_path("basic.jsonl")
    paths = {}
    # oldest -> newest
    for i, name in enumerate(["old", "mid", "new"]):
        dst = os.path.join(proj, f"{name}.jsonl")
        shutil.copy(src, dst)
        mtime = 1_000_000 + i * 100
        os.utime(dst, (mtime, mtime))
        paths[name] = dst
    glob = os.path.join(str(tmp_path), "projects", "*", "*.jsonl")
    return AppPaths(state_root=str(tmp_path), projects_glob=glob), paths


def test_discover_sorted_by_mtime_desc(tmp_path):
    app, _paths = _make_projects(tmp_path)
    sessions = discover_sessions(app, MAX_SESSIONS_DEFAULT)
    ids = [s.session_id for s in sessions]
    assert ids == ["new", "mid", "old"]


def test_discover_respects_max_sessions(tmp_path):
    app, _paths = _make_projects(tmp_path)
    sessions = discover_sessions(app, 2)
    assert len(sessions) == 2
    assert [s.session_id for s in sessions] == ["new", "mid"]


def test_discover_reads_meta(tmp_path):
    app, _paths = _make_projects(tmp_path)
    sessions = discover_sessions(app, MAX_SESSIONS_DEFAULT)
    for s in sessions:
        assert s.meta_loaded is True
        assert isinstance(s.item_count, int)


def test_discover_fast_drops_count(tmp_path):
    app, _paths = _make_projects(tmp_path)
    sessions = discover_sessions(app, MAX_SESSIONS_DEFAULT, fast=True)
    for s in sessions:
        assert s.meta_loaded is True
        assert s.item_count is None


def test_read_meta_title_precedence(tmp_path):
    # titles.jsonl carries custom > ai > last > first — custom wins.
    p = os.path.join(str(tmp_path), "titles.jsonl")
    shutil.copy(fixture_path("titles.jsonl"), p)
    s = Session(p)
    s.read_meta()
    assert s.title == "My Custom Title"
    assert isinstance(s.item_count, int)


def test_read_meta_fast_same_title(tmp_path):
    p = os.path.join(str(tmp_path), "titles.jsonl")
    shutil.copy(fixture_path("titles.jsonl"), p)
    s = Session(p)
    s.read_meta_fast()
    assert s.title == "My Custom Title"
    assert s.item_count is None


def test_is_live_window_math(tmp_path):
    p = os.path.join(str(tmp_path), "s.jsonl")
    shutil.copy(fixture_path("basic.jsonl"), p)
    mtime = 1_000_000
    os.utime(p, (mtime, mtime))
    s = Session(p)
    live_minutes = 5
    # just inside the window
    assert is_live(s, mtime + live_minutes * 60, live_minutes) is True
    # exactly at the boundary is still live (<=)
    assert is_live(s, mtime + live_minutes * 60, live_minutes) is True
    # just outside
    assert is_live(s, mtime + live_minutes * 60 + 1, live_minutes) is False
