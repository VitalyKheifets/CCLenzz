from __future__ import annotations

"""Session picker v2 (§6.3) — fuzzy filter + preview."""

import json
import os
import time

from ..ansi import RGB_
from ..classify import classify_tool
from ..glyphs import cli_glyph, glyph, sep, u
from ..model import extract_user_text
from ..sessions import discover_sessions, is_live
from ..textutil import clip_cells, fmt_clock, fmt_idle, trunc_end


def _fuzzy(needle, hay):
    """Subsequence match; return (matched, tightness) — lower tightness = tighter."""
    if not needle:
        return True, 0
    hay = hay.lower()
    pos = 0
    first = None
    last = None
    for c in needle.lower():
        idx = hay.find(c, pos)
        if idx < 0:
            return False, 0
        if first is None:
            first = idx
        last = idx
        pos = idx + 1
    return True, (last - first)


def _picker_loop(stdscr, caps, pal, paths, live_minutes, max_sessions):
    import curses
    curses.curs_set(0)
    stdscr.timeout(-1)
    aw = caps.ambiwidth
    sessions = discover_sessions(paths, max_sessions, fast=True)
    query = ""
    idx = 0
    top = 0

    def put(y, x, text, attr, maxx=None):
        h, w = stdscr.getmaxyx()
        if maxx is None:
            maxx = w
        clipped, _ = clip_cells(text, maxx - x, aw)
        try:
            stdscr.addstr(y, x, clipped, attr)
        except curses.error:
            pass

    def filtered():
        if not query:
            return list(enumerate(sessions))
        scored = []
        for i, s in enumerate(sessions):
            ok, tight = _fuzzy(query, (s.project or "") + " " + (s.title or ""))
            if ok:
                scored.append((tight, i, s))
        scored.sort(key=lambda t: (t[0], -sessions[t[1]].mtime))
        return [(i, s) for _t, i, s in scored]

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        now = time.time()
        title = (" Open a session   (type to filter " + sep(caps) + " " + u("↑↓", "up/dn", caps) +
                 " move " + sep(caps) + " Enter open " + sep(caps) + " r rescan " + sep(caps) + " Esc cancel)")
        put(0, 0, title.ljust(w - 1), pal.attr("accent", extra=curses.A_REVERSE))
        put(1, 0, "/" + query, pal.attr("fg"))

        view = filtered()
        idx = max(0, min(idx, len(view) - 1)) if view else 0
        rows = max(1, h - 3)
        if idx < top:
            top = idx
        elif idx >= top + rows:
            top = idx - rows + 1

        preview = (w >= 100)
        list_w = int(w * 0.55) if preview else w - 1

        for row, (real_i, s) in enumerate(view[top:top + rows]):
            y = 2 + row
            sel = (top + row == idx)
            live = is_live(s, now, live_minutes)
            dot = glyph("live", caps) if live else glyph("paused", caps)
            line = "{d} {proj:<16} {title:<32} {idle:<5} {clock}".format(
                d=dot, proj=trunc_end(s.project, 16, aw),
                title=trunc_end(s.title or "", 32, aw),
                idle=fmt_idle(s.mtime, now), clock=fmt_clock(s.mtime))
            attr = pal.attr("accent", sel=True, extra=curses.A_REVERSE) if sel else \
                pal.attr("fg" if live else "fg.dim")
            put(y, 0, line[:list_w], attr, maxx=list_w)

        if preview and view:
            _real_i, s = view[idx]
            _draw_preview(stdscr, put, pal, caps, s, list_w + 2, w - 1, h, aw)

        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_UP,):
            idx = max(0, idx - 1)
        elif ch in (curses.KEY_DOWN,):
            idx = min(len(view) - 1, idx + 1) if view else 0
        elif ch in (curses.KEY_ENTER, 10, 13):
            return view[idx][1] if view else None
        elif ch == ord("r"):
            sessions = discover_sessions(paths, max_sessions, fast=True)
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            query = query[:-1]
            idx = 0
        elif ch == 27:
            return None
        elif 32 <= ch < 127:
            query += chr(ch)
            idx = 0


def _draw_preview(stdscr, put, pal, caps, session, x0, x1, h, aw):
    import curses  # noqa: F401  (kept for parity; put handles curses.error)
    put(2, x0, "last topics:", pal.attr("fg.dim"))
    try:
        with open(session.path, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            fh.seek(max(0, size - 65536))
            tail = fh.read()
    except OSError:
        return
    topics = []
    for raw in tail.split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            o = json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, json.JSONDecodeError):
            continue
        t = o.get("type")
        if t == "user":
            txt = extract_user_text(o)
            if txt:
                topics.append((glyph("prompt", caps), trunc_end(txt, x1 - x0 - 3, aw), "accent"))
        elif t == "assistant" and not o.get("isMeta"):
            for b in (o.get("message") or {}).get("content", []) or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    cat, tool, arg, _ = classify_tool(b.get("name"), b.get("input"),
                                                      session.cwd)
                    topics.append((cli_glyph(cat, caps),
                                   trunc_end(f"{tool} {arg}", x1 - x0 - 3, aw),
                                   "cat." + cat if ("cat." + cat) in RGB_ else "fg"))
    for i, (g, txt, tok) in enumerate(topics[-8:]):
        y = 4 + i
        if y >= h - 1:
            break
        put(y, x0, f"{g} {txt}", pal.attr(tok))
