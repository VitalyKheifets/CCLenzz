from __future__ import annotations

"""File-edit diff view — build a git-style unified diff from the logged snapshot."""

import difflib

from .classify import _short_path

FILE_EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}


def is_file_edit(item):
    return item.kind == "tool" and item.name in FILE_EDIT_TOOLS


def _diff_lines(before, after, path, tag_new_only=False):
    a = (before or "").splitlines()
    b = (after or "").splitlines()
    label = path or "file"
    fromfile = label + "  (no baseline)" if tag_new_only else label
    lines = list(difflib.unified_diff(a, b, fromfile=fromfile, tofile=label, lineterm=""))
    if not lines:
        return "(no textual change)"
    return "\n".join(lines)


def build_diff(item, cwd):
    """Return diff text for a file-edit Item, built from logged input only.
    Cached on the item (item._diff) so churn/diff are computed once (§14.2)."""
    if item._diff is not None:
        return item._diff
    inp = item.input or {}
    path = _short_path(inp.get("file_path") or inp.get("notebook_path"), cwd)
    if item.name == "Edit":
        text = _diff_lines(inp.get("old_string"), inp.get("new_string"), path)
    elif item.name == "MultiEdit":
        edits = inp.get("edits") or []
        if not edits:
            text = "(no textual change)"
        else:
            chunks = []
            for i, e in enumerate(edits, 1):
                head = f"# edit {i}/{len(edits)}"
                chunks.append(head + "\n" +
                              _diff_lines(e.get("old_string"), e.get("new_string"), path))
            text = "\n".join(chunks)
    elif item.name == "Write":
        text = _diff_lines("", inp.get("content"), path, tag_new_only=True)
    elif item.name == "NotebookEdit":
        text = _diff_lines("", inp.get("new_source"), path, tag_new_only=True)
    else:
        text = ""
    item._diff = text
    return text


def diff_churn(text):
    added = removed = 0
    for ln in (text or "").splitlines():
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            added += 1
        elif ln.startswith("-"):
            removed += 1
    return added, removed


def item_churn(item, cwd):
    if item._churn is None:
        item._churn = diff_churn(build_diff(item, cwd))
    return item._churn
