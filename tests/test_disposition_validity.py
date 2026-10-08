"""Carry-forward checks: a standing disposition reaches an unreviewed quarter only while its reason holds."""
import csv
import json

import duckdb
import pytest

from pipeline import disposition_validity as dv
from pipeline import finding_dispositions as fd

HPS, OWL = "0001838126", "0001812554"


def _csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _holdings(output, rows):
    base = {"row_id": "", "cik": HPS, "report_date": "2026-06-30", "fair_value": 0.0, "cost": None, "pik_rate": None,
            "nonaccrual_status": "unknown", "src_facts": "{}", "index_classification": "DIRECT_LENDING",
            "accounting_record_class": "parent_schedule"}
    con = duckdb.connect()
    con.execute("CREATE TABLE h (row_id VARCHAR, cik VARCHAR, report_date VARCHAR, fair_value DOUBLE, cost DOUBLE, pik_rate DOUBLE, "
                "nonaccrual_status VARCHAR, src_facts VARCHAR, index_classification VARCHAR, accounting_record_class VARCHAR)")
    for row in rows:
        full = {**base, **row}
        con.execute("INSERT INTO h VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(full.values()))
    con.execute("COPY h TO '%s' (FORMAT PARQUET)" % (output / "private_markets_holdings.parquet").as_posix())
    con.close()


def _issue(row_id, rule, cik=HPS, quarter="2026-06-30", name=None):
    return {"cik": cik, "report_date": quarter, "rule_id": rule, "row_id": row_id,
            "bdc_investment_identifier": name or ("Borrower " + row_id)}


def _entry(rule, check, params=None, cik=HPS, did="D-1"):
    return {"disposition_id": did, "class": "as_filed", "ciks": [cik], "engine": "row_validation", "rule_name": rule,
            "quarters": ["2026-03-31"], "statement": "As filed.", "evidence": [{"source": "query", "quote": "q"}],
            "rerun": "x", "decided_by": "agent", "decided_on": "2026-10-08",
            "carry_forward": {"from": "2026-06-30", "check": check, "params": params or {}}}


def _result(results, quarter="2026-06-30"):
    return next(r for r in results if r["report_date"] == quarter)


def test_values_as_filed_passes_only_when_every_flagged_row_is_the_filed_fact(tmp_path):
    _csv(tmp_path / "row_validation_issues.csv", [_issue("R1", "C107"), _issue("R2", "C107"),
                                                  _issue("R3", "C107", quarter="2026-09-30"),
                                                  _issue("R4", "C107", quarter="2026-09-30", name="Proxy Co revolver")])
    _csv(tmp_path / "provenance_ledger.csv", [
        {"row_id": "R1", "field": "cost", "reason_code": "verified"},
        {"row_id": "R2", "field": "cost", "reason_code": "verified"},
        {"row_id": "R3", "field": "cost", "reason_code": "verified"},
        {"row_id": "R4", "field": "cost", "reason_code": "derived"},      # a proxy, not a filed cost
        {"row_id": "R4", "field": "fair_value", "reason_code": "verified"}])
    _holdings(tmp_path, [{"row_id": "R%d" % i, "fair_value": -1e6} for i in range(1, 5)])
    results = dv.evaluate([_entry("C107", "values_as_filed", {"fields": ["cost"]})], tmp_path)
    assert _result(results)["passed"] is True and _result(results)["rows_tested"] == 2
    later = _result(results, "2026-09-30")
    assert later["passed"] is False and later["rows_failing"] == 1 and "Proxy Co revolver" in later["detail"]


def test_no_rate_in_source_names_the_rows_the_reason_does_not_explain(tmp_path):
    _csv(tmp_path / "row_validation_issues.csv", [_issue("U", "X02"), _issue("N", "X02"), _issue("P", "X02"), _issue("C", "X02"),
                                                  _issue("F", "X02", quarter="2026-09-30", name="Funded Co term loan"),
                                                  _issue("T", "X02", quarter="2026-12-31", name="Tagged Co term loan")])
    _holdings(tmp_path, [
        {"row_id": "U", "fair_value": -50000.0},                                # undrawn
        {"row_id": "N", "fair_value": 4e6, "nonaccrual_status": "nonaccrual"},  # on non-accrual
        {"row_id": "P", "fair_value": 3e6, "pik_rate": 12.0},                   # PIK only
        {"row_id": "C", "fair_value": 433000.0, "cost": -202000.0},             # unfunded line, small positive mark
        {"row_id": "F", "fair_value": 9e6},                                     # funded, accruing, no rate: unexplained
        {"row_id": "T", "fair_value": -1.0, "src_facts": '{"interest_rate":{"r":0.09}}'}])  # a rate is filed
    results = dv.evaluate([_entry("X02", "no_rate_in_source")], tmp_path)
    assert _result(results)["passed"] is True and _result(results)["rows_tested"] == 4
    funded = _result(results, "2026-09-30")
    assert funded["passed"] is False and funded["failing_fair_value_m"] == 9.0 and "Funded Co" in funded["detail"]
    assert _result(results, "2026-12-31")["passed"] is False


def _source_only(rows):
    return [{"cik": OWL, "report_date": "2026-06-30", "raw_investment_identifier": name, "source_fair_value": value,
             "is_blocking": blocking} for name, value, blocking in rows]


@pytest.mark.parametrize("rows,published,passed", [
    ([("Blue Owl Cross-Strategy Opportunities LLC (BOCSO)", 1.24e9, "True"),
      ("Total non-controlled - debt commitments", -73000, "False")], 100.0, True),
    # a new source row no pattern names: the reason no longer covers the quarter
    ([("Blue Owl Cross-Strategy Opportunities LLC (BOCSO)", 1.24e9, "True"),
      ("New Borrower, Inc. | First lien senior secured loan", 5e7, "True")], 100.0, False),
    # every row is known, but the published total no longer equals the filed one
    ([("Blue Owl Cross-Strategy Opportunities LLC (BOCSO)", 1.24e9, "True")], 150.0, False),
])
def test_missing_source_rows_known_needs_known_rows_and_matching_totals(tmp_path, rows, published, passed):
    _csv(tmp_path / "source_reconciliation_source_only_detail.csv", _source_only(rows))
    _csv(tmp_path / "fund_financials.csv", [{"cik": OWL, "report_date": "2026-06-30", "investments_at_fair_value": 100e6}])
    _holdings(tmp_path, [{"row_id": "A", "cik": OWL, "fair_value": published * 1e6},
                         {"row_id": "C", "cik": OWL, "fair_value": 7e6, "index_classification": "CASH"}])
    entry = _entry("SRC_BDC01", "missing_source_rows_known",
                   {"patterns": [r"^Blue Owl Cross-Strategy Opportunities LLC \(BOCSO\)$"]}, cik=OWL)
    assert _result(dv.evaluate([entry], tmp_path))["passed"] is passed


def test_carry_forward_is_validated_with_the_entry():
    assert fd.validate(_entry("C107", "values_as_filed", {"fields": ["cost"]})) == []
    assert any("check must be" in p for p in fd.validate(_entry("C107", "looks_fine")))
    assert any("params.fields" in p for p in fd.validate(_entry("C107", "values_as_filed", {"fields": ["issuer_name"]})))
    assert any("params.patterns" in p for p in fd.validate(_entry("SRC_BDC01", "missing_source_rows_known")))
    bad_date = _entry("C107", "values_as_filed", {"fields": ["cost"]})
    bad_date["carry_forward"]["from"] = "next quarter"
    assert any("carry_forward.from" in p for p in fd.validate(bad_date))


def test_an_entry_reaches_a_later_quarter_only_with_a_recorded_pass():
    entry = _entry("C107", "values_as_filed", {"fields": ["cost"]})
    find = lambda quarter, passes=frozenset(): fd.match([entry], cik=HPS, engine="row_validation", rule_name="C107",
                                                        report_date=quarter, passes=passes)
    assert find("2026-03-31") is not None                       # a listed quarter, as before
    assert find("2026-06-30") is None                           # no result recorded: not covered
    assert find("2026-06-30", {("D-1", HPS, "2026-06-30")}) is not None
    assert find("2026-09-30", {("D-1", HPS, "2026-06-30")}) is None       # a pass covers its own quarter only
    assert find("2025-12-31", {("D-1", HPS, "2025-12-31")}) is None       # nothing before carry_forward.from
    plain = {k: v for k, v in entry.items() if k != "carry_forward"}
    assert fd.match([plain], cik=HPS, engine="row_validation", rule_name="C107", report_date="2026-06-30",
                    passes={("D-1", HPS, "2026-06-30")}) is None          # an entry without a check never carries


def test_the_ledger_closes_a_new_quarter_through_a_pass_and_says_so(tmp_path):
    from scripts.findings_ledger import build_ledger
    queue = tmp_path / "review_queue.csv"
    fields = ["review_id", "cik", "rule_name", "report_date", "lane", "engine", "fv_at_risk_m", "fund_quarter_fv_m"]
    _csv(queue, [dict.fromkeys(fields, "") | {"review_id": rid, "cik": HPS, "rule_name": "C107", "report_date": quarter,
                                             "lane": "blocker", "engine": "row_validation"}
                 for rid, quarter in (("RQ-1", "2026-03-31"), ("RQ-2", "2026-06-30"), ("RQ-3", "2026-09-30"))])
    store = tmp_path / "finding_dispositions"
    store.mkdir()
    (store / "v05.json").write_text(json.dumps({"dispositions": [_entry("C107", "values_as_filed", {"fields": ["cost"]})]}),
                                    encoding="utf-8")
    validity = tmp_path / "disposition_validity.csv"
    dv.write([{"disposition_id": "D-1", "cik": HPS, "report_date": "2026-06-30", "check": "values_as_filed", "passed": True,
               "rows_tested": 3, "rows_failing": 0, "failing_fair_value_m": 0.0, "detail": ""},
              {"disposition_id": "D-1", "cik": HPS, "report_date": "2026-09-30", "check": "values_as_filed", "passed": False,
               "rows_tested": 3, "rows_failing": 1, "failing_fair_value_m": 2.0, "detail": "Proxy Co revolver"}], validity)
    empty = tmp_path / "none"
    kwargs = dict(queue_path=queue, staged_dir=empty, promoted_dir=empty, archive_dir=empty, wrapper_dir=empty,
                  verdict_dirs=(empty,), dispositions_dir=store)
    rows = {r["review_id"]: r for r in build_ledger(validity_path=validity, **kwargs)}
    assert (rows["RQ-1"]["state"], rows["RQ-1"]["disposition_basis"]) == ("dispositioned_as_filed", "listed")
    assert (rows["RQ-2"]["state"], rows["RQ-2"]["disposition_basis"]) == ("dispositioned_as_filed", "carried_forward")
    assert (rows["RQ-3"]["state"], rows["RQ-3"]["disposition_basis"]) == ("open", "")
    # without the results file nothing is carried
    assert {r["review_id"]: r["state"] for r in build_ledger(**kwargs)}["RQ-2"] == "open"
