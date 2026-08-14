from __future__ import annotations

"""Curses bootstrap + the main loop that wires row building, drawing, key
handling, the audit/explain jobs, and live polling together. The curses-coupled,
value-returning handlers (picker, pager/editor, help) live here, calling their
modules directly — exactly as the old ``run_tabs`` loop did (§5.7)."""

import glob
import os
import time

from ..glyphs import glyph
from ..detail import item_detail_text
from ..diffs import is_file_edit
from ..sessions import (LIVE_MINUTES_DEFAULT, MAX_SESSIONS_DEFAULT, Session)
from ..subagents import refresh_subtree, subtree_quiet
from ..persist import rehydrate
from . import draw as D
from .controller import (AppState, Controller, Effect, MouseFlags, _is_audit_row,
                         poll_interval, remember_owner)
from .external import _copy_clipboard, open_editor, open_pager
from .help import show_help
from .jobs import AuditJob, ExplainJob
from .keys import KeySet
from .palette import Palette
from .picker import _picker_loop
from .rows import RowBuilder
from .screen import CursesScreen
from .tabstate import Tab, Toast

DONE_DEBOUNCE = 2.0              # seconds a file must be mtime-idle to count as "done"


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def _baseline_mtimes(paths):
    base = {}
    for p in glob.glob(paths.projects_glob):
        base[os.path.splitext(os.path.basename(p))[0]] = _mtime(p)
    return base


def run_tabs(initial_session, caps, paths, settings, judge, follow=True,
             live_minutes=LIVE_MINUTES_DEFAULT, max_sessions=MAX_SESSIONS_DEFAULT):
    import curses

    interval = settings.interval

    def _loop(stdscr):
        curses.curs_set(0)
        try:
            curses.start_color()
            curses.use_default_colors()
        except Exception:
            pass
        pal = Palette(caps)
        if caps.mouse:
            try:
                curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            except Exception:
                pass

        screen = CursesScreen(stdscr)
        keys = KeySet(curses)
        rb = RowBuilder(caps)
        ctrl = Controller(caps)
        audit_job = AuditJob(judge, settings, paths)
        explain_job = ExplainJob(judge, settings, paths)

        def G(k):
            return glyph(k, caps)

        # ---- state --------------------------------------------------------- #
        state = AppState([Tab(initial_session, follow)], active=0,
                         auto=settings.auto_audit)
        state.seen_mtimes = _baseline_mtimes(paths)
        rehydrate(paths, settings, state.tabs[0])   # restore cached results (§6.1)
        state.last_key_time = time.time()

        def yank(text):
            method = _copy_clipboard(text, caps)
            return Toast(f"{G('live')} yanked ({method})", "ok")

        def open_active_tabs():
            opened = 0
            open_ids = {t.session.session_id for t in state.tabs}
            recently_typed = (time.time() - state.last_key_time) < 5.0
            for p in sorted(glob.glob(paths.projects_glob), key=_mtime):
                sid = os.path.splitext(os.path.basename(p))[0]
                m = _mtime(p)
                prev = state.seen_mtimes.get(sid)
                if prev is not None and m <= prev:
                    continue
                state.seen_mtimes[sid] = m
                if sid in open_ids or sid in state.dismissed:
                    continue
                try:
                    s = Session(p).read_meta_fast()
                except OSError:
                    continue
                nt = Tab(s, follow)
                rehydrate(paths, settings, nt)      # restore cached results (§6.1)
                state.tabs.append(nt)
                open_ids.add(sid)
                opened += 1
                if not recently_typed:
                    state.active = len(state.tabs) - 1  # focus-steal only when idle
                else:
                    state.tabs[-1].unread += 1
            return opened

        stdscr.timeout(int(interval * 1000))

        while True:
            if audit_job.status == "done":
                out = audit_job.consume_done(caps)
                if out.get("beep"):
                    curses.beep()
                if out.get("toast") is not None:
                    state.toast = out["toast"]

            if explain_job.status == "done":
                out = explain_job.consume_done(caps, state.tabs)
                if out.get("toast") is not None:
                    state.toast = out["toast"]

            if not state.tabs:
                return
            tab = state.tabs[state.active]
            tab.unread = 0
            h, w = stdscr.getmaxyx()

            if w < 40 or h < 8:
                D.draw_mini(screen, pal, caps, state.tabs, state.active, w, h)
                ch = stdscr.getch()
                if ch in (ord("q"), 3):
                    return
                continue

            body_h = max(1, h - 3)
            now = time.time()
            rows = rb.build_rows(tab, w - 1, now)
            last_row = max(0, len(rows) - 1)

            if tab.following and tab.stick:
                tab.cur = last_row
            tab.cur = max(0, min(tab.cur, last_row)) if rows else 0
            if tab.cur < tab.top:
                tab.top = tab.cur
            elif tab.cur >= tab.top + body_h:
                tab.top = tab.cur - body_h + 1
            if tab.following and tab.stick:
                tab.top = max(0, len(rows) - body_h)

            stdscr.erase()
            off_ref = [state.tabstrip_off]
            D.draw_tabstrip(screen, pal, caps, state.tabs, state.active, off_ref)
            state.tabstrip_off = off_ref[0]
            D.draw_header(screen, pal, caps, tab, w, audit_job, state.auto, now)
            for row_i in range(body_h):
                ri = tab.top + row_i
                if ri >= len(rows):
                    break
                D.draw_row(screen, pal, caps, 2 + row_i, rows[ri], w - 1, ri == tab.cur)
            D.draw_scrollbar(screen, pal, caps, rows, w, body_h, tab.top)
            D.draw_newchip(screen, pal, caps, tab, rows, w, h, body_h)
            D.draw_footer(screen, pal, caps, tab, rows, w, h, audit_job,
                          [state.toast], now)
            stdscr.refresh()

            # adaptive tick
            stdscr.timeout(max(50, int(poll_interval(tab, interval, time.time()) * 1000)))
            ch = stdscr.getch()
            if ch != -1:
                state.last_key_time = time.time()

            # ---- idle tick ----
            if ch == -1:
                prev_n = len(tab.items)
                if open_active_tabs():
                    continue
                if tab.following:
                    if os.path.exists(tab.session.path):
                        m = _mtime(tab.session.path)
                        if m != tab.last_mtime:
                            tab.reload()
                    refresh_subtree(tab.items)
                    grew = len(tab.items) - prev_n
                    if grew > 0 and not tab.stick:
                        tab.new_since_release += grew
                # mark dirty / auto-fire
                if tab.following and audit_job.status != "running":
                    now2 = time.time()
                    since = now2 - tab.last_mtime
                    idle_ok = since >= DONE_DEBOUNCE
                    live_ok = since <= live_minutes * 60
                    if (live_ok and tab.stream.is_turn_complete(idle_ok)
                            and subtree_quiet(tab.items)):
                        sig = (len(tab.items), tab.last_mtime)
                        if sig != tab.audit_signature:
                            if state.auto:
                                state.toast = audit_job.start(tab, caps)
                            tab.audit_dirty = True
                elif audit_job.status == "running":
                    # a turn completing during a run marks the tab dirty
                    if tab.stream.is_turn_complete(True) and subtree_quiet(tab.items):
                        sig = (len(tab.items), tab.last_mtime)
                        if sig != tab.audit_signature and audit_job.tab is tab:
                            tab.audit_dirty = True
                continue

            # ---- search input mode ----
            if tab.search_active:
                ctrl.handle_search_key(tab, rows, ch, keys)
                continue

            remember_owner(tab, rows)

            # ---- mouse ----
            if ch == keys.MOUSE:
                try:
                    _id, mx, my, _mz, bstate = curses.getmouse()
                except curses.error:
                    bstate = 0
                    mx = my = 0
                _wheel_down = getattr(curses, "BUTTON5_PRESSED",
                                      curses.REPORT_MOUSE_POSITION)
                flags = MouseFlags(
                    middle=bool(bstate & curses.BUTTON2_PRESSED),
                    wheel_up=bool(bstate & getattr(curses, "BUTTON4_PRESSED", 0)),
                    wheel_down=bool(bstate & _wheel_down),
                    press=bool(bstate & curses.BUTTON1_PRESSED),
                    double=bool(bstate & curses.BUTTON1_DOUBLE_CLICKED))
                eff = ctrl.handle_mouse(state, tab, rows, mx, my, h, w, flags, last_row)
                if eff == Effect.QUIT:
                    return
                continue

            # ---- curses-coupled / value-returning keys (stay in tui) ----
            if ch == ord("h"):
                show_help(screen, pal, caps)
                stdscr.timeout(int(interval * 1000))
                continue
            if ch in (ord("q"), 3):
                return
            if ch == 12:                              # Ctrl-L
                stdscr.clearok(True)
                continue
            if ch == ord("l"):
                sel = _picker_loop(stdscr, caps, pal, paths, live_minutes, max_sessions)
                stdscr.timeout(int(interval * 1000))
                if sel is not None:
                    state.dismissed.discard(sel.session_id)
                    state.seen_mtimes[sel.session_id] = _mtime(sel.path)
                    existing = next((i for i, t in enumerate(state.tabs)
                                     if t.session.session_id == sel.session_id), None)
                    if existing is not None:
                        state.active = existing
                        state.tabs[state.active].reload()
                    else:
                        state.tabs.append(Tab(sel, follow))
                        state.active = len(state.tabs) - 1
                continue
            if ch == ord("a"):
                state.toast = audit_job.start(tab, caps)
                continue
            if ch == ord("?"):
                if rows:
                    row = rows[tab.cur]
                    it = row.owner
                    if _is_audit_row(row):
                        state.toast = Toast("nothing to explain here", "fg.dim")
                    else:
                        state.toast = explain_job.start(tab, it, caps)
                continue
            if ch == ord("x"):
                # `x` is the catch-all cancel — fire whichever AI action is running.
                if audit_job.status == "running" and audit_job.cancel:
                    audit_job.cancel.set()
                if explain_job.status == "running" and explain_job.cancel:
                    explain_job.cancel.set()
                continue
            if ch == ord("y"):
                if rows:
                    it = rows[tab.cur].owner
                    text = it.arg or it.text or it.tool or ""
                    state.toast = yank(text)
                continue
            if ch == ord("Y"):
                if rows:
                    it = rows[tab.cur].owner
                    blocks = item_detail_text(it, tab.session.cwd)
                    text = "\n\n".join(f"== {l} ==\n{t}" for l, t in blocks)
                    state.toast = yank(text)
                continue
            if ch == ord("o"):
                if rows:
                    open_pager(stdscr, curses, rows[tab.cur].owner, tab.session.cwd)
                    stdscr.timeout(int(interval * 1000))
                continue
            if ch == ord("O"):
                if rows:
                    it = rows[tab.cur].owner
                    if is_file_edit(it) or it.category == "read":
                        r = open_editor(stdscr, curses, it)
                        if r:
                            state.toast = r
                        stdscr.timeout(int(interval * 1000))
                continue

            # ---- everything else: pure state transitions (controller) ----
            handled, eff = ctrl.handle_key(ch, tab, rows, state, body_h, last_row, keys)
            if eff == Effect.QUIT:
                return

    return curses.wrapper(_loop)


def _run_empty_then_tabs(caps, paths, settings, judge):
    """No sessions — show the centered empty card, keep polling; the first
    session to appear opens as a tab."""
    import curses
    from ..sessions import discover_sessions

    def _loop(stdscr):
        curses.curs_set(0)
        try:
            curses.start_color()
            curses.use_default_colors()
        except Exception:
            pass
        pal = Palette(caps)
        screen = CursesScreen(stdscr)
        stdscr.timeout(2000)
        while True:
            D.draw_empty_card(screen, pal, caps)
            ch = stdscr.getch()
            if ch in (ord("q"), 3, 27):
                return None
            sessions = discover_sessions(paths, MAX_SESSIONS_DEFAULT, fast=True)
            if sessions:
                return sessions[0]

    sel = curses.wrapper(_loop)
    if sel is not None:
        sel.read_meta()
        run_tabs(sel, caps, paths, settings, judge, follow=True,
                 live_minutes=LIVE_MINUTES_DEFAULT, max_sessions=MAX_SESSIONS_DEFAULT)
