from __future__ import annotations

"""cclenzz — Claude Code Monitor.

The flight recorder + heads-up display for Claude Code. ``cclenzz`` opens the
newest Claude Code session in a live, navigable tabbed view — each tool call and
prompt is one line, read straight from the session's JSONL file. New sessions
open automatically as tabs. An LLM "intent audit" scores, per prompt, whether the
actions matched intent (see ``docs/DESIGN.md``,
``docs/FEATURE-setup-wizard.md``).

Command surface: ``cclenzz`` (TUI, runs a first-run setup wizard when no config
exists), ``cclenzz setup``, ``cclenzz doctor``, ``cclenzz update``
(``--snapshot`` / ``--stable``), ``--version``, ``-h/--help``. Apart from the
update channel flags there are no tuning flags and no environment variables —
the ONLY configuration surface is ``~/.cclenzz/config.toml``. Python >= 3.11 is
required (for tomllib).

This module is the single composition root: it builds the frozen ``AppPaths`` /
``Settings`` / ``Caps`` records and the ``ClaudeCliJudge`` once, then passes them
down. The ``paths`` / ``judge`` keyword-only parameters exist for in-process
tests, never on the command line."""

import argparse
import os
import sys

from . import VERSION
from .config import Settings, load_config
from .configwrite import write_config
from .doctor import cmd_doctor
from .paths import AppPaths
from .persist import prune_state
from .sessions import (LIVE_MINUTES_DEFAULT, MAX_SESSIONS_DEFAULT,
                       discover_sessions)
from .termcaps import detect_caps
from .wizard import _tilde, run_wizard


def main(argv=None, *, paths=None, judge=None):
    # 1. Python version gate — tomllib requires 3.11 (no silent skip anymore).
    if sys.version_info < (3, 11):
        sys.stderr.write("cclenzz: Python >= 3.11 required (for tomllib)\n")
        return 1

    argv = sys.argv[1:] if argv is None else argv

    # 2a. `update` carries its own flag surface (--snapshot/--stable) and touches
    # neither config nor the terminal, so it is dispatched ahead of the general
    # parser. It is stdlib-only and network-facing; see update.py.
    if argv and argv[0] == "update":
        from .update import cmd_update
        return cmd_update(argv[1:])

    # 2b. Minimal command surface: one positional in {setup, doctor} + --version.
    parser = argparse.ArgumentParser(
        prog="cclenzz", add_help=True,
        description="Live tabbed view of Claude Code sessions. No command: launch "
                    "the TUI (first run starts a setup wizard).")
    parser.add_argument("command", nargs="?", default=None,
                        help="setup | doctor | update  (no command: launch the TUI)")
    parser.add_argument("--version", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1

    cmd = args.command
    if cmd is not None and cmd not in ("setup", "doctor"):
        sys.stderr.write(f"cclenzz: unknown command {cmd!r}\n")
        sys.stderr.write("usage: cclenzz [setup | doctor | update] [--version]\n")
        return 1

    # 3. --version
    if args.version:
        print(f"cclenzz {VERSION}")
        return 0

    if paths is None:
        paths = AppPaths.default()

    # 4. config (hard error on malformed TOML; {} when the file is absent)
    cfg = load_config(paths.config_path)
    have_config = os.path.exists(paths.config_path)

    # 5. wizard trigger (§4.1)
    if cmd == "setup":
        answers = run_wizard(cfg, paths.config_path)
        if answers is None:
            return 130
        path = write_config(answers, cfg, paths.config_path)
        print(f"Config written to {_tilde(path)} — run cclenzz to start.")
        return 0
    if not have_config and cmd != "doctor":
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            sys.stderr.write("cclenzz: no config found — run cclenzz in an "
                             "interactive terminal to set up\n")
            return 2
        answers = run_wizard(cfg, paths.config_path)
        if answers is None:
            return 130
        path = write_config(answers, cfg, paths.config_path)
        sys.stdout.write(f"\n Config written to {_tilde(path)}\n")
        sys.stdout.write(" Everything else (models, intervals, paths) is in "
                         "there, commented out.\n")
        sys.stdout.write("\n Starting cclenzz…\n")
        sys.stdout.flush()
        cfg = load_config(paths.config_path)   # reload the file we just wrote

    # apply config → frozen records (config value → built-in default, nothing else)
    settings = Settings.from_config(cfg)
    if cfg.get("projects_glob"):
        paths = paths.with_projects_glob(cfg["projects_glob"])

    # 6. capabilities
    caps = detect_caps(cfg)

    if judge is None:
        from .audit.judge import ClaudeCliJudge
        judge = ClaudeCliJudge(settings.claude_bin, settings.audit_model,
                               settings.explain_model)

    # 7. doctor
    if cmd == "doctor":
        cmd_doctor(caps, paths, settings)
        return 0

    # 8. the TUI requires an interactive terminal (§3.5.3)
    interactive = (sys.stdin.isatty() and sys.stdout.isatty()
                   and os.environ.get("TERM") != "dumb")
    if not interactive:
        sys.stderr.write("cclenzz: interactive terminal required\n")
        return 2

    # 9. prune, discover, empty-card-or-tabs
    from .ui.tui import _run_empty_then_tabs, run_tabs
    prune_state(paths, settings)     # startup-only orphan/age prune of sidecars (§9)
    sessions = discover_sessions(paths, MAX_SESSIONS_DEFAULT, fast=True)
    if not sessions:
        _run_empty_then_tabs(caps, paths, settings, judge)
        return 0

    sessions[0].read_meta()   # full read for the first tab
    run_tabs(sessions[0], caps, paths, settings, judge, follow=True,
             live_minutes=LIVE_MINUTES_DEFAULT, max_sessions=MAX_SESSIONS_DEFAULT)
    return 0
