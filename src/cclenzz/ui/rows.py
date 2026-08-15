from __future__ import annotations

"""Curses-free row building (§5.4). ``RowBuilder`` reproduces the old
``run_tabs`` row closures verbatim, with three mechanical, behavior-preserving
transformations:

1. ``curses.A_BOLD`` / ``A_DIM`` on a span become ``Style.BOLD`` / ``Style.DIM``;
   ``ui/draw.py`` maps them back to curses at draw time.
2. ``time.time()`` becomes an explicit ``now`` parameter (the main loop passes
   one ``time.time()`` per frame) so spinners / elapsed durations / delta-note
   expiry are deterministic in tests and unchanged in production.
3. Search-match reverse-video becomes row data: ``build_rows`` OR-es
   ``Style.REVERSE`` into any left span whose text contains the active search
   query, under the identical condition the old ``draw_row`` used. Whole-row
   *selection* highlighting stays a draw-time concern.

``RowBuilder`` never imports curses or reads the clock/filesystem, except that it
calls ``resolve_subagent`` / ``item_detail_text`` exactly where the old code did
(which may touch the filesystem for sub-agent transcripts — identical to today).
"""

import textwrap
import time

from ..ansi import RGB_
from ..audit.scoring import dim_for, label_for
from ..detail import item_detail_text
from ..diffs import is_file_edit, item_churn
from ..glyphs import CAT_GLYPH, ell, glyph, sep, spinner_frame, u
from ..subagents import (is_agent_launch, resolve_subagent, subagent_kind)
from ..textutil import (disp_w, fmt_clock, fmt_clock_secs, fmt_dur, trunc_end,
                        trunc_mid)
from .style import Style


class RenderRow:
    __slots__ = ("owner", "kind", "fold", "status", "status_tok",
                 "left", "right", "fill", "plain", "cite")

    def __init__(self, owner, kind, left, right=None, fold=" ",
                 status=" ", status_tok="fg", fill=None, cite=None):
        self.owner = owner
        self.kind = kind
        self.left = left               # list of (text, token, Style)
        self.right = right or []
        self.fold = fold
        self.status = status
        self.status_tok = status_tok
        self.fill = fill               # token for a dim rule fill, or None
        self.plain = "".join(s[0] for s in left) + "".join(s[0] for s in (right or []))
        self.cite = cite               # (item, prompt) for navigable audit cites


class RowBuilder:
    def __init__(self, caps):
        self.caps = caps
        self.aw = caps.ambiwidth

    def G(self, k):
        return glyph(k, self.caps)

    # ---- filters ---------------------------------------------------------- #
    def passes(self, tab, it):
        if tab.errors_only and not (it.kind == "tool" and it.is_error):
            return False
        if tab.cat_filter and it.category != tab.cat_filter:
            return False
        return True

    def status_cell(self, it, now):
        """(char, token) for the status gutter."""
        if it.kind == "tool" and it.result is None and it.tool_use_id:
            return spinner_frame(self.caps, now), "warn"
        if it.kind == "tool" and it.is_error:
            return self.G("error"), "error"
        return " ", "fg"

    # ---- tree guides ------------------------------------------------------ #
    def guides(self, trail):
        """trail: list of bool is_last for each ancestor depth level."""
        if not trail:
            return ""
        parts = []
        for last in trail[:-1]:
            parts.append("  " if last else self.G("g_v") + " ")
        parts.append(self.G("g_l") + " " if trail[-1] else self.G("g_t") + " ")
        return "".join(parts)

    # ---- audit deltas ----------------------------------------------------- #
    def delta_note(self, tab, it, now):
        d = tab.audit_deltas.get(id(it))
        if not d:
            return None
        val, born = d
        if now - born > 30:
            return None
        sign = u("↑", "^", self.caps) + " +" if val > 0 else \
            (u("↓", "v", self.caps) + " " if val < 0 else "")
        return f"({sign}{val})" if val else None

    # ---- build the detail sub-rows for an item ---------------------------- #
    def emit_blocks(self, rows, blocks, base_indent, owner, width, tab, kind="sub",
                    body_tok="fg"):
        aw = self.aw
        wrap_w = max(10, width - base_indent - 6)
        for blabel, btext in blocks:
            gh = self.G("g_h")
            rows.append(RenderRow(owner, kind, [
                (" " * base_indent + gh + gh + " ", "fg.faint", 0),
                (blabel, "fg.dim", Style.BOLD),   # label stays legible
                (" " + gh * max(2, wrap_w - disp_w(blabel, aw)), "fg.faint", 0),
            ]))
            all_lines = (btext or "").splitlines()
            if blabel == "diff":
                cap = 120
                shown = all_lines[:cap]
                for ln in shown:
                    tok, ex = self.diff_tok(ln)
                    clipped = ln if disp_w(ln, aw) <= wrap_w else trunc_end(ln, wrap_w, aw)
                    rows.append(RenderRow(owner, kind,
                                [(" " * base_indent + "  " + clipped, tok, ex)]))
                if len(all_lines) > cap:
                    rows.append(RenderRow(owner, kind,
                                [(" " * base_indent + f"  {ell(self.caps)} +{len(all_lines) - cap} "
                                  f"more lines (o to open)", "fg.dim", 0)]))
            else:
                cap = 60
                shown = all_lines[:cap]
                for ln in shown:
                    if tab.wrap_detail:
                        for wl in (textwrap.wrap(ln, wrap_w) or [""]):
                            rows.append(RenderRow(owner, kind,
                                        [(" " * base_indent + "  " + wl, body_tok, 0)]))
                    else:
                        rows.append(RenderRow(owner, kind,
                                    [(" " * base_indent + "  "
                                      + trunc_end(ln, wrap_w, aw), body_tok, 0)]))
                if len(all_lines) > cap:
                    rows.append(RenderRow(owner, kind,
                                [(" " * base_indent + f"  {ell(self.caps)} +{len(all_lines) - cap} "
                                  f"more lines (o to open)", "fg.dim", 0)]))

    # ---- the AI-callout card (§2.1 / §3.3) -------------------------------- #
    # Everything CCLenzz generates via the LLM — the `?` explanation and the
    # intent audit derivation — renders as one framed card so it can never be
    # mistaken for raw transcript data: a violet ✦ sigil, a dashed left rail,
    # and a `by claude` provenance footer.
    def emit_ai_block(self, rows, sections, base_indent, owner, width, tab,
                      kind="sub", title="ai", body_tok="fg",
                      attribution="generated by claude", model=None):
        aw = self.aw
        ind = " " * base_indent
        bar = self.G("ai_bar")
        rail = (ind + bar + "  ", "ai.dim", 0)
        wrap_w = max(10, width - base_indent - 6)
        sig = self.G("badge")

        # header — ╭─ ✦ title ───────────────────────────
        head = ind + self.G("ai_tl") + self.G("g_h") + " "
        htxt = sig + " " + title
        rows.append(RenderRow(owner, kind, [
            (head, "ai.dim", 0),
            (sig + " ", "ai", Style.BOLD),
            (title, "ai", Style.BOLD),
            (" " + self.G("g_h") * max(2, wrap_w - disp_w(htxt, aw)),
             "ai.dim", 0),
        ]))

        # body — each section is an optional sub-label then wrapped prose,
        # every line carried on the dashed rail.
        for slabel, stext in sections:
            if slabel:
                rows.append(RenderRow(owner, kind,
                            [rail, (slabel, "fg.dim", Style.BOLD)]))
            all_lines = (stext or "").splitlines() or [""]
            cap = 60
            for ln in all_lines[:cap]:
                if tab.wrap_detail:
                    for wl in (textwrap.wrap(ln, wrap_w) or [""]):
                        rows.append(RenderRow(owner, kind, [rail, (wl, body_tok, 0)]))
                else:
                    rows.append(RenderRow(owner, kind,
                                [rail, (trunc_end(ln, wrap_w, aw), body_tok, 0)]))
            if len(all_lines) > cap:
                rows.append(RenderRow(owner, kind, [rail,
                            (f"{ell(self.caps)} +{len(all_lines) - cap} "
                             f"more lines (o to open)", "fg.dim", 0)]))

        # footer — ╰─ ✦ generated by claude · model
        credit = attribution + (f" {sep(self.caps)} {model}" if model else "")
        rows.append(RenderRow(owner, kind, [
            (ind + self.G("g_l") + self.G("g_h") + " ", "ai.dim", 0),
            (sig + " ", "ai", 0),
            (credit, "ai.dim", Style.DIM),
        ]))

    def diff_tok(self, line):
        if line.startswith("+++") or line.startswith("---"):
            return "fg.dim", 0
        if line.startswith("@@"):
            return "cat.read", 0
        if line.startswith("#"):
            return "fg.dim", 0
        if line.startswith("+"):
            return "cat.edit", 0
        if line.startswith("-"):
            return "error", 0
        return "fg", 0

    # ---- the `explain` overlay block (§2.1 / §2.4 / §3.3) ----------------- #
    def emit_explain_block(self, rows, it, base_indent, width, tab, now):
        rec = tab.explain.get(id(it))
        if not rec:
            return
        status = rec.get("status")
        if status == "running":
            body = f"explaining… {spinner_frame(self.caps, now)}"
            tok = "fg.dim"
        elif status == "error":
            body = f"explain unavailable — {rec.get('text') or 'unknown error'}"
            tok = "fg.dim"
        else:  # done
            body = rec.get("text") or ""
            stale = it.rev != rec.get("rev") or rec.get("stale")
            if stale:
                body = body + "\n(result changed — ? to refresh)"
                tok = "fg.dim"
            else:
                tok = "fg"
        # A prompt row gets a "restate the goal" answer; a tool row gets a
        # command explanation — title the card accordingly.
        title = "intent" if it.kind == "prompt" else "explain"
        verb = "read by claude" if it.kind == "prompt" else "explained by claude"
        self.emit_ai_block(rows, [("", body)], base_indent, it, width, tab,
                           title=title, body_tok=tok, attribution=verb,
                           model=rec.get("model"))

    # ---- one tool item + (optionally) its detail / sub-agent tree --------- #
    def emit_item(self, tab, rows, it, trail, width, now):
        aw = self.aw
        cwd = tab.session.cwd
        depth = len(trail)
        base_indent = 2 + 2 * depth
        expanded = id(it) in tab.expanded
        gpref = self.guides(trail)
        cat_tok = "cat." + it.category if ("cat." + it.category) in RGB_ else "cat.other"
        sch, stok = self.status_cell(it, now)
        flagged = id(it) in tab.audit_flagged
        if flagged and sch == " ":
            sch, stok = self.G("flagged"), "warn"

        left = []
        indent = "  " + gpref if depth > 0 else "  "
        left.append((indent, "fg.faint", 0))

        # A sub-agent's internal prompt (its brief) — render its text.
        if it.kind == "prompt":
            budget = max(6, width - base_indent - 14)
            left.append((f'{self.G("prompt")} ', "accent", Style.BOLD))
            left.append((f'"{trunc_end(it.text or "", budget, aw)}"',
                         "accent", Style.BOLD))
        else:
            icon = self.G(CAT_GLYPH.get(it.category, "other"))
            left.append((icon + " ", cat_tok, 0))
            left.append((f"{trunc_end(it.tool or '', 9, aw):<9} ", "fg", 0))
            arg_budget = max(6, width - base_indent - 14 - 22)
            if it.arg:
                if it.arg_kind == "path":
                    argtxt = trunc_mid(it.arg, arg_budget, aw)
                else:
                    argtxt = trunc_end(it.arg, arg_budget, aw)
                left.append((argtxt, cat_tok if not flagged else "warn", 0))

        right = []
        if is_file_edit(it):
            added, removed = item_churn(it, cwd)
            if added or removed:
                right.append((f"+{added} ", "ok", 0))
                right.append((f"{u('−', '-', self.caps)}{removed}  ", "error", 0))
        if is_agent_launch(it):
            b = self.subagent_badge(it, now)
            if b:
                right.append((b + "  ", "fg.dim", 0))
        dur = it.duration
        if it.kind == "tool" and it.result is None and it.tool_use_id and it.ts_start:
            elapsed = max(0, now - it.ts_start)
            right.append((fmt_dur(elapsed), "fg.dim", 0))
        elif dur is not None:
            right.append((fmt_dur(dur), "fg.dim", 0))
        if tab.show_ts and it.ts_start:
            right.append(("  " + fmt_clock_secs(it.ts_start), "fg.faint", 0))
        # An always-visible trace that an answer is folded here (§2.2).
        if id(it) in tab.explain and not expanded:
            right.append(("  " + self.G("explain"), "fg.faint", 0))

        fold = " "
        foldable = is_agent_launch(it) or bool(item_detail_text(it, cwd))
        if foldable:
            fold = self.G("expanded") if expanded else self.G("collapsed")

        rows.append(RenderRow(it, "tool", left, right, fold=fold,
                              status=sch, status_tok=stok))

        if not expanded:
            return

        # The explanation slots in as the FIRST detail block — the human reads
        # the answer before the raw material (§2.1).
        self.emit_explain_block(rows, it, base_indent, width, tab, now)

        if is_agent_launch(it):
            resolve_subagent(it)
            inp = it.input or {}
            sub = inp.get("subagent_type")
            brief = (f"subagent: {sub}\n" if sub else "") + \
                    (inp.get("prompt") or inp.get("description") or "")
            if brief.strip():
                self.emit_blocks(rows, [("brief", brief)], base_indent, it, width, tab)
            if it.sub_kind == "async" and it.children:
                kids = it.children
                for ci, child in enumerate(kids):
                    self.emit_item(tab, rows, child, trail + [ci == len(kids) - 1], width, now)
            elif it.sub_kind == "sync":
                self.emit_blocks(rows, [("report", it.result or "")], base_indent, it, width, tab)
            elif it.sub_kind == "unavailable":
                rows.append(RenderRow(it, "sub",
                            [(" " * base_indent + f"{self.G('g_l')} internals no longer on disk",
                              "fg.dim", 0)]))
            else:
                rows.append(RenderRow(it, "sub",
                            [(" " * base_indent + f"{self.G('g_l')} sub-agent starting…",
                              "fg.dim", 0)]))
        else:
            blocks = item_detail_text(it, cwd)
            self.emit_blocks(rows, blocks, base_indent, it, width, tab)

    def subagent_badge(self, it, now):
        kind = it.sub_kind or subagent_kind(it)
        if kind == "async":
            if it.resolved and it.children:
                tail = ""
                if not (it.sub_stream and it.sub_stream.is_turn_complete()):
                    tail = " " + spinner_frame(self.caps, now)
                return f"{self.G('g_l')} {len(it.children)} steps{tail}"
            return f"{self.G('g_l')} steps on disk"
        if kind == "sync":
            return f"{self.G('g_l')} report only"
        if kind == "unavailable":
            return f"{self.G('g_l')} internals gone"
        return ""

    # ---- prompt / turn header + digest + audit derivation ----------------- #
    def turn_digest(self, tab, p, kids):
        tools = len(kids)
        edits = [k for k in kids if is_file_edit(k)]
        added = removed = 0
        for e in edits:
            a, r = item_churn(e, tab.session.cwd)
            added += a
            removed += r
        errs = sum(1 for k in kids if k.is_error)
        parts = [f"{tools} tools"]
        if edits:
            parts.append(f"{len(edits)} edits(+{added} {u('−', '-', self.caps)}{removed})")
        if errs:
            parts.append(f"{errs} {self.G('error')}")
        return f" {sep(self.caps)} ".join(parts)

    def emit_turn(self, tab, rows, p, kids, width, now):
        aw = self.aw
        folded = id(p) in tab.folded
        expanded = id(p) in tab.expanded
        text = p.text or ""
        right = []
        clock = fmt_clock_secs(p.ts_start) if (tab.show_ts and p.ts_start) else \
                (fmt_clock(p.ts_start) if p.ts_start else "")
        # turn duration: last kid ts_end - prompt ts_start
        dur = None
        live = False
        if kids:
            last = kids[-1]
            if last.result is None and last.tool_use_id:
                live = True
            elif last.ts_end and p.ts_start:
                dur = last.ts_end - p.ts_start
        if folded:
            dtext = self.turn_digest(tab, p, kids)
            right.append((dtext + "  ", "fg.dim", 0))
        if clock:
            right.append((clock, "fg.dim", 0))
        if live:
            right.append(("  " + self.G("live"), "ok", 0))
        elif dur is not None:
            right.append(("  " + fmt_dur(dur), "fg.dim", 0))

        # Truncate the prompt text so a dim rule can always separate it from
        # the right-aligned metadata (§5.3).
        rightw = sum(disp_w(t[0], aw) for t in right)
        text_budget = max(6, width - 3 - 3 - rightw - 5)
        shown = trunc_end(text, text_budget, aw)
        left = [(f'{self.G("prompt")} ', "accent", Style.BOLD),
                (f'"{shown}"', "accent", Style.BOLD)]

        fold = self.G("expanded") if not folded else self.G("collapsed")
        rows.append(RenderRow(p, "turn", left, right, fold=fold, fill="fg.faint"))

        # An `?`-explanation of the user's intent slots in first, above the
        # full prompt text (§2.1). Same reveal gesture as the prompt text.
        if not folded and id(p) in tab.expanded:
            self.emit_explain_block(rows, p, 3, width, tab, now)

        # full prompt text — revealed with → / Enter on the prompt row, so a
        # long prompt truncated in the header can be read in full inline.
        if expanded and not folded and text:
            self.emit_blocks(rows, [("prompt", text)], 3, p, width, tab,
                             kind="ptext")

        # audit badge
        v = tab.audit_by_prompt.get(id(p))
        audit_open = v and id(p) not in tab.audit_folded
        if v:
            align = v.get("alignment")
            conf = v.get("confidence")
            label, ckey = label_for(align)
            # ✦ in the AI violet flags the verdict as machine-generated; the
            # score itself keeps its aligned/partial/drift color.
            bleft = [("   " + self.G("badge") + " ", "ai", Style.BOLD),
                     (f"{label} {align} {sep(self.caps)} conf {conf}", ckey,
                      Style.DIM if dim_for(conf) else Style.BOLD)]
            dn = self.delta_note(tab, p, now)
            if dn:
                up = dn.startswith("(" + u("↑", "^", self.caps))
                bleft.append(("  " + dn, "ok" if up else "error", 0))
            # A fold chevron makes the derivation view collapsible on its own
            # (← / Enter on this row) without folding the whole turn.
            bfold = (self.G("expanded") if audit_open else self.G("collapsed")) \
                if not folded else " "
            rows.append(RenderRow(p, "audit", bleft, fold=bfold))

        if folded:
            return

        # audit derivation view (visible while the turn is unfolded, unless
        # the badge row has been collapsed with ← / Enter)
        if audit_open:
            self.emit_audit_detail(tab, rows, p, v, width)

        for kid in kids:
            if self.passes(tab, kid):
                self.emit_item(tab, rows, kid, [], width, now)

    def emit_audit_detail(self, tab, rows, p, v, width):
        base_indent = 3
        label, _ = label_for(v.get("alignment"))
        summary = (f"{label} {sep(self.caps)} alignment {v.get('alignment')} "
                   f"{sep(self.caps)} confidence {v.get('confidence')}")
        sections = [("", summary), ("", v.get("reason") or "")]
        if v.get("ask"):
            sections.append(("read as", v["ask"]))
        if v.get("delivered"):
            sections.append(("delivered", v["delivered"]))
        # Only render the derivation blocks when the prompt is expanded, to
        # keep the default view calm; the badge + reason always show.
        if id(p) in tab.expanded:
            for d in v.get("defects") or []:
                where = ", ".join(str(i) for i in (d.get("items") or []))
                sections.append((f"−{d.get('points')} {d.get('code')}",
                                 (d.get("detail") or "")
                                 + (f"  (item {where})" if where else "")))
            for g in v.get("evidence_gaps") or []:
                sections.append((f"−{g.get('points')} conf {sep(self.caps)} "
                                 f"{g.get('code')}", g.get("detail") or ""))
        self.emit_ai_block(rows, sections, base_indent, p, width, tab,
                           title="intent audit", attribution="judged by claude",
                           model=v.get("model"))

    # ---- assemble all rows for a tab -------------------------------------- #
    def build_rows(self, tab, width, now=None):
        if now is None:
            now = time.time()
        rows = []
        lead, turns = tab.stream.turns()
        for it in lead:
            if self.passes(tab, it):
                self.emit_item(tab, rows, it, [], width, now)
        for (p, kids) in turns:
            self.emit_turn(tab, rows, p, kids, width, now)
        # Search-match reverse-video is row data (§5.4 item 3): apply the
        # identical condition the old draw_row used, to left spans only.
        q = tab.search.lower() if (tab.matches or tab.search_active) else ""
        if q:
            for r in rows:
                new_left = []
                for (text, tok, extra) in r.left:
                    if q in text.lower():
                        extra = extra | Style.REVERSE
                    new_left.append((text, tok, extra))
                r.left = new_left
        return rows
