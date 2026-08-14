"""Live polling: appended bytes appear, and a new session auto-opens as a tab
(§11.9)."""

import os
import time

import pytest

from helpers.ptytui import PtySession

PART1 = (
    '{"type":"user","cwd":"/home/u/proj","timestamp":"2026-01-01T10:00:00.000Z",'
    '"message":{"role":"user","content":"initial prompt"}}\n'
    '{"type":"assistant","timestamp":"2026-01-01T10:00:01.000Z","message":'
    '{"role":"assistant","stop_reason":"tool_use","content":[{"type":"tool_use",'
    '"id":"g1","name":"Read","input":{"file_path":"/home/u/proj/first.py"}}]}}\n'
    '{"type":"user","timestamp":"2026-01-01T10:00:02.000Z","message":{"role":"user",'
    '"content":[{"type":"tool_result","tool_use_id":"g1","content":"ok","is_error":false}]}}\n'
    '{"type":"assistant","timestamp":"2026-01-01T10:00:03.000Z","message":'
    '{"role":"assistant","stop_reason":"end_turn","content":[{"type":"text","text":"first done"}]}}\n'
)
PART2 = (
    '{"type":"user","cwd":"/home/u/proj","timestamp":"2026-01-01T10:05:00.000Z",'
    '"message":{"role":"user","content":"second prompt"}}\n'
    '{"type":"assistant","timestamp":"2026-01-01T10:05:01.000Z","message":'
    '{"role":"assistant","stop_reason":"tool_use","content":[{"type":"tool_use",'
    '"id":"g2","name":"Bash","input":{"command":"appended_marker_cmd"}}]}}\n'
    '{"type":"user","timestamp":"2026-01-01T10:05:02.000Z","message":{"role":"user",'
    '"content":[{"type":"tool_result","tool_use_id":"g2","content":"ok","is_error":false}]}}\n'
    '{"type":"assistant","timestamp":"2026-01-01T10:05:03.000Z","message":'
    '{"role":"assistant","stop_reason":"end_turn","content":[{"type":"text","text":"second done"}]}}\n'
)


def test_appended_bytes_appear(sandbox):
    sb = sandbox()
    path = sb.write_session("bbbb2222", PART1)
    p = PtySession(sb.env())
    try:
        assert p.read_until("initial prompt", timeout=6)
        with open(path, "a") as fh:
            fh.write(PART2)
        assert p.read_until("appended_marker_cmd", timeout=6)
        p.send("q")
        assert p.wait(timeout=6) == 0
    finally:
        p.close()


def test_new_session_auto_opens_tab(sandbox):
    sb = sandbox()
    sb.write_session("cccc3333", PART1)
    p = PtySession(sb.env())
    try:
        assert p.read_until("initial prompt", timeout=6)
        # A brand-new session appears while cclenzz runs. Within 5 s of the last
        # keypress cclenzz opens it as an UNREAD tab (no focus-steal), so the
        # tab strip gains a second tab with an unread badge.
        time.sleep(0.3)
        sb.write_session("dddd4444", PART2.replace("second prompt", "brand new session"))
        assert p.read_until("(+1)", timeout=6)   # unread badge for the auto-opened tab
        p.send("q")
        assert p.wait(timeout=6) == 0
    finally:
        p.close()
