"""Tests for the P3 staged-overlay blank-only / conflict disposition logic."""

from pipeline.identifier_overlay import _agree, _prod_blank
from pipeline.identifier_rate import normalize_rate_pct


def test_normalize_rate_pct_mixed_storage():
    assert normalize_rate_pct(0.0575) == 5.75    # decimal -> percent
    assert normalize_rate_pct(5.75) == 5.75      # already percent -> as-is
    assert normalize_rate_pct(0.0) == 0.0
    assert normalize_rate_pct(None) is None
    assert normalize_rate_pct("x") is None


def test_agree_tolerates_percent_scale_twin():
    # the scale bug: prod basis_spread stored on PERCENT scale (5.75), A=5.75 -> NOT a conflict
    assert _agree(5.75, 5.75, "pct_dec")         # was a false conflict before the fix
    assert _agree(0.0575, 5.75, "pct_dec")       # decimal-stored twin, same value -> agree
    assert not _agree(0.0535, 5.25, "pct_dec")   # real 10bps disagreement -> still a conflict


def test_agree_does_not_rescale_agent_subpercent_value():
    # A may legitimately parse a sub-1% rate (0.75%); prod decimal 0.0075 -> 0.75% -> agree
    assert _agree(0.0075, 0.75, "pct_dec")


def test_prod_blank_detects_empty_and_zero():
    assert _prod_blank(None, "str")
    assert _prod_blank("", "str")
    assert _prod_blank("none", "str")
    assert _prod_blank(0.0, "pct_dec")          # zero rate is blank
    assert _prod_blank("1M SOFR + 6.00%", "pct_dec")  # unparseable string -> numerically blank
    assert not _prod_blank("SOFR", "str")
    assert not _prod_blank(0.05, "pct_dec")


def test_agree_pct_decimal_vs_percent():
    # production stores decimal (0.123), A parses percent (12.30)
    assert _agree(0.123, 12.30, "pct_dec")
    assert not _agree(0.07, 11.00, "pct_dec")   # MidCap mis-bin: cash leg vs total -> conflict


def test_agree_date_iso_prefix():
    assert _agree("2030-10-24", "2030-10-24", "date")
    assert not _agree("2023-02-02", "2030-10-24", "date")


def test_agree_str_case_insensitive():
    assert _agree("sofr", "SOFR", "str")
    assert not _agree("LIBOR", "SOFR", "str")
