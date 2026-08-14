from __future__ import annotations

"""Distil the whole item tree (main agent + inlined sub-agents) into the compact
transcript the judge reads. Output format is golden-tested byte-for-byte."""

from ..diffs import build_diff, diff_churn, is_file_edit
from ..model import result_to_text
from ..subagents import (is_agent_launch, resolve_subagent, subagent_kind,
                         subtree_quiet)
from ..textutil import _trunc

AUDIT_PROMPT_LEN = 2000
AUDIT_LABEL_LEN = 220
AUDIT_RESULT_LEN = 400
AUDIT_RESULT_LINES = 4
AUDIT_SAY_LEN = 700
AUDIT_SUBREPORT_LEN = 600


def _gist(text, lines=AUDIT_RESULT_LINES, n=AUDIT_RESULT_LEN):
    rows = [ln.strip() for ln in (text or "").splitlines()]
    rows = [ln for ln in rows if ln][:lines]
    return _trunc(" ⏎ ".join(rows), n)


def result_summary(item):
    if is_agent_launch(item):
        kind = item.sub_kind or subagent_kind(item)
        if kind == "async":
            return " → launched sub-agent (its internal steps are inlined below)"
        if kind == "sync":
            body = result_to_text(item.result) if item.result else ""
            return f" → sub-agent report: {_gist(body, 6, AUDIT_SUBREPORT_LEN)}"
        if kind == "unavailable":
            return " → sub-agent ran; its internals are no longer on disk"
        return " → launched sub-agent (no result yet)"
    if item.result is None:
        return " → (no result yet — this call is still in flight)"
    if is_file_edit(item):
        added, removed = diff_churn(build_diff(item, None))
        if item.is_error:
            return f" → EDIT FAILED: {_gist(item.result)}"
        return f" → applied edit (+{added} −{removed} lines)"
    if item.is_error:
        return f" → ERROR: {_gist(item.result)}"
    body = _gist(item.result)
    return f" → {body}" if body else " → ok (empty output)"


def build_audit_transcript(items, stream=None):
    lines = []
    index_map = {}
    prompt_map = {}
    counter = [0]
    prompt_no = [0]
    visited = set()

    def walk(nodes, depth, says):
        pending = list(says or [])
        indent = "  " * depth

        def flush(upto):
            while pending and pending[0][0] <= upto:
                _pos, say = pending.pop(0)
                lines.append(f'{indent}say  "{_trunc(say, AUDIT_SAY_LEN)}"')

        for n, it in enumerate(nodes):
            flush(n)
            i = counter[0]
            counter[0] += 1
            index_map[i] = it
            if it.kind == "prompt":
                prompt_no[0] += 1
                prompt_map[prompt_no[0]] = it
                lines.append(
                    f'{indent}[prompt {prompt_no[0]}] (item {i}) '
                    f'"{_trunc(it.text, AUDIT_PROMPT_LEN)}"')
            else:
                gutter = "↳ " if depth > 0 else "tool "
                lines.append(f"{indent}{gutter}(item {i}) "
                             f"{_trunc(it.label, AUDIT_LABEL_LEN)}{result_summary(it)}")
                if is_agent_launch(it):
                    resolve_subagent(it, recursive=True, visited=visited, depth=depth)
                    if it.children:
                        walk(it.children, depth + 1,
                             it.sub_stream.says if it.sub_stream else None)
        flush(len(nodes))

    walk(items, 0, stream.says if stream is not None else None)

    if stream is not None:
        done = stream.is_turn_complete(idle_ok=True) and subtree_quiet(items)
        status = ("COMPLETE — the agent finished its turn and handed control back "
                  "to the user." if done else
                  "IN PROGRESS — the agent is still working on the LAST prompt; "
                  "later steps for it are not in this transcript yet.")
    else:
        status = "UNKNOWN — completion state was not captured."
    lines.append("")
    lines.append(f"[session status] {status}")
    return "\n".join(lines), index_map, prompt_map
