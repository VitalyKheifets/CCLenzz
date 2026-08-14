"""Real-TUI smoke tests through a pty (§11.9). Substring assertions only; every
test finishes with the read-only .claude-tree hash guard."""

import pytest

from helpers.ptytui import PtySession


def test_launch_render_quit(sandbox):
    sb = sandbox()
    sb.add_session("basic.jsonl")
    before = sb.claude_hash()
    p = PtySession(sb.env())
    try:
        assert p.read_until("read the config", timeout=6)
        p.send("q")
        assert p.wait(timeout=6) == 0
    finally:
        p.close()
    assert sb.claude_hash() == before


def test_help_overlay(sandbox):
    sb = sandbox()
    sb.add_session("basic.jsonl")
    p = PtySession(sb.env())
    try:
        assert p.read_until("read the config", timeout=6)
        p.send("h")
        assert p.read_until("cclenzz — keys", timeout=6)
        p.send(" ")   # dismiss help
        p.send("q")
        assert p.wait(timeout=6) == 0
    finally:
        p.close()


def test_search_footer_counter(sandbox):
    sb = sandbox()
    sb.add_session("basic.jsonl")
    p = PtySession(sb.env())
    try:
        assert p.read_until("read the config", timeout=6)
        p.send("/config\r")
        assert p.read_until("1/", timeout=6)  # match counter appears in footer
        p.send("q")
        assert p.wait(timeout=6) == 0
    finally:
        p.close()


def test_empty_card_literal_path(sandbox):
    sb = sandbox()  # no session added
    before = sb.claude_hash()
    p = PtySession(sb.env())
    try:
        # the card is a hardcoded string and does NOT reflect projects_glob
        assert p.read_until("~/.claude/projects/", timeout=6)
        p.send("q")
        assert p.wait(timeout=6) == 0
    finally:
        p.close()
    assert sb.claude_hash() == before
