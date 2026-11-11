"""par_tagged_as_units mode 'listed_rows_without_instrument' (HPS Corporate Lending, 10-Q 2026-03-31).

In 0001628280-26-033248 the filer tagged the par of its loans with the share-count concept. Its debt rows
carry no instrument text ('2080 Media, Inc. 2': printed '1/31/2033 13,795 ( 90 ) -'), so an undrawn line
with a count, no principal and no rate is classed common equity by the field heuristic, and 'TruGreen
Limited Partnership' is a fund by its name. Every equity row of the filing names its instrument
('OneTeam Partners, LLC - Class D Units', 'Creek Feeder, L.P. - LP Interest').
"""
import json

import duckdb
import pytest

from pipeline.source_encodings import load_encodings, par_tagged_unclassed_rows_expression

CIK = "0001838126"
Q1 = "0001628280-26-033248"
Q4 = "0001628280-26-020206"


def _encodings(tmp_path, values, cik=CIK):
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": cik, "source_encodings": {"par_tagged_as_units": values}}
    (tmp_path / (cik + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")
    return load_encodings(tmp_path)


ROWS = [
    # (name, cik, accession, category, instrument, raw_id, principal, shares)
    ("undrawn_line", "1838126", Q1, "EQUITY_COMMON", None, "2080 Media, Inc. 2", None, 13795000.0),
    ("fund_named_loan", "1838126", Q1, "FUND", "", "TruGreen Limited Partnership", None, 8376000.0),
    ("real_units", "1838126", Q1, "EQUITY_COMMON", "Class D Units", "OneTeam Partners, LLC - Class D Units", None, 177651.0),
    ("lp_interest", "1838126", Q1, "FUND", "LP Interest", "Creek Feeder, L.P. - LP Interest", None, 9000.0),
    ("interest_in_id_only", "1838126", Q1, "EQUITY_COMMON", None, "SLF V AD1 Holdings, LLC - LLC Interest", None, 10101.0),
    ("clo_class", "1838126", Q1, "FUND", "Class E", "ABPCI Direct Lending Fund CLO XVII LLC - Class E", None, 3500000.0),
    ("already_par", "1838126", Q1, "EQUITY_COMMON", None, "Acme LLC 2", 5000000.0, 5000000.0),
    ("loan_already", "1838126", Q1, "LOAN", None, "Acme LLC 3", None, 5000000.0),
    ("other_filing", "1838126", Q4, "EQUITY_COMMON", None, "2080 Media, Inc. 2", None, 13795000.0),
    ("other_fund", "0001812554", Q1, "EQUITY_COMMON", None, "2080 Media, Inc. 2", None, 13795000.0),
]


def _selected(expression):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (name VARCHAR, cik VARCHAR, accession_number VARCHAR, asset_category_final VARCHAR, "
                "instrument_description VARCHAR, _raw_id VARCHAR, _pa DOUBLE, _sh DOUBLE)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ROWS)
    sql = ("SELECT name FROM t WHERE " + expression.replace("cik_col", "cik") + " ORDER BY name")
    return [r[0] for r in con.execute(sql).fetchall()]


def _expr(encodings):
    return par_tagged_unclassed_rows_expression("cik", "accession_number", "asset_category_final",
                                                "instrument_description", "_raw_id", "_pa", "_sh", encodings)


def test_listed_filing_with_mode_selects_only_debt_rows_without_instrument(tmp_path):
    encodings = _encodings(tmp_path, [Q1, "rows_near_cost", "listed_rows_without_instrument"])
    assert _selected(_expr(encodings)) == ["fund_named_loan", "undrawn_line"]


def test_equity_rows_naming_an_instrument_keep_their_count(tmp_path):
    # false-positive guard: units, LP / LLC interests and a CLO class are never converted
    encodings = _encodings(tmp_path, [Q1, "listed_rows_without_instrument"])
    selected = _selected(_expr(encodings))
    for name in ("real_units", "lp_interest", "interest_in_id_only", "clo_class", "already_par", "loan_already"):
        assert name not in selected


def test_plain_listing_without_the_mode_selects_nothing(tmp_path):
    encodings = _encodings(tmp_path, [Q1, "rows_near_cost"])
    assert _expr(encodings) == "false"


def test_mode_without_a_listed_filing_selects_nothing(tmp_path):
    encodings = _encodings(tmp_path, ["listed_rows_without_instrument"])
    assert _expr(encodings) == "false"


def test_another_filing_and_another_fund_are_untouched(tmp_path):
    encodings = _encodings(tmp_path, [Q1, "listed_rows_without_instrument"])
    selected = _selected(_expr(encodings))
    assert "other_filing" not in selected and "other_fund" not in selected


def test_loader_accepts_the_mode_and_rejects_a_misspelling(tmp_path):
    _encodings(tmp_path, [Q1, "listed_rows_without_instrument"])
    with pytest.raises(ValueError):
        _encodings(tmp_path, [Q1, "listed_rows_without_instruments"])
