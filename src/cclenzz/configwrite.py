from __future__ import annotations

"""Config-file rendering + the shared atomic text writer.

``_atomic_write_text`` lives here (Layer 1) rather than in ``persist.py`` so both
the config writer and the sidecar cache can share one implementation while
imports still only point downward (``persist`` imports it from here)."""

import os
import re

CONFIG_TEMPLATE = """\
# cclenzz — config
# This file is the ONLY way to configure cclenzz (no flags, no env vars).
# Re-run the wizard any time with:  cclenzz setup
# Uncomment a line to override its built-in default.

# --- appearance (set by the wizard) ---
theme = "{theme}"          # auto | dark | light
icons = "{icons}"          # auto | nerd | unicode | ascii
color = "{color}"          # auto | always | never

# --- intent audit (set by the wizard) ---
auto_audit = {auto_audit}  # true: audit every new prompt automatically (costs money)

# --- models ---
#audit_model = "opus"      # model for the intent audit (a key / Auto mode)
#explain_model = "haiku"   # model for the per-item explain feature (? key)

# --- behavior ---
#interval = 1.0            # live poll interval, seconds
#ambiwidth = 1             # 2 if your terminal renders ambiguous-width glyphs wide

# --- paths ---
#projects_glob = "~/.claude/projects/*/*.jsonl"   # where sessions are read from
#claude_bin = "claude"     # the claude CLI used for audit/explain calls

# --- persistence (~/.cclenzz) ---
#persist = true            # cache audit/explain results to JSON sidecars
#state_retention_days = 30 # prune cached results older than this
"""

# Config keys the wizard does NOT set. On a `setup` re-run, any of these that
# carried an explicit value in the pre-existing config is emitted uncommented.
CONFIG_OPTIONAL_KEYS = ("audit_model", "explain_model", "interval", "ambiwidth",
                        "projects_glob", "claude_bin", "persist",
                        "state_retention_days")


def _atomic_write_text(path, text):
    """Write text via tmp in the same dir -> fsync -> os.replace (atomic). Files
    are owner-only (0o600), dirs owner-only (0o700). Raises on failure — callers
    that must not crash wrap this (e.g. _atomic_write_json)."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(v)


def write_config(answers, existing_cfg, config_path):
    """Render CONFIG_TEMPLATE with the wizard's answers active, preserving any
    non-wizard key that had an explicit value in the pre-existing config (emitted
    uncommented). Writes atomically; returns the config path."""
    text = CONFIG_TEMPLATE.format(
        theme=answers["theme"], icons=answers["icons"], color=answers["color"],
        auto_audit=("true" if answers["auto_audit"] else "false"))
    existing_cfg = existing_cfg or {}
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^#(\w+) = (.*?)( +#.*)?$", line)
        if not m:
            continue
        key = m.group(1)
        if key in CONFIG_OPTIONAL_KEYS and key in existing_cfg:
            comment = (m.group(3) or "").strip()
            new_line = f"{key} = {_toml_value(existing_cfg[key])}"
            if comment:
                new_line += "  " + comment
            lines[i] = new_line
    path = config_path
    _atomic_write_text(path, "\n".join(lines))
    return path
