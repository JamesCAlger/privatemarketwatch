"""Tests for the per-position instrument-type text classifier."""
import duckdb

from pipeline.instrument_classification import (
    classify_instrument_type,
    _sql_classify_instrument_type,
)


def test_basic_types():
    assert classify_instrument_type("First Lien Term Loan") == "Term Loan"
    assert classify_instrument_type("Senior Secured Revolver") == "Revolver"
    assert classify_instrument_type("Revolving Credit Facility") == "Revolver"
    assert classify_instrument_type("Unitranche Loan") == "Unitranche"
    assert classify_instrument_type("Common Stock") is None


def test_delayed_draw_beats_term_loan():
    # "delayed draw term loan" contains "term loan"; priority must pick DDTL.
    assert classify_instrument_type("Delayed Draw Term Loan") == "Delayed Draw Term Loan"
    assert classify_instrument_type("DDTL") == "Delayed Draw Term Loan"


def test_searches_bdc_identifier():
    assert classify_instrument_type(
        "", bdc_investment_identifier="Acme | First Lien | Revolver"
    ) == "Revolver"


def test_no_match_returns_none():
    assert classify_instrument_type("Preferred Equity") is None
    assert classify_instrument_type(None, None, None) is None


def _sql_eval(combined: str, bid: str = "") -> str | None:
    con = duckdb.connect()
    case = _sql_classify_instrument_type()
    row = con.execute(
        f"SELECT {case} FROM (SELECT ? AS _combined_fund_text, ? AS bdc_investment_identifier)",
        [combined, bid],
    ).fetchone()
    con.close()
    return row[0]


def test_sql_matches_python():
    assert _sql_eval("first lien term loan") == "Term Loan"
    assert _sql_eval("senior secured revolving credit facility") == "Revolver"
    assert _sql_eval("delayed draw term loan") == "Delayed Draw Term Loan"
    assert _sql_eval("unitranche") == "Unitranche"
    assert _sql_eval("common stock") is None
    assert _sql_eval("", "acme | revolver") == "Revolver"
