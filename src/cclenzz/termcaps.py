from __future__ import annotations

"""§2 Terminal capability model — detected once at startup into a frozen record.

Everything downstream renders the best version the terminal supports. ``curses``
is imported lazily inside ``detect_caps`` (for ``tigetnum``) so importing this
module never requires curses and stays 3.9-import-safe.
"""

import os
import re
import sys


class Caps:
    """Frozen capability record. All rendering reads this; nothing probes the
    terminal mid-frame."""
    __slots__ = ("color", "glyphs", "ambiwidth", "mouse", "osc8", "osc52",
                 "title", "bg", "is_tty", "term", "term_program",
                 "curses_colors", "can_change")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def _in_multiplexer():
    term = os.environ.get("TERM", "")
    return bool(os.environ.get("TMUX")) or term.startswith("screen") or term.startswith("tmux")


def _detect_icons_tier():
    """The glyph tier auto-detection resolves to (unicode on a UTF-8 locale, else
    ascii). Nerd is opt-in only, never auto-detected."""
    utf8 = "utf-8" in (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE")
                       or os.environ.get("LANG") or "").lower()
    return "unicode" if utf8 else "ascii"


def detect_caps(cfg):
    """Run capability detection once, honoring the config dict's overrides
    (`theme`, `icons`, `color`, `ambiwidth`). This must never block startup beyond
    a single 50 ms OSC 11 window (which we skip in a multiplexer / non-tty)."""
    is_tty = sys.stdout.isatty()
    term = os.environ.get("TERM", "") or ""
    term_program = os.environ.get("TERM_PROGRAM", "") or ""

    # --- color --- (terminal-standard env vars are detection inputs, not knobs)
    no_color = os.environ.get("NO_COLOR") is not None
    clicolor_force = os.environ.get("CLICOLOR_FORCE") not in (None, "0")
    colorterm = (os.environ.get("COLORTERM") or "").lower()
    color_cfg = cfg.get("color", "auto")
    ncolors = 0
    if is_tty:
        try:
            import curses
            curses.setupterm()
            ncolors = curses.tigetnum("colors") or 0
        except Exception:
            ncolors = 256 if "256" in term else 8
    if no_color:
        color = "mono"
    elif colorterm in ("truecolor", "24bit"):
        color = "rgb"
    elif ncolors >= 256:
        color = "c256"
    elif ncolors >= 8 or clicolor_force:
        color = "c16"
    else:
        color = "mono"
    if clicolor_force and color == "mono" and not no_color:
        color = "c16"
    # config `color`: `never` forces mono; `always` guarantees at least c16 (but
    # NO_COLOR still wins — it's a terminal-standard contract, not a cclenzz knob).
    if color_cfg == "never":
        color = "mono"
    elif color_cfg == "always" and color == "mono" and not no_color:
        color = "c16"

    # --- glyphs ---
    icons_cfg = cfg.get("icons", "auto")
    if icons_cfg in ("nerd", "unicode", "ascii"):
        glyphs = icons_cfg
    else:
        glyphs = _detect_icons_tier()

    # --- ambiwidth ---
    ambiwidth = 2 if (cfg.get("ambiwidth") == 2) else 1

    # --- mouse: always on when tty ---
    mouse = is_tty

    # --- osc8 hyperlinks: auto-detect only ---
    osc8 = (term_program in ("iTerm.app", "WezTerm", "ghostty")
            or term.startswith("xterm-kitty"))
    if _in_multiplexer():
        osc8 = False

    # --- osc52 clipboard: always on ---
    osc52 = True

    # --- title ---
    title = is_tty and term != "dumb"

    # --- background theme ---
    theme = cfg.get("theme")
    if theme in ("dark", "light"):
        bg = theme
    elif _in_multiplexer() or not is_tty:
        bg = "dark"
    else:
        bg = _query_bg_osc11()

    return Caps(color=color, glyphs=glyphs, ambiwidth=ambiwidth, mouse=mouse,
                osc8=osc8, osc52=osc52, title=title, bg=bg, is_tty=is_tty,
                term=term, term_program=term_program, curses_colors=ncolors,
                can_change=False)


def _query_bg_osc11():
    """Query the terminal background with OSC 11, 50 ms timeout. Assume dark on
    any failure. Only called on a real tty outside a multiplexer."""
    try:
        import termios
        import select
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] = new[3] & ~(termios.ICANON | termios.ECHO)
        termios.tcsetattr(fd, termios.TCSANOW, new)
        try:
            sys.stdout.write("\033]11;?\033\\")
            sys.stdout.flush()
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                return "dark"
            resp = os.read(fd, 64).decode("latin-1", "replace")
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, old)
        m = re.search(r"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", resp)
        if not m:
            return "dark"
        def chan(s):
            v = int(s[:2], 16)
            return v
        r_, g_, b_ = chan(m.group(1)), chan(m.group(2)), chan(m.group(3))
        lum = 0.299 * r_ + 0.587 * g_ + 0.114 * b_
        return "light" if lum > 128 else "dark"
    except Exception:
        return "dark"
