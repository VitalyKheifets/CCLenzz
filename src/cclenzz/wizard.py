from __future__ import annotations

"""First-run setup wizard (FEATURE-setup-wizard.md §4-§5).

The raw-mode byte reads are factored behind a ``KeyReader`` seam (§5.5) so the
selection logic is testable with a scripted reader; all drawing (ANSI escapes,
cursor hide/show, erase-on-exit) is unchanged. The wizard is pure UI — it writes
no files (the caller writes via ``write_config``)."""

import os
import sys
from typing import Protocol

from .ansi import _ansi, _reset
from .glyphs import glyph
from .termcaps import Caps, _detect_icons_tier, detect_caps


def _tilde(path):
    """Render an absolute path with the home dir collapsed to ~ for display."""
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


class KeyReader(Protocol):
    def __enter__(self): ...
    def __exit__(self, *a): ...
    def read_key(self) -> str: ...


class RawTtyKeyReader:
    """Raw-mode terminal reader: enters cbreak/raw on ``__enter__`` and restores
    on ``__exit__``. ``read_key`` returns a symbolic token
    ("up"|"down"|"enter"|"abort"|"1".."9"|"other"), including the Esc-alone vs
    escape-sequence 50 ms disambiguation."""

    def __enter__(self):
        import termios
        import tty
        self._termios = termios
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setraw(self._fd)
        return self

    def __exit__(self, *a):
        self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old)

    def read_key(self):
        import select as _select
        fd = self._fd
        b = os.read(fd, 1)
        if not b:
            return "other"
        c = b[0]
        if c == 3 or c == ord("q"):              # Ctrl-C / q → abort
            return "abort"
        if c == 27:                              # Esc alone, or an escape seq
            r, _, _ = _select.select([fd], [], [], 0.05)
            if not r:
                return "abort"
            seq = os.read(fd, 2)
            if seq[:1] == b"[":
                k = seq[1:2]
                if k == b"A":
                    return "up"
                if k == b"B":
                    return "down"
            return "other"
        if c == ord("k"):
            return "up"
        if c == ord("j"):
            return "down"
        if ord("1") <= c <= ord("9"):
            return chr(c)
        if c in (10, 13):                        # Enter → confirm
            return "enter"
        return "other"


def _caps_with(caps, **over):
    kw = {k: getattr(caps, k) for k in caps.__slots__}
    kw.update(over)
    return Caps(**kw)


def _wizard_select(title, options, default_index, caps, use_color, samples=None,
                   reader=None):
    """Raw-mode single-choice picker rendered inline with ANSI escapes, in the
    `claude` onboarding style. `options` are (value, label, preview) tuples.
    `samples`, when given, is a list parallel to `options`; each entry is a list
    of already-rendered lines shown in a live panel below the options that
    updates as the cursor moves. Returns the chosen index, or None on abort
    (Ctrl-C / q / Esc)."""
    n = len(options)
    idx = max(0, min(default_index, n - 1))
    accent = _ansi(caps, "accent", use_color)
    dim = _ansi(caps, "fg.dim", use_color)
    reset = _reset(use_color)
    cursor = "❯" if (use_color and caps.glyphs != "ascii") else ">"
    labelw = max(len(lbl) for _, lbl, _ in options)
    sample_h = max((len(b) for b in samples), default=0) if samples else 0
    # title + blank + options (+ blank + "sample:" label + sample_h lines)
    total = 2 + n + ((2 + sample_h) if sample_h else 0)

    # raw mode disables NL->CRLF translation, so every line is positioned
    # explicitly: \r (column 0) + \033[2K (erase line) + text + \r\n.
    def draw(first):
        parts = []
        if not first:
            parts.append(f"\033[{total}A")          # move up to the title line
        parts.append("\r\033[2K   " + title + "\r\n")
        parts.append("\r\033[2K\r\n")
        for i, (_val, lbl, prev) in enumerate(options):
            mark = (accent + cursor + reset) if i == idx else " "
            row = f"   {mark} {i + 1}. {lbl:<{labelw}}"
            if prev:
                row += "   " + prev
            parts.append("\r\033[2K" + row + "\r\n")
        if sample_h:
            parts.append("\r\033[2K\r\n")
            parts.append("\r\033[2K   " + dim + "sample:" + reset + "\r\n")
            block = samples[idx] if idx < len(samples) else []
            for j in range(sample_h):
                txt = ("     " + block[j]) if j < len(block) else ""
                parts.append("\r\033[2K" + txt + "\r\n")
        sys.stdout.write("".join(parts))
        sys.stdout.flush()

    if reader is None:
        reader = RawTtyKeyReader()
    sys.stdout.write("\033[?25l")                    # hide cursor
    sys.stdout.flush()
    reader.__enter__()
    try:
        draw(True)
        while True:
            key = reader.read_key()
            if key == "abort":
                idx = None
                break
            elif key == "up":
                idx = (idx - 1) % n
                draw(False)
            elif key == "down":
                idx = (idx + 1) % n
                draw(False)
            elif key == "enter":
                break
            elif key and key.isdigit():
                d = int(key)
                if 1 <= d <= n:
                    idx = d - 1
                    draw(False)
    finally:
        sys.stdout.write(f"\033[{total}A\r\033[J")   # erase the picker block
        sys.stdout.write("\033[?25h")                # show cursor
        sys.stdout.flush()
        reader.__exit__(None, None, None)
    return idx


def run_wizard(existing_cfg, config_path):
    """The 4-question first-run wizard. Pure UI — writes no files. Returns the
    answers dict, or None on abort. `existing_cfg` preselects each question."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    existing_cfg = existing_cfg or {}
    caps = detect_caps({})
    use_color = caps.color != "mono"
    ascii_only = caps.glyphs == "ascii"
    accent = _ansi(caps, "accent", use_color)
    reset = _reset(use_color)
    bullet = "*" if ascii_only else "✻"
    chk = "+" if ascii_only else "✔"
    nav = ("up/down or j/k to move, 1-9 to jump, Enter to select, Ctrl-C to quit"
           if ascii_only else
           "↑/↓ or j/k to move · 1-9 to jump · Enter to select · Ctrl-C to quit")

    sys.stdout.write("\n")
    sys.stdout.write(f" {accent}{bullet} Welcome to cclenzz{reset}\n\n")
    sys.stdout.write(f"   Let's set up your config ({_tilde(config_path)}).\n")
    sys.stdout.write(f"   {nav}\n\n")
    sys.stdout.flush()

    def col(c, uc, token, text):
        return _ansi(c, token, uc) + text + _reset(uc)

    detected = _detect_icons_tier()

    # A tool-line + verdict-line sample rendered against a given Caps + color
    # mode — the shared vocabulary for the theme/icons/color live previews.
    def sample_block(c, uc):
        dot = "*" if c.glyphs == "ascii" else "●"
        okg = "+" if c.glyphs == "ascii" else "✔"
        wg = "!" if c.glyphs == "ascii" else "‼"
        bad = "x" if c.glyphs == "ascii" else "✖"
        prm = glyph("prompt", c)
        return [
            col(c, uc, "cat.prompt", f"{prm} a user prompt"),
            "  ".join(col(c, uc, "cat." + k, f"{glyph(k, c)} {tool}") for k, tool in
                      (("read", "Read"), ("edit", "Edit"), ("bash", "Bash"),
                       ("agent", "Task"))),
            (col(c, uc, "ok", f"{okg} aligned") + "   "
             + col(c, uc, "warn", f"{wg} partial") + "   "
             + col(c, uc, "error", f"{bad} drift")),
        ]

    # ---- Q1 theme -----------------------------------------------------------
    def theme_caps(value):
        if value in ("dark", "light"):
            return _caps_with(caps, bg=value)
        return caps                     # auto → the detected background
    theme_opts = [
        ("auto", "Auto", "detect from the terminal background   (recommended)"),
        ("dark", "Dark", "dark-background palette"),
        ("light", "Light", "light-background palette"),
    ]
    theme_samples = [sample_block(theme_caps(v), use_color) for v, _, _ in theme_opts]
    i = _wizard_select("Theme — colors used by the TUI", theme_opts,
                       _default_idx(theme_opts, existing_cfg.get("theme"), 0),
                       caps, use_color, samples=theme_samples)
    if i is None:
        return None
    theme = theme_opts[i][0]

    # ---- Q2 icons -----------------------------------------------------------
    def icon_caps(value):
        return _caps_with(caps, glyphs=(detected if value == "auto" else value))
    icon_opts = [
        ("auto", "Auto", f"detect from your locale   (detected: {detected})"),
        ("nerd", "Nerd", "Nerd Font glyphs"),
        ("unicode", "Unicode", "Unicode symbols"),
        ("ascii", "ASCII", "plain ASCII"),
    ]
    icon_samples = [sample_block(icon_caps(v), use_color) for v, _, _ in icon_opts]
    i = _wizard_select("Icons — glyph set for tool lines", icon_opts,
                       _default_idx(icon_opts, existing_cfg.get("icons"), 0),
                       caps, use_color, samples=icon_samples)
    if i is None:
        return None
    icons = icon_opts[i][0]

    # ---- Q3 color -----------------------------------------------------------
    # never → monochrome sample; always/auto → colored (if the terminal can).
    def color_sample(value):
        if value == "never":
            return sample_block(_caps_with(caps, color="mono"), False)
        return sample_block(caps, use_color)
    color_opts = [
        ("auto", "Auto", "detect from the terminal   (recommended)"),
        ("always", "Always", "force color on"),
        ("never", "Never", "monochrome output"),
    ]
    color_samples = [color_sample(v) for v, _, _ in color_opts]
    i = _wizard_select("Color output", color_opts,
                       _default_idx(color_opts, existing_cfg.get("color"), 0),
                       caps, use_color, samples=color_samples)
    if i is None:
        return None
    color = color_opts[i][0]

    # ---- Q4 auto_audit ------------------------------------------------------
    audit_opts = [
        ("off", "Off", "recommended — audit on demand with the `a` key"),
        ("on", "On", "runs claude -p on every new prompt (costs money)"),
    ]
    audit_default = 1 if existing_cfg.get("auto_audit") else 0
    i = _wizard_select(
        "Auto-audit — run the LLM intent audit automatically on each new prompt "
        "(calls `claude -p`; costs money)", audit_opts, audit_default,
        caps, use_color)
    if i is None:
        return None
    auto_audit = (audit_opts[i][0] == "on")

    summary = "   ".join([
        f"{accent}{chk}{reset} Theme: {theme}",
        f"{accent}{chk}{reset} Icons: {icons}",
        f"{accent}{chk}{reset} Color: {color}",
        f"{accent}{chk}{reset} Auto-audit: {'on' if auto_audit else 'off'}",
    ])
    sys.stdout.write("\n " + summary + "\n")
    sys.stdout.flush()
    return {"theme": theme, "icons": icons, "color": color,
            "auto_audit": auto_audit}


def _default_idx(options, value, fallback):
    for i, (v, _lbl, _prev) in enumerate(options):
        if v == value:
            return i
    return fallback
