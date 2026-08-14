from __future__ import annotations

"""Tool classification — (category, tool-name, key-argument, arg-kind)."""

import os

from .textutil import _first_line


def _short_path(path, cwd):
    """Show path relative to cwd when possible, else the basename."""
    if not path:
        return ""
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    return os.path.basename(path.rstrip("/")) or path


def classify_tool(name, tool_input, cwd):
    """Return (category, tool_name, key_argument, arg_kind) for a tool_use.
    arg_kind is 'path' (middle-truncate) or 'text' (end-truncate)."""
    ti = tool_input or {}
    name = name or "?"

    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        server = parts[1] if len(parts) > 1 else "?"
        tool = parts[2] if len(parts) > 2 else "?"
        return ("mcp", "MCP", f"{server}.{tool}", "text")
    if name == "Bash":
        return ("bash", "Bash", _first_line(ti.get("command")), "text")
    if name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        return ("edit", name,
                _short_path(ti.get("file_path") or ti.get("notebook_path"), cwd), "path")
    if name == "Read":
        return ("read", "Read", _short_path(ti.get("file_path"), cwd), "path")
    if name in ("Grep", "Glob"):
        return ("search", name, ti.get("pattern") or ti.get("query") or "", "text")
    if name == "Agent":
        return ("agent", "Agent",
                ti.get("subagent_type") or ti.get("description") or "?", "text")
    if name == "WebSearch":
        return ("web", "WebSearch", ti.get("query") or "", "text")
    if name == "WebFetch":
        return ("web", "WebFetch", ti.get("url") or "", "text")
    if name == "Skill":
        return ("skill", "Skill", ti.get("skill") or ti.get("command") or "?", "text")
    if name == "ToolSearch":
        return ("search", "ToolSearch", ti.get("query") or "", "text")
    if name.startswith("Task"):
        return ("agent", name, ti.get("description") or ti.get("prompt") or "", "text")
    if name == "Artifact":
        return ("artifact", "Artifact", _short_path(ti.get("file_path"), cwd), "path")
    return ("other", name, "", "text")


def item_label(item):
    """A combined 'Tool · arg' label — used by the audit transcript + plain CLI."""
    if item.kind == "prompt":
        return item.text or ""
    if item.arg:
        return f"{item.tool} · {item.arg}"
    return item.tool or (item.name or "?")
