from __future__ import annotations

"""Detail-block text builder (data layer, unchanged)."""

import json

from .diffs import build_diff, is_file_edit
from .subagents import is_agent_launch


def item_detail_text(item, cwd):
    blocks = []
    if item.kind == "prompt":
        blocks.append(("prompt", item.text or ""))
        return blocks
    inp = item.input or {}
    if is_file_edit(item):
        blocks.append(("diff", build_diff(item, cwd)))
        if item.result is not None:
            label = "result" + (" error" if item.is_error else "")
            blocks.append((label, item.result))
        return blocks
    if item.name == "Bash":
        blocks.append(("command", inp.get("command", "")))
    elif item.name == "Agent" or (item.name or "").startswith("Task"):
        sub = inp.get("subagent_type")
        head = f"subagent: {sub}\n" if sub else ""
        blocks.append(("input", head + (inp.get("prompt") or inp.get("description") or "")))
    elif inp:
        try:
            blocks.append(("input", json.dumps(inp, ensure_ascii=False, indent=2)))
        except (TypeError, ValueError):
            blocks.append(("input", str(inp)))
    if item.result is not None:
        label = "sub-agent report" if is_agent_launch(item) else "result"
        if item.is_error:
            label += " error"
        blocks.append((label, item.result))
    return blocks
