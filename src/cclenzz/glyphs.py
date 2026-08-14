from __future__ import annotations

"""§3.1 Glyph system — one cell per glyph, three tiers (nerd / unicode / ascii).

Every glyph occupies exactly one cell in its tier. The unicode tier uses only
East-Asian Narrow or Ambiguous codepoints; ambiguous glyphs (in AMBI_KEYS)
fall back to their ascii form *individually* when Caps.ambiwidth == 2 — never
the whole tier. Nerd glyphs are Private-Use codepoints; they only appear on
explicit ``--icons nerd`` opt-in and degrade to tofu if the font lacks them.
"""

import time

from .termcaps import Caps

GLYPHS = {
    # meaning:          (nerd,             unicode, ascii)
    "prompt":           ("❯",         "❯", ">"),   # ❯
    "read":             ("\U000f0214",     "≡", "="),   # ≡
    "edit":             ("\U000f0dc8",     "±", "~"),   # ±
    "bash":             ("",         "$",      "$"),
    "search":           ("",         "∗", "*"),   # ∗
    "mcp":              ("\U000f043b",     "◆", "%"),   # ◆
    "agent":            ("\U000f06a9",     "◉", "@"),   # ◉
    "web":              ("\uf0ac",         "↗", "^"),   # ↗
    "skill":            ("\U000f0a66",     "§", "&"),   # §
    "artifact":         ("\uf1fc",         "◇", "+"),   # ◇
    "other":            ("·",         "·", "."),   # ·
    "error":            ("✗",         "✗", "x"),   # ✗
    "flagged":          ("‼",         "‼", "!"),   # ‼
    "live":             ("●",         "●", "*"),   # ●
    "paused":           ("○",         "○", "o"),   # ○
    "err_dot":          ("●",         "●", "*"),   # ● (error-colored)
    "expanded":         ("▾",         "▾", "v"),   # ▾
    "collapsed":        ("▸",         "▸", ">"),   # ▸
    "selbar":           ("▍",         "▍", "|"),   # ▍
    "badge":            ("⟐",         "⟐", "*"),   # ⟐ (audit badge)
    # tree guides
    "g_v":              ("│",         "│", "|"),   # │
    "g_t":              ("├",         "├", "|"),   # ├
    "g_l":              ("╰",         "╰", "\\"),  # ╰
    "g_h":              ("─",         "─", "-"),   # ─
    "arr_l":            ("‹",         "‹", "<"),   # ‹
    "arr_r":            ("›",         "›", ">"),   # ›
    "sb_track":         ("░",         "░", "."),   # ░
    "sb_thumb":         ("▐",         "▐", "#"),   # ▐
    "rule":             ("─",         "─", "-"),   # ─
    "warn":             ("‼",         "‼", "!"),
    "newchip":          ("↓",         "↓", "v"),   # ↓
    "explain":          ("\U000f0335", "?", "?"),   #  (nerd lightbulb) / ? / ?
}

# Glyphs marked ᴬ in §3.1 — East-Asian Ambiguous; downgrade under ambiwidth=2.
AMBI_KEYS = {"mcp", "agent", "web", "artifact", "error", "live", "paused",
             "err_dot", "expanded", "collapsed"}

SPINNER_UNICODE = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_ASCII = "|/-\\"

# Category -> glyph key.
CAT_GLYPH = {
    "prompt": "prompt", "read": "read", "edit": "edit", "bash": "bash",
    "search": "search", "mcp": "mcp", "agent": "agent", "web": "web",
    "skill": "skill", "artifact": "artifact", "other": "other",
}


# The CAPS fallback default (§4): used only as the default when a caps record is
# not supplied to the glyph/text helpers below. cclenzz never mutates it.
CAPS = Caps(color="c256", glyphs="unicode", ambiwidth=1, mouse=False,
            osc8=False, osc52=True, title=False, bg="dark", is_tty=False,
            term="", term_program="", curses_colors=256, can_change=False)


def glyph(key, caps=None):
    caps = caps or CAPS
    tier = caps.glyphs
    trio = GLYPHS.get(key)
    if not trio:
        return "?"
    g = trio[0] if tier == "nerd" else (trio[1] if tier == "unicode" else trio[2])
    if tier != "ascii" and caps.ambiwidth == 2 and key in AMBI_KEYS:
        return trio[2]
    return g


def spinner_frame(caps=None, now=None):
    caps = caps or CAPS
    if now is None:
        now = time.time()
    frames = SPINNER_ASCII if caps.glyphs == "ascii" else SPINNER_UNICODE
    idx = int(now * 10) % len(frames)
    return frames[idx]


def u(uni, asc, caps=None):
    """Pick a Unicode literal or its ascii fallback for the active glyph tier."""
    caps = caps or CAPS
    return asc if caps.glyphs == "ascii" else uni


def sep(caps=None):
    return u("·", "|", caps)


def ell(caps=None):
    return u("…", "...", caps)


def cli_glyph(cat, caps=None):
    """Unicode-tier glyph for plain output regardless of caps."""
    caps = caps or CAPS
    key = CAT_GLYPH.get(cat, "other")
    return GLYPHS[key][1] if caps.glyphs != "ascii" else GLYPHS[key][2]
