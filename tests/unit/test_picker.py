"""The session-picker fuzzy matcher (`_fuzzy`)."""

from cclenzz.ui.picker import _fuzzy


def test_empty_needle_matches_zero_tightness():
    assert _fuzzy("", "anything") == (True, 0)


def test_subsequence_matches_with_tightness():
    matched, tight = _fuzzy("cfg", "config")
    assert matched is True
    assert tight > 0


def test_non_subsequence_fails():
    assert _fuzzy("xyz", "config") == (False, 0)


def test_case_insensitive():
    matched, _ = _fuzzy("CFG", "config")
    assert matched is True


def test_tighter_match_has_smaller_tightness():
    _, tight_tight = _fuzzy("co", "config")     # adjacent -> span 1
    _, tight_loose = _fuzzy("cg", "config")     # spread out -> span 5
    assert tight_tight < tight_loose
