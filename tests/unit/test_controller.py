"""Controller: scripted-key state transitions, search input, the Esc dismiss
ladder, tab close/QUIT, and the pure helpers (tabstrip hit-test, poll_interval,
remember/restore cursor)."""

import pytest

from cclenzz.model import CATEGORIES
from cclenzz.sessions import Session
from cclenzz.ui.controller import (AppState, Controller, Effect, poll_interval,
                                   remember_owner, restore_cursor,
                                   _tabstrip_hit)
from cclenzz.ui.keys import FakeKeySet
from cclenzz.ui.rows import RowBuilder
from cclenzz.ui.tabstate import Tab, Toast

from helpers.jsonl import fixture_path

BODY_H = 20


def _tab(fixture, follow=False):
    s = Session(fixture_path(fixture))
    s.read_meta()
    return Tab(s, follow)


def _ctx(caps, fixture="basic.jsonl"):
    tab = _tab(fixture)
    rows = RowBuilder(caps).build_rows(tab, 80, now=1000.0)
    state = AppState([tab])
    ctrl = Controller(caps)
    keys = FakeKeySet()
    return tab, rows, state, ctrl, keys


def _key(ctrl, ch, tab, rows, state, keys):
    return ctrl.handle_key(ch, tab, rows, state, BODY_H, len(rows) - 1, keys)


# ---- navigation ---------------------------------------------------------- #
def test_j_k_move_and_clamp(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    last = len(rows) - 1
    tab.cur = 0
    handled, eff = _key(ctrl, ord("j"), tab, rows, state, keys)
    assert handled and eff is Effect.NONE and tab.cur == 1
    _key(ctrl, ord("k"), tab, rows, state, keys)
    assert tab.cur == 0
    # clamp at top
    _key(ctrl, ord("k"), tab, rows, state, keys)
    assert tab.cur == 0
    # clamp at bottom
    tab.cur = last
    _key(ctrl, ord("j"), tab, rows, state, keys)
    assert tab.cur == last


def test_home_end_g_G(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    last = len(rows) - 1
    tab.cur = 3
    _key(ctrl, ord("g"), tab, rows, state, keys)
    assert tab.cur == 0
    _key(ctrl, ord("G"), tab, rows, state, keys)
    assert tab.cur == last
    tab.cur = 3
    _key(ctrl, keys.HOME, tab, rows, state, keys)
    assert tab.cur == 0
    _key(ctrl, keys.END, tab, rows, state, keys)
    assert tab.cur == last


def test_enter_on_turn_row_expands(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    tab.cur = 0                                   # first row is a turn header
    p = rows[0].owner
    assert rows[0].kind == "turn"
    _key(ctrl, 10, tab, rows, state, keys)        # Enter
    assert id(p) in tab.expanded


def test_z_folds_all_turns_then_unfolds(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    _lead, turns = tab.stream.turns()
    n_prompts = len(turns)
    assert n_prompts >= 1
    _key(ctrl, ord("z"), tab, rows, state, keys)
    assert len(tab.folded) == n_prompts
    _key(ctrl, ord("z"), tab, rows, state, keys)
    assert tab.folded == set()


def test_e_toggles_errors_only(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    assert tab.errors_only is False
    _key(ctrl, ord("e"), tab, rows, state, keys)
    assert tab.errors_only is True
    _key(ctrl, ord("e"), tab, rows, state, keys)
    assert tab.errors_only is False


def test_c_cycles_only_present_categories(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    present = [c for c in CATEGORIES if any(it.category == c for it in tab.items)]
    order = [None] + present
    seen = []
    for _ in range(len(order)):
        _key(ctrl, ord("c"), tab, rows, state, keys)
        seen.append(tab.cat_filter)
    # cycled through every present category (never one absent) and returned home
    assert set(seen) == set(order)
    assert seen[0] == present[0]
    assert tab.cat_filter is None                 # full loop returns to None


# ---- search -------------------------------------------------------------- #
def test_slash_activates_search(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    _key(ctrl, ord("/"), tab, rows, state, keys)
    assert tab.search_active is True
    assert tab.search == ""


def test_search_typing_then_enter_recomputes_matches(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    _key(ctrl, ord("/"), tab, rows, state, keys)
    for ch in "config":
        ctrl.handle_search_key(tab, rows, ord(ch), keys)
    assert tab.search == "config"
    ctrl.handle_search_key(tab, rows, 10, keys)   # Enter commits
    assert tab.search_active is False
    assert tab.matches, "the prompt row contains 'config'"


# ---- Esc dismiss ladder -------------------------------------------------- #
def test_esc_clears_search_first(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    tab.search = "cfg"
    tab.matches = [0]
    _key(ctrl, 27, tab, rows, state, keys)
    assert tab.search == "" and tab.matches == []


def test_esc_dismisses_toast_when_no_search(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    state.toast = Toast("hi")
    _key(ctrl, 27, tab, rows, state, keys)
    assert state.toast is None


def test_esc_clears_filters_last(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    tab.cat_filter = "read"
    tab.errors_only = True
    _key(ctrl, 27, tab, rows, state, keys)
    assert tab.cat_filter is None and tab.errors_only is False


# ---- tabs ---------------------------------------------------------------- #
def test_d_on_only_tab_quits(caps_unicode_dark):
    tab, rows, state, ctrl, keys = _ctx(caps_unicode_dark)
    handled, eff = _key(ctrl, ord("d"), tab, rows, state, keys)
    assert handled and eff is Effect.QUIT


def test_tabstrip_hit_math(caps_unicode_dark):
    t1 = _tab("basic.jsonl")
    t2 = _tab("basic.jsonl")
    tabs = [t1, t2]
    aw = caps_unicode_dark.ambiwidth
    # label " 1 proj " -> width 8; seg = 8 + 2 (pad) + 0 (no badge) = 10
    assert _tabstrip_hit(tabs, 3, 0, aw, 80) == 0
    assert _tabstrip_hit(tabs, 9, 0, aw, 80) == 0
    assert _tabstrip_hit(tabs, 12, 0, aw, 80) == 1
    assert _tabstrip_hit(tabs, 500, 0, aw, 80) is None


def test_poll_interval_age_buckets(caps_unicode_dark):
    tab = _tab("basic.jsonl")
    tab.last_mtime = 1000.0
    assert poll_interval(tab, 1.0, 1003.0) == pytest.approx(0.25)   # age<=5
    assert poll_interval(tab, 1.0, 1030.0) == pytest.approx(1.0)    # age<=60
    assert poll_interval(tab, 1.0, 2000.0) == pytest.approx(2.0)    # older


def test_remember_and_restore_cursor_across_rebuild(caps_unicode_dark):
    tab = _tab("basic.jsonl")
    rb = RowBuilder(caps_unicode_dark)
    rows = rb.build_rows(tab, 80, now=1000.0)
    # remember a tool row in the SECOND turn (survives folding the first turn)
    _lead, turns = tab.stream.turns()
    tool = turns[1][1][0]
    i = next(idx for idx, r in enumerate(rows)
             if r.owner is tool and r.kind == "tool")
    tab.cur = i
    remember_owner(tab, rows)
    # fold the first turn -> row indices shift, but `tool` is still present
    tab.folded.add(id(turns[0][0]))
    rows2 = rb.build_rows(tab, 80, now=1000.0)
    restore_cursor(tab, rows2)
    assert rows2[tab.cur].owner is tool
