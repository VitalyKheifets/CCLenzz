"""RowBuilder over the session fixtures: turn/tool/sub rows, folding, expansion
+ diffs, filters, search reverse-video, glyph tiers, and spinner determinism."""

import pytest

from cclenzz.diffs import is_file_edit
from cclenzz.sessions import Session
from cclenzz.ui.rows import RowBuilder
from cclenzz.ui.style import Style
from cclenzz.ui.tabstate import Tab

from helpers.jsonl import fixture_path


def _tab(fixture, follow=True):
    s = Session(fixture_path(fixture))
    s.read_meta()
    return Tab(s, follow)


def _turns(tab):
    return tab.stream.turns()


# --------------------------------------------------------------------------- #
def test_turn_row_carries_prompt_text(caps_unicode_dark):
    tab = _tab("basic.jsonl")
    rb = RowBuilder(caps_unicode_dark)
    rows = rb.build_rows(tab, 80, now=1000.0)
    turns = [r for r in rows if r.kind == "turn"]
    assert turns, "expected at least one turn row"
    assert any("read the config and fix the bug" in r.plain for r in turns)


def test_folding_a_prompt_changes_rows(caps_unicode_dark):
    tab = _tab("basic.jsonl")
    rb = RowBuilder(caps_unicode_dark)
    rows = rb.build_rows(tab, 80, now=1000.0)
    _lead, turns = _turns(tab)
    p = turns[0][0]
    tab.folded.add(id(p))
    folded_rows = rb.build_rows(tab, 80, now=1000.0)
    # a folded turn hides its child tool rows, so the row count drops.
    assert len(folded_rows) < len(rows)


def test_expanding_edit_tool_yields_diff_sub_rows(caps_unicode_dark):
    tab = _tab("edits.jsonl")
    rb = RowBuilder(caps_unicode_dark)
    edit = next(it for it in tab.items if is_file_edit(it) and it.name == "Edit")
    tab.expanded.add(id(edit))
    rows = rb.build_rows(tab, 80, now=1000.0)
    subs = [r for r in rows if r.kind == "sub" and r.owner is edit]
    assert subs, "expected detail sub-rows for an expanded Edit"
    joined = "\n".join(r.plain for r in subs)
    assert "diff" in joined                       # the block header label
    assert "x = 10" in joined                     # the changed line body


def test_errors_only_hides_non_error_tools(caps_unicode_dark):
    tab = _tab("edits.jsonl")
    rb = RowBuilder(caps_unicode_dark)
    tab.errors_only = True
    rows = rb.build_rows(tab, 80, now=1000.0)
    tool_rows = [r for r in rows if r.kind == "tool"]
    assert tool_rows, "the one error tool should remain"
    assert all(r.owner.is_error for r in tool_rows)


def test_cat_filter_limits_to_one_category(caps_unicode_dark):
    # basic.jsonl mixes read/edit/bash tools; categories.jsonl is pretty-printed
    # multi-line JSON that the line-oriented ItemStream only reads a prompt from.
    tab = _tab("basic.jsonl")
    rb = RowBuilder(caps_unicode_dark)
    tab.cat_filter = "read"
    rows = rb.build_rows(tab, 80, now=1000.0)
    tool_rows = [r for r in rows if r.kind == "tool"]
    assert tool_rows
    assert all(r.owner.category == "read" for r in tool_rows)


def test_search_ors_in_reverse_style(caps_unicode_dark):
    tab = _tab("basic.jsonl")
    rb = RowBuilder(caps_unicode_dark)
    tab.search = "config"
    tab.search_active = True
    rows = rb.build_rows(tab, 80, now=1000.0)

    def has_reverse(row):
        return any((extra & Style.REVERSE) for (_t, _tok, extra) in row.left)

    assert any(has_reverse(r) for r in rows)


def test_ascii_tier_uses_ascii_glyphs(caps_ascii):
    tab = _tab("basic.jsonl")
    rb = RowBuilder(caps_ascii)
    rows = rb.build_rows(tab, 80, now=1000.0)
    turn = next(r for r in rows if r.kind == "turn")
    # ascii prompt glyph is ">" not the unicode "❯"
    assert turn.left[0][0].startswith(">")
    assert "❯" not in turn.plain


def test_spinner_status_deterministic_for_fixed_now(caps_unicode_dark):
    tab = _tab("inprogress.jsonl")
    rb = RowBuilder(caps_unicode_dark)
    rows1 = rb.build_rows(tab, 80, now=1000.0)
    rows2 = rb.build_rows(tab, 80, now=1000.0)
    tool1 = next(r for r in rows1 if r.kind == "tool")
    tool2 = next(r for r in rows2 if r.kind == "tool")
    assert tool1.status == tool2.status
    assert tool1.status != " "                    # a live spinner frame


@pytest.mark.parametrize("fixture", [
    "basic.jsonl", "edits.jsonl", "errors.jsonl", "categories.jsonl",
    "inprogress.jsonl", "unicode.jsonl", "malformed.jsonl",
])
def test_build_rows_never_raises(caps_unicode_dark, caps_ascii, fixture):
    for caps in (caps_unicode_dark, caps_ascii):
        tab = _tab(fixture)
        rows = RowBuilder(caps).build_rows(tab, 80, now=1000.0)
        assert isinstance(rows, list)
