from __future__ import annotations

"""Shelling out from the TUI: clipboard, pager, and editor. The only ``ui``
module besides ``jobs``/``doctor`` that spawns subprocesses."""

import os
import subprocess

from ..detail import item_detail_text
from .tabstate import Toast


def _copy_clipboard(text, caps):
    for tool in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["wl-copy"]):
        if _which(tool[0]):
            try:
                p = subprocess.run(tool, input=text, text=True, timeout=5)
                if p.returncode == 0:
                    return tool[0]
            except Exception:
                pass
    if caps.osc52:
        try:
            import base64
            b = base64.b64encode(text.encode("utf-8")).decode("ascii")
            with open("/dev/tty", "w") as tty:
                tty.write(f"\033]52;c;{b}\007")
                tty.flush()
            return "osc52"
        except Exception:
            pass
    return "no clipboard"


def _which(name):
    import shutil
    return shutil.which(name)


def shlex_quote(s):
    try:
        import shlex
        return shlex.quote(s)
    except Exception:
        return "'" + s.replace("'", "'\\''") + "'"


def _suspend_run(stdscr, curses, cmd, text):
    """Suspend curses, run a shell command (optionally feeding it `text` via a
    temp file passed as the pager's input), then restore the TUI."""
    try:
        curses.def_prog_mode()
        curses.endwin()
        if text is not None:
            import tempfile
            fd, path = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
            try:
                subprocess.run(f"{cmd} {shlex_quote(path)}", shell=True)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        else:
            subprocess.run(cmd, shell=True)
    except Exception:
        pass
    finally:
        try:
            curses.reset_prog_mode()
            stdscr.refresh()
        except Exception:
            pass


def open_pager(stdscr, curses, item, cwd):
    blocks = item_detail_text(item, cwd)
    buf = []
    for lbl, txt in blocks:
        buf.append(f"== {lbl} ==")
        buf.append(txt or "")
        buf.append("")
    text = "\n".join(buf)
    pager = os.environ.get("PAGER", "less -R")
    _suspend_run(stdscr, curses, pager, text)


def open_editor(stdscr, curses, item):
    inp = item.input or {}
    path = inp.get("file_path") or inp.get("notebook_path")
    if not path:
        return Toast("no file to open", "warn")
    editor = os.environ.get("EDITOR", "vi")
    _suspend_run(stdscr, curses, f"{editor} {shlex_quote(path)}", None)
    return None
