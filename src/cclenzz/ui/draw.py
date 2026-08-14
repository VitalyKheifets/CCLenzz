from __future__ import annotations

"""Screen-based frame drawing. Bodies are verbatim from the old ``run_tabs``
closures; the only changes are explicit ``(screen, pal, caps, …state…)``
parameters instead of closed-over locals, ``Style`` → curses via ``pal`` (this
module imports no curses of its own, §4), and a threaded ``now``."""

import sys

from ..audit.scoring import label_for
from ..diffs import is_file_edit as _is_file_edit
from ..glyphs import glyph, sep, spinner_frame, u
from ..subagents import is_agent_launch as _is_agent_launch
from ..textutil import disp_w, trunc_end
from .controller import _is_audit_row
from .screen import put


def set_title(caps, text):
    if caps.title:
        try:
            sys.stdout.write(f"\033]0;{text}\007")
            sys.stdout.flush()
        except Exception:
            pass


def draw_tabstrip(screen, pal, caps, tabs, active, tabstrip_off):
    aw = caps.ambiwidth

    def G(k):
        return glyph(k, caps)
    _h, w = screen.getmaxyx()
    put(screen, caps, 0, 0, " " * w, pal.attr("fg"))
    segs = []
    for i, t in enumerate(tabs):
        dot_tok = "ok" if t.following else "fg.dim"
        dch = G("live") if t.following else G("paused")
        if t.items and t.items[-1].is_error:
            dch, dot_tok = G("err_dot"), "error"
        badge = f"(+{t.unread})" if (t.unread and i != active) else ""
        segs.append((i, f" {i + 1} {trunc_end(t.session.project, 12, aw)} ",
                     dch, dot_tok, badge))
    # compute widths & scroll to keep active visible
    widths = [disp_w(s[1], aw) + 2 + disp_w(s[4], aw) for s in segs]
    total = sum(widths)
    x = 0
    off = tabstrip_off[0]
    if total > w - 2:
        # ensure active visible
        start = sum(widths[:active])
        if start < off:
            off = start
        elif start + widths[active] > off + (w - 3):
            off = start + widths[active] - (w - 3)
    else:
        off = 0
    tabstrip_off[0] = off
    if off > 0:
        x = put(screen, caps, 0, 0, G("arr_l") + " ", pal.attr("fg.dim"))
    cursor = 0
    for (i, label, dch, dot_tok, badge) in segs:
        seg_w = disp_w(label, aw) + 2 + disp_w(badge, aw)
        if cursor + seg_w <= off:
            cursor += seg_w
            continue
        if x >= w - 1:
            put(screen, caps, 0, w - 2, G("arr_r"), pal.attr("fg.dim"))
            break
        sel = (i == active)
        a_lbl = pal.attr("accent", sel=sel, extra=pal.A_BOLD if sel else 0)
        if sel and pal.mode in ("mono", "c16"):
            a_lbl = pal.A_REVERSE | pal.A_BOLD
        x = put(screen, caps, 0, x, label, a_lbl)
        x = put(screen, caps, 0, x, dch + " ", pal.attr(dot_tok))
        if badge:
            x = put(screen, caps, 0, x, badge + " ", pal.attr("warn"))
        cursor += seg_w


def _audit_summary(caps, tab):
    verdicts = tab.audit_by_prompt.values()
    if not verdicts:
        return None
    counts = {"aligned": 0, "partial": 0, "drift": 0}
    confs = []
    for v in verdicts:
        lbl, _ = label_for(v.get("alignment"))
        counts[lbl] += 1
        c = v.get("confidence")
        if isinstance(c, int):
            confs.append(c)
    avg = round(sum(confs) / len(confs)) if confs else 0
    check = u("✓", "v", caps)
    pm = u("±", "~", caps)
    segs = [(f"{counts['aligned']}{check} ", "ok"),
            (f"{counts['partial']}{pm} ", "warn"),
            (f"{counts['drift']}{glyph('error', caps)} ", "error"),
            (f"{sep(caps)} conf {avg}", "fg.dim")]
    return ("audit", segs)


def draw_header(screen, pal, caps, tab, w, audit, auto, now):
    def G(k):
        return glyph(k, caps)
    S = sep(caps)
    put(screen, caps, 1, 0, " " * w, pal.attr("fg"))
    x = put(screen, caps, 1, 0, G("selbar"), pal.attr("accent"))
    x = put(screen, caps, 1, x + 1, tab.session.project + " ", pal.attr("fg", extra=pal.A_BOLD))
    x = put(screen, caps, 1, x, f"{S} {tab.session.session_id[:8]} ", pal.attr("fg.dim"))
    n = len(tab.items)
    x = put(screen, caps, 1, x, f"{S} {n} items ", pal.attr("fg.dim"))
    # state
    if audit.status == "running":
        el = int(now - audit.started)
        x = put(screen, caps, 1, x, f"{S} {spinner_frame(caps, now)} auditing {el}s ", pal.attr("warn"))
    elif tab.following:
        x = put(screen, caps, 1, x, f"{S} {G('live')} live ", pal.attr("ok"))
    else:
        x = put(screen, caps, 1, x, f"{S} {G('paused')} paused ", pal.attr("fg.dim"))
    # audit summary
    summ = _audit_summary(caps, tab)
    if summ:
        x = put(screen, caps, 1, x, f"{S} " + summ[0] + " ", pal.attr("fg"))
        for seg, tok in summ[1]:
            x = put(screen, caps, 1, x, seg, pal.attr(tok))
        x = put(screen, caps, 1, x, " ", pal.attr("fg"))
    # filter (only when active)
    filt = []
    if tab.cat_filter:
        filt.append("filter:" + tab.cat_filter)
    if tab.errors_only:
        filt.append("errors")
    if filt:
        x = put(screen, caps, 1, x, f"{S} " + " ".join(filt) + " ", pal.attr("warn"))
    # cost meter
    if tab.audit_cost > 0:
        x = put(screen, caps, 1, x, f"{S} ${tab.audit_cost:.2f} ", pal.attr("fg.dim"))
    x = put(screen, caps, 1, x, f"{S} [Auto {G('live') if auto else G('paused')}]",
            pal.attr("fg.dim"))
    state = f"{G('live') if tab.following else G('paused')} " \
            f"{'live' if tab.following else 'paused'}"
    set_title(caps, f"cclenzz — {tab.session.project} {state}")


def draw_row(screen, pal, caps, y, row, width, selected):
    def G(k):
        return glyph(k, caps)
    aw = caps.ambiwidth
    # Paint the full-width background first so every line fully overwrites
    # the previous frame — curses' erase() diffing can leave stale trailing
    # cells when the layout shifts (§14.3: rows overwritten in place).
    if selected and pal.mode in ("rgb", "c256"):
        put(screen, caps, y, 0, " " * width, pal.bg_attr("sel.bg"))
    else:
        put(screen, caps, y, 0, " " * width, pal.attr("fg"))
    # col0 selection bar
    if selected:
        a = pal.attr("accent", extra=pal.A_REVERSE if pal.mode in ("mono", "c16") else 0)
        put(screen, caps, y, 0, G("selbar"), a)
    # col1 fold
    put(screen, caps, y, 1, row.fold, pal.attr("accent", sel=selected))
    # col2 status
    put(screen, caps, y, 2, row.status, pal.attr(row.status_tok, sel=selected))
    # reserve room for the right-aligned meta so long left text can't
    # overwrite it (§5.3)
    rightw = sum(disp_w(t[0], aw) for t in row.right)
    left_max = width - rightw - (1 if row.right else 0)
    # Search-match reverse-video is already baked into the span's Style (§5.4).
    x = 3
    for (text, tok, extra) in row.left:
        if x >= left_max:
            break
        ex = pal.style_extra(extra)
        x = put(screen, caps, y, x, text, pal.attr(tok, sel=selected, extra=ex), maxx=left_max)
    # dim rule fill (turn headers)
    if row.fill and x + 1 < left_max:
        put(screen, caps, y, x + 1, " " + G("rule") * (left_max - x - 2) + " ",
            pal.attr(row.fill, sel=selected), maxx=left_max)
    # right-aligned meta
    rx = max(x, width - rightw)
    for (text, tok, extra) in row.right:
        rx = put(screen, caps, y, rx, text,
                 pal.attr(tok, sel=selected, extra=pal.style_extra(extra)), maxx=width)


def draw_footer(screen, pal, caps, tab, rows, w, h, audit, toast, now):
    def G(k):
        return glyph(k, caps)
    put(screen, caps, h - 1, 0, " " * w, pal.attr("fg.dim"))
    # right — position
    pos = f"{tab.cur + 1}/{len(rows)}" if rows else "0/0"
    pct = f" {sep(caps)} {int(100 * (tab.cur + 1) / len(rows))}%" if rows else ""
    rtext = pos + pct
    if tab.search_active or (tab.matches and tab.search):
        mi = (tab.match_i + 1) if tab.matches else 0
        rtext = f"{G('read')}{tab.search} {mi}/{len(tab.matches)}   " + rtext
    put(screen, caps, h - 1, max(0, w - disp_w(rtext, caps.ambiwidth) - 1), rtext, pal.attr("fg.dim"))
    # left — toast / audit progress / hints / search input
    if tab.search_active:
        put(screen, caps, h - 1, 0, "/" + tab.search, pal.attr("fg"))
        return
    if audit.status == "running":
        el = int(now - audit.started)
        txt = f" {spinner_frame(caps, now)} auditing {sep(caps)} {audit.model} {sep(caps)} {el}s {sep(caps)} x cancel"
        put(screen, caps, h - 1, 0, txt, pal.attr("warn"))
        return
    if toast[0] and toast[0].alive():
        tk = toast[0].token if not toast[0].faded() else "fg.dim"
        put(screen, caps, h - 1, 0, " " + toast[0].text, pal.attr(tk))
        return
    # contextual hints for the selected row
    hint = contextual_hints(caps, tab, rows)
    put(screen, caps, h - 1, 0, " " + hint, pal.attr("fg.dim"))


def contextual_hints(caps, tab, rows):
    def G(k):
        return glyph(k, caps)
    if not rows:
        return "h help"
    row = rows[tab.cur]
    owner = row.owner
    parts = []
    if _is_audit_row(row):
        shut = owner is not None and id(owner) in tab.audit_folded
        parts = [f"{G('collapsed') if shut else G('expanded')} audit",
                 "a re-audit"]
    elif owner is not None and owner.kind == "prompt":
        if id(owner) in tab.folded:
            parts = [f"{G('collapsed')} open", "a audit"]
        elif id(owner) in tab.expanded:
            parts = [f"{G('collapsed')} collapse", "a audit"]
        else:
            parts = [f"{G('expanded')} full prompt", "a audit"]
    elif owner is not None and _is_agent_launch(owner):
        parts = [f"{G('collapsed')} steps", "y yank", "o open"]
    elif owner is not None and _is_file_edit(owner):
        parts = [f"{G('collapsed')} diff", "O edit file"]
    else:
        parts = [f"{G('collapsed')} expand", "y yank", "o open"]
    # ? explain — for any eligible tool row not yet explained (§6.3)
    if (owner is not None and owner.kind == "tool"
            and not _is_audit_row(row) and id(owner) not in tab.explain):
        parts.append("? explain")
    parts.append("/ search")
    parts.append("h help")
    return f" {sep(caps)} ".join(parts)


def draw_newchip(screen, pal, caps, tab, rows, w, h, body_h):
    if tab.following and not tab.stick and tab.new_since_release > 0:
        chip = f"{glyph('newchip', caps)} {tab.new_since_release} new "
        put(screen, caps, h - 2, max(0, w - disp_w(chip, caps.ambiwidth) - 2), chip,
            pal.attr("accent", extra=pal.A_DIM))


def draw_scrollbar(screen, pal, caps, rows, w, body_h, active_top):
    if len(rows) <= body_h:
        return
    track_x = w - 1
    for i in range(body_h):
        put(screen, caps, 2 + i, track_x, glyph("sb_track", caps), pal.attr("fg.faint"))
    thumb = max(1, int(body_h * body_h / len(rows)))
    top_frac = active_top / max(1, len(rows))
    ty = int(body_h * top_frac)
    for i in range(thumb):
        if ty + i < body_h:
            put(screen, caps, 2 + ty + i, track_x, glyph("sb_thumb", caps), pal.attr("fg.dim"))


def draw_empty_card(screen, pal, caps):
    h, w = screen.getmaxyx()
    screen.erase()
    card = [
        "cclenzz — Claude Code Monitor", "",
        "No sessions found under", "~/.claude/projects/", "",
        "Start a Claude Code conversation and",
        "cclenzz will pick it up automatically —",
        "or point it elsewhere: set projects_glob",
        "in ~/.cclenzz/config.toml",
    ]
    top = max(0, (h - len(card)) // 2)
    for i, ln in enumerate(card):
        x = max(0, (w - len(ln)) // 2)
        put(screen, caps, top + i, x, ln, pal.attr("accent" if i == 0 else "fg.dim"))
    screen.refresh()


def draw_mini(screen, pal, caps, tabs, active, w, h):
    screen.erase()
    for i, t in enumerate(tabs[:h]):
        last = t.items[-1] if t.items else None
        tool = (last.tool if last and last.kind == "tool" else
                ("prompt" if last else u("—", "-", caps)))
        state = "live" if t.following else "paused"
        line = f"{i + 1} {t.session.project} {sep(caps)} {tool} {sep(caps)} {state}"
        put(screen, caps, i, 0, trunc_end(line, w - 1, caps.ambiwidth),
            pal.attr("accent" if i == active else "fg"))
    screen.refresh()
