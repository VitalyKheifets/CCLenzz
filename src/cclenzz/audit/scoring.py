from __future__ import annotations

"""Intent-audit score ranges — the single source of truth (unchanged from v1).
cclenzz, not the model, maps raw scores to labels."""

ALIGN_BANDS = [(85, "aligned", "cat.edit"),
               (60, "partial", "warn"),
               (0,  "drift",   "error")]
CONF_LOW = 70


def label_for(align):
    """Map an alignment score (0–100) to (label, colour-token) via ALIGN_BANDS."""
    try:
        align = int(align)
    except (TypeError, ValueError):
        align = 0
    for thr, label, colour in ALIGN_BANDS:
        if align >= thr:
            return label, colour
    return ALIGN_BANDS[-1][1], ALIGN_BANDS[-1][2]


def dim_for(conf):
    """True when a verdict's confidence is low enough to render dimmed."""
    try:
        return int(conf) < CONF_LOW
    except (TypeError, ValueError):
        return True
