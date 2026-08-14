from __future__ import annotations

"""Per-key state transitions and cursor/stick/search/mouse logic — the pure,
curses-free half of the TUI (§5.7). The controller owns only pure state
transitions; the value-returning, curses-coupled handlers (picker, pager,
editor, help, audit/explain/yank/cancel) stay in ``tui.py``. Bodies here are the
old ``run_tabs`` ``elif`` branches, moved verbatim."""

import enum
import time

from ..model import CATEGORIES
from ..subagents import is_agent_launch
from ..textutil import disp_w, trunc_end
from .tabstate import Toast


class Effect(enum.Enum):
    NONE = 0
    QUIT = 1
    REPAINT = 2
    BEEP = 3


class AppState:
    """Cross-tab loop state (§5.7): the fields the old ``run_tabs`` kept as
    ``nonlocal`` / list-cell locals."""

    __slots__ = ("tabs", "active", "dismissed", "seen_mtimes", "toast", "auto",
                 "tabstrip_off", "last_key_time")

    def __init__(self, tabs, active=0, auto=False):
        self.tabs = tabs
        self.active = active
        self.dismissed = set()
        self.seen_mtimes = {}
        self.toast = None
        self.auto = auto
        self.tabstrip_off = 0
        self.last_key_time = time.time()


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def _is_audit_row(row):
    # The badge ("aligned … · conf …") and its derivation lines all belong to
    # a prompt; they collapse on their own, independent of the whole turn.
    return row.kind == "audit" or (
        row.kind == "sub" and row.owner is not None
        and row.owner.kind == "prompt")


def _toggle_expand(tab, it):
    if it.kind == "prompt":
        tab.folded.symmetric_difference_update({id(it)})
    else:
        tab.expanded.symmetric_difference_update({id(it)})


def _next_prompt(rows, cur, direction):
    rng = range(cur + 1, len(rows)) if direction > 0 else range(cur - 1, -1, -1)
    for i in rng:
        if rows[i].kind == "turn":
            return i
    return cur


def _parent_row(rows, cur):
    for i in range(cur - 1, -1, -1):
        if rows[i].kind in ("turn", "tool"):
            return i
    return None


def head_row_of(rows, item):
    for i, r in enumerate(rows):
        if r.owner is item and r.kind in ("tool", "turn"):
            return i
    return None


def remember_owner(tab, rows):
    if rows and 0 <= tab.cur < len(rows):
        tab.owner_at_cursor = rows[tab.cur].owner


def restore_cursor(tab, rows):
    if not rows:
        tab.cur = 0
        return
    owner = tab.owner_at_cursor
    if owner is not None:
        for i, r in enumerate(rows):
            if r.owner is owner:
                tab.cur = i
                return
        # find nearest previous surviving item by original order
    tab.cur = max(0, min(tab.cur, len(rows) - 1))


def recompute_matches(tab, rows):
    q = tab.search.lower()
    tab.matches = [i for i, r in enumerate(rows) if q and q in r.plain.lower()]
    if tab.matches:
        after = [i for i in tab.matches if i >= tab.cur]
        tab.match_i = tab.matches.index(after[0]) if after else 0
        tab.cur = tab.matches[tab.match_i]


def _tabstrip_hit(tabs, mx, off, aw, w):
    x = 2 if off > 0 else 0
    cursor = 0
    for i, t in enumerate(tabs):
        label = f" {i + 1} {trunc_end(t.session.project, 12, aw)} "
        badge = f"(+{t.unread})" if t.unread else ""
        seg_w = disp_w(label, aw) + 2 + disp_w(badge, aw)
        if cursor + seg_w <= off:
            cursor += seg_w
            continue
        if x <= mx < x + seg_w:
            return i
        x += seg_w
        cursor += seg_w
    return None


def poll_interval(tab, interval, now):
    """Adaptive polling (§8.3)."""
    age = now - tab.last_mtime
    if age <= 5:
        return interval * 0.25
    if age <= 60:
        return interval
    return interval * 2


# --------------------------------------------------------------------------- #
# Controller
# --------------------------------------------------------------------------- #

class MouseFlags:
    __slots__ = ("middle", "wheel_up", "wheel_down", "press", "double")

    def __init__(self, middle=False, wheel_up=False, wheel_down=False,
                 press=False, double=False):
        self.middle = middle
        self.wheel_up = wheel_up
        self.wheel_down = wheel_down
        self.press = press
        self.double = double


class Controller:
    def __init__(self, caps):
        self.caps = caps

    def G(self, k):
        from ..glyphs import glyph
        return glyph(k, self.caps)

    # ---- search input mode -------------------------------------------------
    def handle_search_key(self, tab, rows, ch, keys):
        if ch in (27,):                     # Esc cancels
            tab.search_active = False
            tab.search = ""
            tab.matches = []
        elif ch in (10, 13, keys.ENTER):
            tab.search_active = False
            recompute_matches(tab, rows)
        elif ch in (keys.BACKSPACE, 127, 8):
            tab.search = tab.search[:-1]
            recompute_matches(tab, rows)
        elif 32 <= ch < 127:
            tab.search += chr(ch)
            recompute_matches(tab, rows)

    # ---- mouse -------------------------------------------------------------
    def handle_mouse(self, state, tab, rows, mx, my, h, w, flags, last_row):
        aw = self.caps.ambiwidth
        if my == 0:
            # tab click
            hit = _tabstrip_hit(state.tabs, mx, state.tabstrip_off, aw, w)
            if hit is not None:
                if flags.middle:
                    closed = state.tabs.pop(hit)
                    state.dismissed.add(closed.session.session_id)
                    if not state.tabs:
                        return Effect.QUIT
                    state.active = min(state.active, len(state.tabs) - 1)
                else:
                    state.active = hit
                    state.tabs[state.active].reload()
            return Effect.NONE
        if flags.wheel_up:
            tab.cur = max(0, tab.cur - 3)
            tab.stick = False
            return Effect.NONE
        if flags.wheel_down:
            tab.cur = min(last_row, tab.cur + 3)
            tab.stick = tab.cur >= last_row
            return Effect.NONE
        ri = tab.top + (my - 2)
        if 0 <= ri < len(rows) and 2 <= my < h - 1:
            if flags.double:
                row = rows[ri]
                it = row.owner
                if _is_audit_row(row):
                    tab.audit_folded.symmetric_difference_update({id(it)})
                elif it.kind == "prompt":
                    # cycle: full text ↔ unfolded ↔ folded
                    if id(it) in tab.expanded:
                        tab.expanded.discard(id(it))
                    elif id(it) in tab.folded:
                        tab.folded.discard(id(it))
                    else:
                        tab.expanded.add(id(it))
                else:
                    _toggle_expand(tab, it)
            elif flags.press:
                tab.cur = ri
                tab.stick = tab.cur >= last_row
        return Effect.NONE

    # ---- pure key transitions ---------------------------------------------
    def handle_key(self, ch, tab, rows, state, body_h, last_row, keys):
        """Handle the pure-state keys. Returns (handled, Effect)."""
        # Esc — dismiss, never quit
        if ch == 27:
            if tab.search:
                tab.search = ""
                tab.matches = []
            elif state.toast and state.toast.alive():
                state.toast = None
            elif tab.cat_filter or tab.errors_only:
                tab.cat_filter = None
                tab.errors_only = False
            return True, Effect.NONE

        # ---- tabs ----
        if ch in (ord("]"), 9):
            state.active = (state.active + 1) % len(state.tabs)
            state.tabs[state.active].reload()
            return True, Effect.NONE
        if ch in (ord("["), keys.BTAB):
            state.active = (state.active - 1) % len(state.tabs)
            state.tabs[state.active].reload()
            return True, Effect.NONE
        if ord("1") <= ch <= ord("9"):
            n = ch - ord("1")
            if n < len(state.tabs):
                state.active = n
                state.tabs[state.active].reload()
            return True, Effect.NONE
        if ch == ord("d"):
            closed = state.tabs.pop(state.active)
            state.dismissed.add(closed.session.session_id)
            if not state.tabs:
                return True, Effect.QUIT
            state.active = min(state.active, len(state.tabs) - 1)
            return True, Effect.NONE

        # ---- navigation ----
        if ch in (keys.UP, ord("k")):
            tab.cur = max(0, tab.cur - 1)
            tab.stick = tab.cur >= last_row
            return True, Effect.NONE
        elif ch in (keys.DOWN, ord("j")):
            tab.cur = min(last_row, tab.cur + 1)
            tab.stick = tab.cur >= last_row
            if tab.cur >= last_row:
                tab.new_since_release = 0
            return True, Effect.NONE
        elif ch == 4:                              # Ctrl-D
            tab.cur = min(last_row, tab.cur + body_h // 2)
            tab.stick = tab.cur >= last_row
            return True, Effect.NONE
        elif ch == 21:                             # Ctrl-U
            tab.cur = max(0, tab.cur - body_h // 2)
            tab.stick = False
            return True, Effect.NONE
        elif ch == keys.NPAGE:
            tab.cur = min(last_row, tab.cur + body_h)
            tab.stick = tab.cur >= last_row
            return True, Effect.NONE
        elif ch == keys.PPAGE:
            tab.cur = max(0, tab.cur - body_h)
            tab.stick = False
            return True, Effect.NONE
        elif ch in (ord("g"), keys.HOME):
            tab.cur = 0
            tab.stick = False
            return True, Effect.NONE
        elif ch in (ord("G"), keys.END):
            tab.cur = last_row
            tab.stick = True
            tab.new_since_release = 0
            return True, Effect.NONE
        elif ch == ord("}"):
            tab.cur = _next_prompt(rows, tab.cur, 1)
            tab.stick = tab.cur >= last_row
            return True, Effect.NONE
        elif ch == ord("{"):
            tab.cur = _next_prompt(rows, tab.cur, -1)
            tab.stick = False
            return True, Effect.NONE
        elif ch in (keys.ENTER, 10, 13, keys.RIGHT, ord(" ")):
            if rows:
                row = rows[tab.cur]
                it = row.owner
                # navigable cite: Enter on an audit-detail deduction row jumps
                cite = row.cite
                if cite is not None:
                    j = head_row_of(rows, cite)
                    if j is not None:
                        tab.cur = j
                        tab.stick = False
                        return True, Effect.NONE
                if _is_audit_row(row):
                    # toggle the audit derivation view on its own
                    tab.audit_folded.symmetric_difference_update({id(it)})
                elif it.kind == "prompt":
                    # progressive open: unfold the turn, then reveal the
                    # full prompt text — → always opens, never collapses.
                    if id(it) in tab.folded:
                        tab.folded.discard(id(it))
                    else:
                        tab.expanded.add(id(it))
                else:
                    _toggle_expand(tab, it)
                tab.stick = False
            return True, Effect.NONE
        elif ch == keys.LEFT:
            if rows:
                row = rows[tab.cur]
                it = row.owner
                if _is_audit_row(row):
                    # collapse just the audit derivation, keep the turn open
                    tab.audit_folded.add(id(it))
                    tab.stick = False
                elif it.kind == "prompt":
                    # progressive close: hide the full prompt text first,
                    # then fold the turn.
                    if id(it) in tab.expanded:
                        tab.expanded.discard(id(it))
                    elif id(it) not in tab.folded:
                        tab.folded.add(id(it))
                    tab.stick = False
                elif id(it) in tab.expanded:
                    tab.expanded.discard(id(it))
                    tab.stick = False
                else:
                    # jump to parent turn / launch
                    j = _parent_row(rows, tab.cur)
                    if j is not None:
                        tab.cur = j
                    tab.stick = False
            return True, Effect.NONE
        elif ch == ord("z"):
            allp = [p for (_l, ts) in [tab.stream.turns()] for (p, _k) in ts]
            if any(id(p) not in tab.folded for p in allp):
                tab.folded = {id(p) for p in allp}
            else:
                tab.folded = set()
            tab.stick = False
            return True, Effect.NONE

        # ---- filters & search ----
        elif ch == ord("e"):
            tab.errors_only = not tab.errors_only
            tab.stick = False
            return True, Effect.NONE
        elif ch == ord("c"):
            present = [c for c in CATEGORIES
                       if any(it.category == c for it in tab.items)]
            order = [None] + present
            pos = order.index(tab.cat_filter) if tab.cat_filter in order else 0
            tab.cat_filter = order[(pos + 1) % len(order)]
            tab.stick = False
            return True, Effect.NONE
        elif ch == ord("C"):
            present = [c for c in CATEGORIES
                       if any(it.category == c for it in tab.items)]
            order = [None] + present
            pos = order.index(tab.cat_filter) if tab.cat_filter in order else 0
            tab.cat_filter = order[(pos - 1) % len(order)]
            tab.stick = False
            return True, Effect.NONE
        elif ch == ord("/"):
            tab.search_active = True
            tab.search = ""
            return True, Effect.NONE
        elif ch == ord("n"):
            if tab.matches:
                tab.match_i = (tab.match_i + 1) % len(tab.matches)
                tab.cur = tab.matches[tab.match_i]
                tab.stick = False
            return True, Effect.NONE
        elif ch == ord("N"):
            if tab.matches:
                tab.match_i = (tab.match_i - 1) % len(tab.matches)
                tab.cur = tab.matches[tab.match_i]
                tab.stick = False
            return True, Effect.NONE

        # ---- live & audit (pure subset) ----
        elif ch == ord("f"):
            tab.following = not tab.following
            if tab.following:
                tab.stick = True
                tab.reload()
            return True, Effect.NONE
        elif ch == ord("p"):
            tab.following = False
            return True, Effect.NONE
        elif ch == ord("r"):
            tab.reload()
            state.toast = Toast(f"{self.G('read')} reloaded", "fg.dim")
            return True, Effect.NONE
        elif ch == ord("m"):
            state.auto = not state.auto     # session-only; config persists
            state.toast = Toast(f"auto-audit {'on' if state.auto else 'off'}", "fg")
            return True, Effect.NONE

        # ---- utility (pure subset) ----
        elif ch == ord("t"):
            tab.show_ts = not tab.show_ts
            return True, Effect.NONE
        elif ch == ord("w"):
            tab.wrap_detail = not tab.wrap_detail
            return True, Effect.NONE
        elif ch == keys.RESIZE:
            return True, Effect.REPAINT

        return False, Effect.NONE
