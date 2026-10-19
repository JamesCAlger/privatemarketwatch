"""dispatch.cash_identifier_rows: listed cash rows of an opted-in prefix_rules filer pass the subtotal filter.

TCW Direct Lending VII prints its money market fund and Treasury bills under 'Cash Equivalents' and
'Short-term Investments'; the members carry the heading in front and no instrument word, so the
prefix-rule subtotal filter dropped them except where a bill's member named a 'Maturity Date'.
"""
import json

import duckdb
import pytest

from pipeline import source_encodings, staging_bdc

LISTED = "Cash Equivalents First American Government Obligation Fund, Yield 4.65%"


def _wrapper(cik, dispatch, identifiers):
    return {"schema_version": "bdc-xbrl-wrapper.v3", "cik": cik, "dispatch": dispatch,
            "source_encodings": {"cash_identifiers": identifiers}}


@pytest.fixture
def wrappers(tmp_path, monkeypatch):
    for cik, dispatch in (("0001715933", {"cash_identifier_rows": "positions"}), ("0009999999", {})):
        (tmp_path / (cik + ".json")).write_text(json.dumps(_wrapper(cik, dispatch, [LISTED])), encoding="utf-8")
    monkeypatch.setattr(staging_bdc, "_WRAPPER_DEFINITIONS_DIR", tmp_path)
    real = source_encodings.load_encodings
    monkeypatch.setattr(source_encodings, "load_encodings", lambda wrapper_directory=None: real(tmp_path))
    return tmp_path


def _rescued(cik, raw_id):
    sql = staging_bdc.cash_identifier_rescue_sql("_raw_id")
    con = duckdb.connect()
    return con.execute(f"SELECT {sql} FROM (SELECT ? AS cik, ? AS _raw_id)", [cik, raw_id]).fetchone()[0]


def test_listed_cash_row_of_opted_in_filer_is_rescued(wrappers):
    assert _rescued("1715933", LISTED) is True
    # whitespace and case are normalised as for the reviewed-cash classification
    assert _rescued("0001715933", "cash equivalents  First American Government Obligation Fund, Yield 4.65%") is True


def test_heading_total_and_unlisted_rows_are_not_rescued(wrappers):
    assert _rescued("0001715933", "Cash Equivalents") is False
    assert _rescued("0001715933", "Total Investments (144.1%)") is False
    assert _rescued("0001715933", "Cash Equivalents First American Government Obligation Fund, Yield 5.30%") is False


def test_filer_without_the_setting_keeps_the_filter(wrappers):
    # the same identifier listed by a filer that did not opt in is not rescued
    assert _rescued("0009999999", LISTED) is False


def test_no_opted_in_filer_gives_false(tmp_path, monkeypatch):
    (tmp_path / "0009999999.json").write_text(json.dumps(_wrapper("0009999999", {}, [LISTED])), encoding="utf-8")
    monkeypatch.setattr(staging_bdc, "_WRAPPER_DEFINITIONS_DIR", tmp_path)
    assert staging_bdc.cash_identifier_rescue_sql("_raw_id") == "FALSE"
