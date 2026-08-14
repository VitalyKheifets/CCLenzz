"""Unit tests for cclenzz.textutil — width, truncation, durations, clocks."""

import pytest

from cclenzz.textutil import (
    char_w,
    clip_cells,
    disp_w,
    fmt_dur,
    fmt_idle,
    iso_ts,
    parse_ts,
    trunc_end,
    trunc_mid,
)

COMBINING = "́"   # combining acute accent (zero width)
CJK = "日"          # 日 (wide, 2 cells)
AMBI = "※"         # ※ ambiguous width


def test_char_w_ascii():
    assert char_w("a") == 1
    assert char_w(" ") == 1


def test_char_w_combining_is_zero():
    assert char_w(COMBINING) == 0


def test_char_w_wide_cjk():
    assert char_w(CJK) == 2


def test_char_w_ambiguous_depends_on_ambiwidth():
    assert char_w(AMBI, ambiwidth=1) == 1
    assert char_w(AMBI, ambiwidth=2) == 2


def test_disp_w():
    assert disp_w("abc") == 3
    assert disp_w("") == 0
    assert disp_w(None) == 0
    assert disp_w(CJK + "a") == 3
    assert disp_w("a" + COMBINING) == 1


def test_clip_cells_nonpositive():
    assert clip_cells("hello", 0) == ("", 0)
    assert clip_cells("hello", -3) == ("", 0)


def test_clip_cells_exact_fit():
    assert clip_cells("abc", 3) == ("abc", 3)


def test_clip_cells_wide_boundary():
    # A wide char that would overflow is not included.
    assert clip_cells(CJK + CJK, 3) == (CJK, 2)
    assert clip_cells(CJK + CJK, 4) == (CJK + CJK, 4)


def test_trunc_end_no_truncation():
    assert trunc_end("short", 10) == "short"


def test_trunc_end_uses_unicode_ellipsis():
    out = trunc_end("hello world", 5)
    assert out == "hell…"
    assert out.endswith("…")


def test_trunc_end_newlines_flattened():
    assert trunc_end("a\nb", 10) == "a b"


def test_trunc_end_nonpositive():
    assert trunc_end("hello", 0) == ""


def test_trunc_mid_preserves_basename():
    path = "/home/user/deep/nested/project/parser/stream.py"
    out = trunc_mid(path, 20)
    assert out.endswith("stream.py")
    assert "…" in out
    assert disp_w(out) <= 20


def test_trunc_mid_no_truncation_when_fits():
    assert trunc_mid("a/b.py", 20) == "a/b.py"


def test_fmt_dur_table():
    assert fmt_dur(0.45) == "450ms"
    assert fmt_dur(1.2) == "1.2s"
    assert fmt_dur(12) == "12s"
    assert fmt_dur(64) == "1m04"
    assert fmt_dur(8000) == "2h13"


def test_fmt_dur_negative_and_none():
    assert fmt_dur(-5) == "0ms"
    assert fmt_dur(0) == "0ms"
    assert fmt_dur(None) == ""


def test_fmt_idle_buckets():
    now = 1_000_000
    assert fmt_idle(now, now) == "now"
    assert fmt_idle(now - 30, now) == "now"
    assert fmt_idle(now - 180, now) == "3m"
    assert fmt_idle(now - 3600, now) == "1h"
    assert fmt_idle(now - 2 * 86400, now) == "2d"


def test_fmt_idle_never_negative():
    now = 1000
    assert fmt_idle(now + 500, now) == "now"


def test_parse_ts_roundtrip_with_iso():
    s = "2026-01-01T10:00:00.000Z"
    epoch = parse_ts(s)
    assert epoch is not None
    assert isinstance(epoch, float)
    assert iso_ts(epoch) == s


def test_parse_ts_z_suffix():
    assert parse_ts("2026-01-01T10:00:00Z") is not None


def test_parse_ts_garbage():
    assert parse_ts("not a date") is None
    assert parse_ts(None) is None
    assert parse_ts("") is None
    assert parse_ts(123) is None


def test_iso_ts_none():
    assert iso_ts(None) is None
