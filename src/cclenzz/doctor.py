from __future__ import annotations

"""doctor — the only diagnostic/offline command. Output format preserved
line-for-line; ``paths``/``settings`` are injected so config values affect it."""

import glob
import os
import shutil
import subprocess
import sys
import time

from . import VERSION
from .ansi import _ansi, _reset
from .textutil import fmt_idle


def cmd_doctor(caps, paths, settings, out=sys.stdout):
    def line(ok, label, value):
        prefix = "  "
        if ok:
            out.write(f"{prefix}{label:<15} {value}\n")
        else:
            c = _ansi(caps, "error", out.isatty())
            out.write(f"{prefix}{c}{label:<15} {value}{_reset(out.isatty())}\n")

    py = ".".join(str(x) for x in sys.version_info[:3])
    out.write(f"cclenzz {VERSION} · python {py} · {sys.platform}\n")

    session_paths = glob.glob(paths.projects_glob)
    if session_paths:
        newest = max(session_paths, key=lambda p: os.path.getmtime(p))
        age = fmt_idle(os.path.getmtime(newest), time.time())
        line(True, "sessions glob", f"{paths.projects_glob}   ({len(session_paths)} files, newest {age} ago)")
    else:
        line(False, "sessions glob", f"{paths.projects_glob}   (no files — start a Claude Code session)")

    mouse = "mouse " + ("✓" if caps.mouse else "✗")
    osc8 = "osc8 " + ("✓" if caps.osc8 else "✗")
    line(True, "terminal",
         f"{caps.term or '?'} · {caps.color} · {caps.glyphs} · {mouse} · {osc8}")
    line(True, "theme", f"{caps.bg}")

    cb = shutil.which(settings.claude_bin)
    if cb:
        ver = "?"
        try:
            r = subprocess.run([settings.claude_bin, "--version"], capture_output=True,
                               text=True, timeout=10)
            ver = (r.stdout or r.stderr or "?").strip().splitlines()[0] if (r.stdout or r.stderr) else "?"
        except Exception:
            ver = "?"
        line(True, "claude binary", f"{cb} ({ver})")
    else:
        line(False, "claude binary", f"`{settings.claude_bin}` not found on PATH — audit unavailable")

    line(True, "audit model", settings.audit_model)
    line(True, "explain model", settings.explain_model)

    cfg = paths.config_path
    if os.path.exists(cfg):
        line(True, "config file", cfg)
    else:
        line(True, "config file", f"{cfg} (not present — run cclenzz setup)")

    root = paths.state_root
    if not settings.persist:
        line(True, "state dir", f"{root}   (persistence disabled)")
    else:
        sidecars = glob.glob(os.path.join(root, "sessions", "*", "*.json"))
        total = 0
        for p in sidecars:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
        # writable if the root exists and is writable, or its parent is (we can
        # create it lazily on first write).
        probe = root if os.path.isdir(root) else os.path.dirname(root) or "."
        writable = os.access(probe, os.W_OK)
        kib = total / 1024.0
        line(writable, "state dir",
             f"{root}   ({'writable' if writable else 'NOT writable'}, "
             f"{len(sidecars)} sidecars, {kib:.1f} KiB)")
