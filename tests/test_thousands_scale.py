"""Two opt-in readings for a filer whose facts carry the printed thousands figure with no scale.

source_encodings.thousands_scale_filings: Phillip Street Middle Market Lending, 10-Q 2026-03-31
(0001193125-26-219873): SpecialtyCare prints '20,267 20,226 20,166' (thousands); principal is tagged
20267 at decimals 0, cost 20,226,000 and fair value 20,166,000 at decimals -3.

par_tagged_as_units '<accession>:x1000': the same filer, 10-Q 2023-12-31 (0000950170-24-026163), tags
the par of its loans as InvestmentOwnedBalanceShares at the printed scale ('ASM Buyer ... 01/29/28
4,189 - -' tagged 4189).
"""
import json

import duckdb
import pytest

from pipeline.bdc_filings import _normalize_mixed_decimals_monetary_facts
from pipeline.source_encodings import (load_encodings, par_tagged_as_units_expression,
                                       par_tagged_as_units_thousands_expression, thousands_scale_filing)

CIK = "0001948368"
Q1 = "0001193125-26-219873"
Q4 = "0000950170-24-026163"


def _facts():
    facts = {
        "specialtycare": {"principal_amount": 20267.0, "cost": 20226000.0, "fair_value": 20166000.0},
        "undrawn": {"principal_amount": 948.0, "cost": -8000.0, "fair_value": -14000.0},
        "already_dollars": {"principal_amount": 5872000.0, "cost": 5824000.0, "fair_value": 5755000.0},
    }
    stored = [
        ("specialtycare", "principal_amount", 0, "investmentownedbalanceprincipalamount"),
        ("specialtycare", "cost", -3, "investmentownedatcost"),
        ("specialtycare", "fair_value", -3, "investmentownedatfairvalue"),
        ("undrawn", "principal_amount", 0, "investmentownedbalanceprincipalamount"),
        ("undrawn", "cost", -3, "investmentownedatcost"),
        ("undrawn", "fair_value", -3, "investmentownedatfairvalue"),
        ("already_dollars", "principal_amount", -3, "investmentownedbalanceprincipalamount"),
        ("already_dollars", "cost", -3, "investmentownedatcost"),
        ("already_dollars", "fair_value", -3, "investmentownedatfairvalue"),
    ]
    return facts, stored


def test_listed_filing_reads_decimals_zero_facts_in_thousands():
    facts, stored = _facts()
    prov = {}
    _normalize_mixed_decimals_monetary_facts(facts, stored, prov, thousands=True)
    assert facts["specialtycare"] == {"principal_amount": 20267000.0, "cost": 20226000.0, "fair_value": 20166000.0}
    assert facts["undrawn"]["principal_amount"] == pytest.approx(948000.0)
    assert facts["already_dollars"]["principal_amount"] == 5872000.0
    assert prov["specialtycare"]["principal_amount"]["x"] == ["decimals_rescale:10^3"]
    assert prov["specialtycare"]["principal_amount"]["r"] == 20267.0
    assert "cost" not in prov["specialtycare"]


def test_unlisted_filing_with_the_same_facts_is_left_alone():
    # false positive guard: 6 of 9 facts at -3 is below the shared 75 pct dominance, and the shared
    # guard only ever scales a coarse outlier down
    facts, stored = _facts()
    _normalize_mixed_decimals_monetary_facts(facts, stored, {})
    assert facts["specialtycare"]["principal_amount"] == 20267.0
    assert facts["undrawn"]["principal_amount"] == 948.0


def test_coarser_fact_is_never_divided_in_thousands_mode():
    facts = {"a": {"cost": 1234000000.0}}
    _normalize_mixed_decimals_monetary_facts(facts, [("a", "cost", -6, "investmentownedatcost")], {}, thousands=True)
    assert facts["a"]["cost"] == 1234000000.0


def _encodings(tmp_path, source_encodings):
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK, "source_encodings": source_encodings}
    (tmp_path / (CIK + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")
    return load_encodings(tmp_path)


def test_thousands_lookup_is_by_cik_and_accession(tmp_path):
    encodings = _encodings(tmp_path, {"thousands_scale_filings": [Q1]})
    assert thousands_scale_filing({"cik": "1948368", "accession_number": Q1}, encodings)
    assert not thousands_scale_filing({"cik": CIK, "accession_number": "0001193125-26-088656"}, encodings)
    assert not thousands_scale_filing({"cik": "0001772704", "accession_number": Q1}, encodings)


def test_loader_rejects_a_non_accession(tmp_path):
    with pytest.raises(ValueError):
        _encodings(tmp_path, {"thousands_scale_filings": ["2026-03-31"]})
    with pytest.raises(ValueError):
        _encodings(tmp_path, {"par_tagged_as_units": [Q4 + ":x10"]})


def _matches(expression):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (cik VARCHAR, accession_number VARCHAR)")
    con.execute("INSERT INTO t VALUES (?, ?), (?, ?), (?, ?), (?, ?)",
                ["1948368", Q4, "1948368", "0000950170-23-039890", "0001772704", Q4, "1948368", "0000950170-24-125398"])
    return [r[0] for r in con.execute("SELECT accession_number FROM t WHERE " + expression + " ORDER BY 1").fetchall()]


def test_x1000_entries_select_only_their_filing(tmp_path):
    encodings = _encodings(tmp_path, {"par_tagged_as_units": [Q4 + ":x1000", "0000950170-23-039890", "rated_rows_near_cost"]})
    assert _matches(par_tagged_as_units_thousands_expression("cik", "accession_number", encodings)) == [Q4]
    # the plain-accession reading keeps its own filing only; an x1000 entry is not read at scale 1
    assert _matches(par_tagged_as_units_expression("cik", "accession_number", encodings)) == ["0000950170-23-039890"]


def test_no_x1000_entry_selects_nothing(tmp_path):
    encodings = _encodings(tmp_path, {"par_tagged_as_units": ["rated_rows_near_cost"]})
    assert par_tagged_as_units_thousands_expression("cik", "accession_number", encodings) == "false"
