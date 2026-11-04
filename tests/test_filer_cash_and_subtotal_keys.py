"""Per-filer wrapper keys from the Silver Point Specialty Lending run (CIK 0001646614, requests
SPL-R1..R3, 2026-10-19). Each key is off for a filer that does not set it.

SPL-R1 source_encodings.cash_rows_include_concepts: the schedule's cash rows also hold restricted
    cash equivalents. 10-Q 2023-09-30 (0000950170-23-060746) prints 'Total Cash Equivalents and
    Restricted Cash Equivalents 92,114,292 92,114,292 17.06 %'; the filer tags
    CashEquivalentsAtCarryingValue 49,900,000 and RestrictedCashEquivalents 42,200,000 (sum 92.1M).
SPL-R2 source_encodings.subtotal_members: printed subtotal lines no shared rule recognises.
SPL-R3 source_encodings.cost_total_excludes: the cost total leaves the cash rows out like fair value.
    10-Q 2023-06-30 (0000950170-23-042115): 'Total Investments, June 30, 2023 $ 863,202,721
    $ 847,380,975'; the cash row (84,630,043 cost) is printed below it.
"""
import json
import re
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from pipeline import source_encodings

SPL = "0001646614"
SPL_PATTERNS = json.loads(
    (Path(__file__).resolve().parents[1] / "data/overrides/bdc_xbrl_wrappers"
     / (SPL + ".json")).read_text(encoding="utf-8"))["source_encodings"]["subtotal_members"]


def _write_wrapper(tmp_path, cik, encoding):
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": cik, "source_encodings": encoding}
    (tmp_path / (cik + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")


# ------------------------------------------------------------------ loader


@pytest.mark.parametrize("encoding,message", [
    ({"cash_rows_include_concepts": ["us-gaap:RestrictedCashEquivalents"]}, "one local name"),
    ({"subtotal_members": ["^(?=Total) .*$"]}, "RE2"),
    ({"subtotal_members": ["^Total ("]}, "regular expressions"),
    ({"cost_total_excludes": ["cash_rows"]}, "needs investments_total_excludes"),
    ({"investments_total_excludes": ["cash_rows"], "cost_total_excludes": ["deposits"]}, "cost total"),
])
def test_loader_refuses_malformed_keys(tmp_path, encoding, message):
    _write_wrapper(tmp_path, "0000000001", encoding)
    with pytest.raises(ValueError, match=message):
        source_encodings.load_encodings(tmp_path)


def test_silver_point_wrapper_fits_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json").read_text(encoding="utf-8"))
    wrapper = json.loads((root / "data/overrides/bdc_xbrl_wrappers" / (SPL + ".json")).read_text(encoding="utf-8"))
    assert [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(wrapper)] == []


def test_loader_accepts_the_silver_point_wrapper():
    encoding = source_encodings.load_encodings()[SPL]
    assert encoding["cash_rows_include_concepts"] == ["RestrictedCashEquivalents"]
    assert encoding["cost_total_excludes"] == ["cash_rows"]
    assert SPL in source_encodings.cost_cash_split_ciks()


# ------------------------------------------------------------------ SPL-R1 filed addends


def _companyfacts(tmp_path, cik, concepts):
    facts = {"facts": {"us-gaap": {name: {"units": {"USD": [
        {"end": end, "val": val, "form": "10-Q"} for end, val in series.items()]}}
        for name, series in concepts.items()}}}
    (tmp_path / (cik + ".json")).write_text(json.dumps(facts), encoding="utf-8")


def test_addends_read_the_filed_restricted_cash_equivalents(tmp_path):
    _companyfacts(tmp_path, SPL, {"RestrictedCashEquivalents": {"2023-09-30": 42200000, "2023-12-31": 83300000},
                                  "CashEquivalentsAtCarryingValue": {"2023-09-30": 49900000}})
    encodings = {SPL: {"cash_rows_include_concepts": ["RestrictedCashEquivalents"]}}
    rows = source_encodings.cash_rows_filed_addends(encodings, cache_dir=tmp_path)
    assert rows == [(SPL, "2023-09-30", 42200000.0), (SPL, "2023-12-31", 83300000.0)]


def test_addends_are_empty_for_a_filer_without_the_key(tmp_path):
    _companyfacts(tmp_path, "0000000002", {"RestrictedCashEquivalents": {"2023-09-30": 5.0}})
    encodings = {"0000000002": {"investments_total_excludes": ["cash_rows"]}}
    assert source_encodings.cash_rows_filed_addends(encodings, cache_dir=tmp_path) == []


# ------------------------------------------------------------------ SPL-R1 conservation engine


def _engine_case(monkeypatch, tmp_path, *, cash_row, filed_cash, extra, value_column="fair_value",
                 cost_split=False, loans=862914087.0, fv_declared=True, inside=False):
    import scripts.shadow_conservation_engine as sce
    monkeypatch.setattr(sce, "cash_outside_total_ciks", lambda: ["0000000001"] if fv_declared else [])
    monkeypatch.setattr(sce, "cash_inside_total_ciks", lambda: ["0000000001"] if inside else [])
    monkeypatch.setattr(sce, "filed_cash_addend_rows",
                        lambda: [("0000000001", "2023-09-30", extra)] if extra else [])
    monkeypatch.setattr(sce, "cost_split_ciks", lambda: ["0000000001"] if cost_split else [])
    ff = tmp_path / "fund_financials.csv"
    ff.write_text("cik,report_date,source,investments_at_fair_value,cash_equivalents_at_fair_value,investments_at_cost\n"
                  "0000000001,2023-09-30,companyfacts,862914087,%s,869289348\n" % filed_cash, encoding="utf-8")
    monkeypatch.setattr(sce, "FUND_FINANCIALS_FILE", ff)
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.execute("INSERT INTO wrapped VALUES ('0000000001')")
    con.execute(f"""CREATE TABLE unified_tbl AS SELECT * FROM (VALUES
        ('0000000001', '2023-09-30', {loans}, {loans}, 'x=y', 'LOAN', 'parent_schedule'),
        ('0000000001', '2023-09-30', {cash_row}, {cash_row}, 'c=MMF', 'CASH', 'parent_schedule')
        ) AS t(cik, report_date, fair_value, cost, bdc_dimensions_raw, asset_category, accounting_record_class)""")
    monkeypatch.setattr(sce, "_unified", lambda: "unified_tbl")
    if value_column == "fair_value":
        anchors = (sce.Anchor("fund_financials_plus_cash", "companyfacts_fv_plus_cash",
                              "investments_at_fair_value", basis="published_rows"),
                   sce.Anchor("fund_financials", "companyfacts_fv", "investments_at_fair_value",
                              basis="investments_ex_cash"))
    else:
        anchors = (sce.Anchor("fund_financials", "ff_investments_at_cost", "investments_at_cost",
                              basis="investments_ex_cash"),)
    rule = sce.ConservationRule(name="r_" + value_column, value_column=value_column, anchors=anchors,
                                tolerance_pct=0.005 if value_column == "fair_value" else 0.05)
    sce.run_rule(con, rule)
    return con.execute(f"SELECT anchor_used, status, cash_status, compared_sum FROM result_r_{value_column}").fetchone()


def test_engine_cash_rows_holding_restricted_cash_equivalents_reconcile(monkeypatch, tmp_path):
    # 2023-09-30: published cash row 92,114,292 = filed 49.9M + filed restricted 42.2M.
    used, status, cash_status, _ = _engine_case(monkeypatch, tmp_path, cash_row=92114292.0,
                                                filed_cash=49900000, extra=42200000.0)
    assert status == "reconciles"
    assert used == "companyfacts_fv_plus_cash" or cash_status == "within_filed"


def test_engine_without_the_key_the_restricted_part_still_fails(monkeypatch, tmp_path):
    assert _engine_case(monkeypatch, tmp_path, cash_row=92114292.0, filed_cash=49900000, extra=None)[1:3] == (
        "overshoot", "exceeds_filed")


def test_engine_cash_rows_above_filed_plus_restricted_still_fail(monkeypatch, tmp_path):
    # A cash row 30M above what is filed is excess even with the restricted part added.
    assert _engine_case(monkeypatch, tmp_path, cash_row=122114292.0, filed_cash=49900000,
                        extra=42200000.0)[1:3] == ("overshoot", "exceeds_filed")


def test_engine_restricted_part_not_added_where_no_cash_figure_is_filed(monkeypatch, tmp_path):
    assert _engine_case(monkeypatch, tmp_path, cash_row=92114292.0, filed_cash="",
                        extra=42200000.0)[2] == "no_filed_figure"


# ------------------------------------------------------------------ SPL-R3 cost split


def test_cost_rule_splits_cash_for_a_declared_filer(monkeypatch, tmp_path):
    # 2023-09-30: non-cash cost 869,289,348 = filed; with the 92.1M cash row it is 10.6 pct over.
    used, status, cash_status, compared = _engine_case(
        monkeypatch, tmp_path, cash_row=92114292.0, filed_cash=49900000, extra=None,
        value_column="cost", cost_split=True, loans=869289348.0)
    assert (used, status, cash_status, compared) == ("ff_investments_at_cost", "reconciles", "", 869289348.0)


def test_cost_rule_without_the_key_detects_the_basis_of_an_ex_cash_investments_filer(monkeypatch, tmp_path):
    # Owner ruling 2026-11-04 (cost-conservation-cash-rows-against-ex-cash-cost-total): the
    # wrapper says the investments line leaves the cash rows out; with them cost is 10.6 pct
    # over, without them it ties: the cash rows' cost is taken out. (Before: overshoot.)
    assert _engine_case(monkeypatch, tmp_path, cash_row=92114292.0, filed_cash=49900000, extra=None,
                        value_column="cost", cost_split=False, loans=869289348.0)[1:] == (
        "reconciles", "", 869289348.0)


def test_cost_rule_without_any_evidence_is_unchanged(monkeypatch, tmp_path):
    # No wrapper declaration and the cash rows (92.1M) do not equal the filed cash (49.9M).
    assert _engine_case(monkeypatch, tmp_path, cash_row=92114292.0, filed_cash=49900000, extra=None,
                        value_column="cost", cost_split=False, loans=869289348.0,
                        fv_declared=False)[1] == "overshoot"


def test_cost_rule_detects_an_undeclared_filer_whose_cash_rows_equal_filed_cash(monkeypatch, tmp_path):
    # Silver Capital 2025-09-30 shape: the money fund (fair value = filed cash equivalents).
    assert _engine_case(monkeypatch, tmp_path, cash_row=92114292.0, filed_cash=92114292, extra=None,
                        value_column="cost", cost_split=False, loans=869289348.0,
                        fv_declared=False)[1:] == ("reconciles", "", 869289348.0)


def test_cost_rule_detection_never_for_a_filer_whose_line_holds_cash(monkeypatch, tmp_path):
    assert _engine_case(monkeypatch, tmp_path, cash_row=92114292.0, filed_cash=92114292, extra=None,
                        value_column="cost", cost_split=False, loans=869289348.0,
                        fv_declared=False, inside=True)[1] == "overshoot"


def test_cost_rule_detection_still_fails_non_cash_cost_that_is_off(monkeypatch, tmp_path):
    # False-positive guard: non-cash cost 19 pct short; neither basis ties, nothing is taken out.
    assert _engine_case(monkeypatch, tmp_path, cash_row=92114292.0, filed_cash=92114292, extra=None,
                        value_column="cost", cost_split=False, loans=700000000.0)[1:] == (
        "undershoot", "", 700000000.0 + 92114292.0)


def test_cost_rule_keeps_small_cash_rows_where_the_total_with_them_ties(monkeypatch, tmp_path):
    # Cash row 1M inside the 5 pct band: the with-cash total ties, so it is not split.
    assert _engine_case(monkeypatch, tmp_path, cash_row=1000000.0, filed_cash=1000000, extra=None,
                        value_column="cost", cost_split=False, loans=869289348.0)[1:] == (
        "reconciles", "", 869289348.0 + 1000000.0)


def test_cost_rule_split_still_fails_non_cash_cost_that_is_off(monkeypatch, tmp_path):
    # Non-cash cost 10 pct short of the filed total fails whatever the cash row holds.
    assert _engine_case(monkeypatch, tmp_path, cash_row=92114292.0, filed_cash=49900000, extra=None,
                        value_column="cost", cost_split=True, loans=782360413.0)[1] == "undershoot"


# ------------------------------------------------------------------ SPL-R1 GAV reconciliation


def _gav(monkeypatch, cik, encodings, addends, cash_row="92114292"):
    from pipeline.validate_holdings import check_gav_reconciliation
    from tests.test_validate_holdings import _make_unified_df
    monkeypatch.setattr(source_encodings, "load_encodings", lambda *a, **k: encodings)
    monkeypatch.setattr(source_encodings, "cash_rows_filed_addends", lambda *a, **k: addends)
    holdings = _make_unified_df([
        {"cik": cik, "entity_name": "Fund", "report_date": "2023-09-30",
         "fair_value": "862914087", "source": "bdc", "asset_category": "LOAN"},
        {"cik": cik, "entity_name": "Fund", "report_date": "2023-09-30",
         "fair_value": cash_row, "source": "bdc", "asset_category": "CASH"},
    ])
    ff = pd.DataFrame([{"cik": cik, "report_date": "2023-09-30", "investments_at_fair_value": "862914087",
                        "cash_equivalents_at_fair_value": "49900000", "total_assets": "1000000000"}])
    return float(check_gav_reconciliation(holdings, fund_financials_df=ff).iloc[0]["gav_ratio"])


def test_gav_adds_the_filed_restricted_cash_equivalents(monkeypatch):
    enc = {SPL: {"investments_total_excludes": ["cash_rows"], "cash_rows_include_concepts": ["RestrictedCashEquivalents"]}}
    assert abs(_gav(monkeypatch, SPL, enc, [(SPL, "2023-09-30", 42200000.0)]) - 1.0) < 2e-4


def test_gav_without_the_key_is_short_by_the_restricted_part(monkeypatch):
    enc = {SPL: {"investments_total_excludes": ["cash_rows"]}}
    ratio = _gav(monkeypatch, SPL, enc, [])
    assert abs(ratio - 955028379 / 912814087) < 1e-4  # gav_ratio is rounded to 4 places


def test_gav_cash_row_above_filed_plus_restricted_is_still_excess(monkeypatch):
    enc = {SPL: {"investments_total_excludes": ["cash_rows"], "cash_rows_include_concepts": ["RestrictedCashEquivalents"]}}
    assert _gav(monkeypatch, SPL, enc, [(SPL, "2023-09-30", 42200000.0)], cash_row="192114292") > 1.05


# ------------------------------------------------------------------ SPL-R2 subtotal members


@pytest.mark.parametrize("member", [
    # 10-Q 2023-06-30 (0000950170-23-042115) prints 'Total Investments, June 30, 2023 $ 863,202,721
    # $ 847,380,975'; member fair value 847,380,975.
    "Total Investments",
    # Same filing: 'Total United States of America 1st Lien Term Loan 660,831,089 652,835,717 122.76';
    # member fair value 652,835,717.
    "Non-Controlled/Non-Affiliated Investments, Secured Loans, Total United States of America 1st Lien Term Loan",
    "Controlled Investments, Total Trust Interest",
    "Non-Controlled/Non-Affiliated Investments Total 1st Lien/Secured Loans",
    # 10-Q 2024-06-30 (0000950170-24-095339): 'Total United States of America Equities 474,538
    # 2,349,171 0.43'; member fair value 2,349,171. And 'Total Canada 1st Lien/Secured Loans
    # 32,791,029 32,834,377'; member fair value 32,834,377.
    "Non-Controlled/Non-Affiliated Investments United States of America Equities",
    "Non-Controlled/Non-Affiliated Investments Canada 1st Lien/Secured Loans",
    # 10-K 2024-12-31 (0000950170-25-039264): 'Total Trust Interest 3,724,975 1,424,586 0.26';
    # member fair value 1,424,586.
    "Controlled Investments United States of America Trust Interest",
    # Same filing: member fair value 5,135,6xx, the value of the 'United States of America 2nd
    # Lien/Secured Loans' subtotal it repeats.
    "Non-Controlled/Non-Affiliated Investments of 2nd Lien/Secured Loans",
    # 10-Q 2024-06-30: 'Total Non-Controlled/Non-Affiliated Investments 887,143,280 879,384,323';
    # member fair value 879,384,323.
    "Non-Controlled/Non-Affiliated Investments",
])
def test_silver_point_subtotal_members_match(member):
    assert any(re.search("(?i)" + p, member) for p in SPL_PATTERNS)


@pytest.mark.parametrize("member", [
    # Real position members (leaves) of the same filer, including issuers whose name holds 'Total'.
    "Non-Controlled/Non-Affiliated Investments Equities United States of America Beauty Health Co Instrument "
    "Common Equities Industry Consumer Services",
    "Non-Controlled/Non-Affiliated Investments Equities United States of America Total Produce Holdings "
    "Instrument Common Equities",
    "Non-Controlled/Non-Affiliated Investments, Secured Loans, 1st Lien Term Loan, France, Total Energies SA, "
    "Energy, Rate S+5.00%, Interest Rate 10.31%, Maturity Date 6/30/2027",
    "Total Quality Logistics LLC 1st Lien Term Loan",
    "Controlled Investments, Trust Interest, United States of America, TH Liquidating Trust, Other",
])
def test_silver_point_subtotal_members_leave_positions_alone(member):
    assert not any(re.search("(?i)" + p, member) for p in SPL_PATTERNS)


def test_subtotal_expression_is_restricted_to_its_filer():
    encodings = {SPL: {"subtotal_members": SPL_PATTERNS}}
    expression = source_encodings.subtotal_member_expression("cik", "member", encodings)
    member = "Non-Controlled/Non-Affiliated Investments United States of America Equities"
    with duckdb.connect() as con:
        sql = "SELECT " + expression + " FROM (SELECT ? AS cik, ? AS member)"
        assert con.execute(sql, [SPL, member]).fetchone()[0] is True
        assert con.execute(sql, ["0000000002", member]).fetchone()[0] is False
        assert con.execute(sql, [SPL, member + " Instrument Common Equities"]).fetchone()[0] is False
    assert source_encodings.subtotal_member_expression("cik", "member", {"0000000002": {}}) == "false"


def _reconcile(monkeypatch, encodings, members):
    from pipeline.source_reconciliation import reconcile_bdc_source_to_holdings
    from tests.test_validate_holdings import _make_bdc_output, _make_bdc_source, _no_rescales
    monkeypatch.setattr(source_encodings, "load_encodings", lambda *a, **k: encodings)
    source = _make_bdc_source(
        [{}] + [{"investment_identifier": m, "dimensions_raw": "investmentidentifier=" + m,
                 "context_id": "ctx%d" % (i + 2), "fair_value": "2349171", "cost": "474538",
                 "principal_amount": "", "interest_rate": "", "basis_spread": ""}
                for i, m in enumerate(members)])
    detail, _ = reconcile_bdc_source_to_holdings(source, _make_bdc_output([{}]), audited_value_rescales=_no_rescales())
    return {r["raw_investment_identifier"]: (r["status"], bool(r["blocking_issue"]))
            for _, r in detail.iterrows()}


SUBTOTAL = "Non-Controlled/Non-Affiliated Investments United States of America Equities"
LEAF = ("Non-Controlled/Non-Affiliated Investments Equities United States of America Total Produce Holdings "
        "Instrument Common Equities Industry Food Products")


def test_reconciliation_documents_a_wrapper_subtotal_and_keeps_a_missing_leaf_blocking(monkeypatch):
    result = _reconcile(monkeypatch, {"0000000100": {"subtotal_members": SPL_PATTERNS}}, [SUBTOTAL, LEAF])
    assert result["Acme Corp - First Lien Term Loan"][0] == "matched"
    assert result[SUBTOTAL] == ("excluded_aggregate_candidate", False)
    assert result[LEAF] == ("missing_from_pipeline", True)


def test_reconciliation_unchanged_for_a_filer_without_the_key(monkeypatch):
    result = _reconcile(monkeypatch, {}, [SUBTOTAL, LEAF])
    assert result[SUBTOTAL] == ("missing_from_pipeline", True)
    assert result[LEAF] == ("missing_from_pipeline", True)
