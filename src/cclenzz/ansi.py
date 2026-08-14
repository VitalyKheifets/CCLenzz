from __future__ import annotations

"""§3.2 Color tokens (truecolor values + mandated 256/16 fallbacks) and the
ANSI colorizers shared by ``doctor`` and the setup wizard."""

# token -> (rgb_dark, rgb_light|None, c256_dark, c256_light|None,
#           c16_color_name, c16_extra)
RGB_ = {
    "fg":         ("#c8ccd4", "#333a45", 251, 237, "default", ""),
    "fg.dim":     ("#8a919e", "#767e8a", 245, None, "white", "DIM"),
    "fg.faint":   ("#565d6a", "#a8aeb8", 240, 248, "white", "DIM"),
    "accent":     ("#7aa2f7", "#2a5adf", 111, 26,  "blue", "BOLD"),
    "cat.read":   ("#56b6c2", "#0e7f8b", 73,  30,  "cyan", ""),
    "cat.edit":   ("#98c379", "#3d8a2e", 114, 28,  "green", ""),
    "cat.bash":   ("#e5c07b", "#9a6a00", 179, 136, "yellow", ""),
    "cat.search": ("#61afef", "#1a6fd4", 75,  32,  "blue", ""),
    "cat.mcp":    ("#c678dd", "#8a2fb8", 176, 91,  "magenta", ""),
    "cat.agent":  ("#d3869b", "#b0356a", 175, 132, "magenta", "BOLD"),
    "cat.web":    ("#7dcfff", "#0a7ec2", 117, 31,  "cyan", ""),
    "cat.skill":  ("#a9b665", "#6b7f1e", 143, 100, "green", ""),
    "cat.other":  ("#8a919e", "#767e8a", 245, None, "white", "DIM"),
    "cat.artifact": ("#8a919e", "#767e8a", 245, None, "white", "DIM"),
    "cat.prompt": ("#7aa2f7", "#2a5adf", 111, 26,  "blue", "BOLD"),
    "error":      ("#e06c75", "#c22b36", 168, 160, "red", ""),
    "warn":       ("#e5c07b", "#9a6a00", 179, 136, "yellow", ""),
    "ok":         ("#98c379", "#3d8a2e", 114, 28,  "green", ""),
    "sel.bg":     ("#2b3245", "#dde6f7", 237, 189, None, ""),
    "diff.add.bg": ("#20303b", "#e2f0e0", 236, 194, None, ""),
    "diff.del.bg": ("#37222c", "#f7e2e4", 236, 224, None, ""),
}


def _hex_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _ansi(caps, token, use_color):
    """SGR escape for a token when colorizing non-TTY output."""
    if not use_color:
        return ""
    spec = RGB_.get(token)
    if not spec:
        return ""
    if caps.color == "rgb":
        h = spec[0] if caps.bg != "light" or spec[1] is None else spec[1]
        r, g, b = _hex_rgb(h)
        return f"\033[38;2;{r};{g};{b}m"
    if caps.color == "c256":
        idx = spec[2] if caps.bg != "light" or spec[3] is None else spec[3]
        return f"\033[38;5;{idx}m"
    if caps.color == "c16":
        base = {"default": 39, "black": 30, "red": 31, "green": 32, "yellow": 33,
                "blue": 34, "magenta": 35, "cyan": 36, "white": 37}.get(spec[4], 39)
        bold = ";1" if "BOLD" in spec[5] else (";2" if "DIM" in spec[5] else "")
        return f"\033[{base}{bold}m"
    return ""


def _reset(use_color):
    return "\033[0m" if use_color else ""
