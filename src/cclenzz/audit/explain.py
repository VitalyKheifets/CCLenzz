from __future__ import annotations

"""The `?` explain-this-command feature — compact per-item context builder and
the model-prose clipper."""

from ..detail import item_detail_text
from ..identity import owning_prompt
from ..textutil import _trunc
from .transcript import _gist

EXPLAIN_CONTEXT_MAX = 6000       # hard cap on the plain-text context we send
EXPLAIN_MAX_LINES = 6            # trim the model's prose to at most this many lines
EXPLAIN_MAX_CHARS = 800          # …and at most this many characters


def build_explain_context(item, tab):
    """Compact, plain-text context for ONE item, grounded in the prompt that
    triggered it. Never includes secrets beyond what is already on screen.
    Truncated hard. Returns "" when there is nothing explainable."""
    cwd = tab.session.cwd
    lines = []
    if cwd:
        lines.append(f"cwd: {cwd}")
    # Prompt row: explain the user's intent, not a command (§4.3).
    if item.kind == "prompt":
        if not (item.text or "").strip():
            return ""
        lines.append("MODE: restate the user's goal for this turn in one or two "
                     "plain lines. There is no command to explain.")
        lines.append(f"user asked: {_trunc(item.text, 1200)}")
        return "\n".join(lines)[:EXPLAIN_CONTEXT_MAX]
    # Tool row: the governing intent, then precisely what the human can expand.
    p = owning_prompt(tab, item)
    if p and p.text:
        lines.append(f"user asked: {_trunc(p.text, 400)}")
    lines.append(f"tool: {item.name or item.tool}   category: {item.category}")
    for label, body in item_detail_text(item, cwd):
        if label == "diff":
            body = _trunc(body, 1500)                 # diffs can be huge
        elif label.startswith("result") or label.startswith("sub-agent report"):
            body = _gist(body, lines=8, n=800)        # summarize noisy output
        lines.append(f"{label}:\n{body}")
    return "\n".join(lines)[:EXPLAIN_CONTEXT_MAX]


def _clip_explain(text):
    """Trim the model's prose to EXPLAIN_MAX_LINES lines / EXPLAIN_MAX_CHARS."""
    text = (text or "").strip()
    if len(text) > EXPLAIN_MAX_CHARS:
        text = text[:EXPLAIN_MAX_CHARS - 1].rstrip() + "…"
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > EXPLAIN_MAX_LINES:
        lines = lines[:EXPLAIN_MAX_LINES]
    return "\n".join(lines)
