"""Tests for B2 post-staging correction appliers (pure, in-memory DataFrames)."""

from __future__ import annotations

import pandas as pd

from pipeline import agent_b2_appliers as ap


def _holdings():
    # Two identical TorcSill rows in the same quarter (a duplicate) + a distinct row + a
    # legitimate prior-period comparative of the distinct row.
    return pd.DataFrame([
        {"issuer_name": "WDE TorcSill", "interest_rate": 25.75, "report_date": "2025-03-31",
         "period": "2025-03-31", "fair_value": 1000.0},
        {"issuer_name": "WDE TorcSill", "interest_rate": 25.75, "report_date": "2025-03-31",
         "period": "2025-03-31", "fair_value": 1000.0},
        {"issuer_name": "Acme Term Loan", "interest_rate": 9.0, "report_date": "2025-03-31",
         "period": "2025-03-31", "fair_value": 500.0},
        {"issuer_name": "Acme Term Loan", "interest_rate": 9.0, "report_date": "2025-03-31",
         "period": "2024-12-31", "fair_value": 480.0},  # comparative prior period
    ])


def test_dedup_drops_same_quarter_duplicate():
    df, audit = ap.apply_dedup(_holdings(), {
        "match_fields": ["issuer_name", "interest_rate", "report_date", "period"], "keep": "first"})
    assert audit["status"] == "ok"
    assert audit["rows_dropped"] == 1
    assert audit["fv_dropped"] == 1000.0
    # the duplicate TorcSill is gone; the comparative Acme row (different period) is NOT a dup
    assert len(df) == 3
    assert (df["issuer_name"] == "WDE TorcSill").sum() == 1


def test_dedup_does_not_collapse_comparatives_when_period_in_keys():
    # With period in match_fields, the two Acme rows (different period) are NOT duplicates.
    df, audit = ap.apply_dedup(_holdings(), {
        "match_fields": ["issuer_name", "report_date", "period"]})
    assert (df["issuer_name"] == "Acme Term Loan").sum() == 2


def test_dedup_missing_column_fails_safe():
    df, audit = ap.apply_dedup(_holdings(), {"match_fields": ["nonexistent_col"]})
    assert audit["status"] == "error"
    assert audit["rows_dropped"] == 0
    assert len(df) == 4  # unchanged


def test_comparative_period_filter():
    df, audit = ap.apply_comparative_period_filter(_holdings(), {"report_date": "2025-03-31"})
    assert audit["status"] == "ok"
    assert audit["rows_dropped"] == 1  # the 2024-12-31 comparative
    assert (df["period"].astype(str) == df["report_date"].astype(str)).all()


def test_comparative_period_filter_is_report_date_scoped():
    rows = _holdings().to_dict("records")
    rows.append({"issuer_name": "Other Quarter", "interest_rate": 9.0, "report_date": "2025-06-30",
                 "period": "2025-03-31", "fair_value": 123.0})
    df, audit = ap.apply_comparative_period_filter(
        pd.DataFrame(rows), {"report_date": "2025-03-31"}
    )
    assert audit["status"] == "ok"
    assert audit["rows_dropped"] == 1
    assert (df["issuer_name"] == "Other Quarter").sum() == 1


def test_comparative_period_filter_requires_report_date():
    df, audit = ap.apply_comparative_period_filter(_holdings(), {})
    assert audit["status"] == "error"
    assert audit["rows_dropped"] == 0
    assert len(df) == 4


def test_run_corrections_applies_in_stage_order_and_skips_non_post_staging():
    corrections = [
        {"cik": "0001715933", "fix_class": "dedup",
         "template": {"match_fields": ["issuer_name", "interest_rate", "report_date", "period"]}},
        {"cik": "0001715933", "fix_class": "subtotal_filter",  # wrapper-domain -> skipped here
         "template": {"patterns": ["Total"]}},
    ]
    df, audits = ap.run_corrections(_holdings(), corrections)
    by_fc = {a["fix_class"]: a for a in audits}
    assert by_fc["dedup"]["status"] == "ok" and by_fc["dedup"]["rows_dropped"] == 1
    assert by_fc["subtotal_filter"]["status"] == "skipped"
    assert len(df) == 3


def test_run_corrections_stage_filter():
    corrections = [{"cik": "0001715933", "fix_class": "dedup",
                    "template": {"match_fields": ["issuer_name", "report_date", "period", "interest_rate"]}}]
    # dedup is stage 1; restricting to stage 2 applies nothing.
    df, audits = ap.run_corrections(_holdings(), corrections, stage=2)
    assert audits == []
    assert len(df) == 4


def _layer_frame():
    # Two presentations of a fund's book: dimensioned rows + a bare-axis layer
    # (the 1812554/1838126 shape). One off-scope quarter row guards scoping.
    return pd.DataFrame([
        {"issuer_name": "Acme TL", "report_date": "2026-03-31", "fair_value": 1000.0,
         "axis_profile": "investmentidentifieraxis|non-affiliated issuer", "is_subsidiary": 0},
        {"issuer_name": "Beta TL", "report_date": "2026-03-31", "fair_value": 2000.0,
         "axis_profile": "investmentidentifieraxis|non-affiliated issuer", "is_subsidiary": 0},
        {"issuer_name": "JV Feeder LLC", "report_date": "2026-03-31", "fair_value": 400.0,
         "axis_profile": "investmentidentifieraxis", "is_subsidiary": 0},
        {"issuer_name": "JV Feeder II LLC", "report_date": "2026-03-31", "fair_value": 100.0,
         "axis_profile": "investmentidentifieraxis", "is_subsidiary": 0},
        {"issuer_name": "JV Feeder LLC", "report_date": "2025-12-31", "fair_value": 390.0,
         "axis_profile": "investmentidentifieraxis", "is_subsidiary": 0},  # off-scope
    ])


def _layer_template(**kw):
    base = {"scope_quarters": ["2026-03-31"],
            "selector": {"axis_profile": "investmentidentifieraxis",
                         "source_table": None, "is_subsidiary": None},
            "anchor_proof": {"kind": "named_anchor_gap", "cited_value": 500.0,
                             "tolerance_pct": 0.5,
                             "citation": "companyfacts fv gap 2026-03-31"}}
    base.update(kw)
    return base


def test_layer_exclusion_drops_selected_layer_in_scope_only():
    df, audit = ap.apply_layer_exclusion(_layer_frame(), _layer_template())
    assert audit["status"] == "ok"
    assert audit["rows_dropped"] == 2 and audit["fv_dropped"] == 500.0
    assert len(df) == 3
    # off-scope quarter's bare-axis row is retained
    assert (df["report_date"] == "2025-12-31").sum() == 1


def test_layer_exclusion_refuses_non_whitelist_selector_field():
    t = _layer_template(selector={"issuer_name": "JV Feeder LLC"})
    df, audit = ap.apply_layer_exclusion(_layer_frame(), t)
    assert audit["status"] == "error" and audit["rows_dropped"] == 0
    assert len(df) == 5


def test_layer_exclusion_requires_scope_quarters_and_a_selector_value():
    t1 = _layer_template(scope_quarters=[])
    _, a1 = ap.apply_layer_exclusion(_layer_frame(), t1)
    assert a1["status"] == "error"
    t2 = _layer_template(selector={"axis_profile": None, "source_table": None,
                                   "is_subsidiary": None})
    _, a2 = ap.apply_layer_exclusion(_layer_frame(), t2)
    assert a2["status"] == "error"


def test_layer_exclusion_null_selector_never_matches_null_data():
    # A NULL selector field must not match rows where the column is NULL/missing.
    df = _layer_frame()
    df.loc[2, "axis_profile"] = None
    t = _layer_template(selector={"axis_profile": "investmentidentifieraxis",
                                  "source_table": None, "is_subsidiary": None})
    out, audit = ap.apply_layer_exclusion(df, t)
    assert audit["rows_dropped"] == 1  # only the non-null exact match in scope


def test_run_corrections_fills_structural_identity_on_added_rows():
    # 2026-08-30 trial-gate defect: missing_position_add rows carry only the position
    # fields; without the cik/source fill (which agent_promoted does in production)
    # the trial CSV had a NULL-cik row, the cik column went float64, and
    # filter_holdings_cik dropped EVERY row of the trial frame at the gate.
    base = _holdings().assign(cik="0001715933", source="bdc")
    corrections = [{"cik": "0001715933", "fix_class": "missing_position_add",
                    "template": {"positions": [
                        {"source_row_id": "src:acc-1:ctx-9", "issuer_name": "Gamma Warrant",
                         "report_date": "2025-03-31", "fair_value": 250.0}]}}]
    df, audits = ap.run_corrections(base, corrections)
    assert audits[0]["status"] == "ok"
    added = df[df["issuer_name"] == "Gamma Warrant"]
    assert len(added) == 1
    assert added["cik"].iloc[0] == "0001715933"
    assert added["source"].iloc[0] == "bdc"


# --------------------------------------------------------------------------- 2026-08-13 expansion


def _value_frame():
    return pd.DataFrame([
        {"issuer_name": "Alpha Corp", "bdc_investment_identifier": "Alpha Corp TL",
         "report_date": "2025-12-31", "fair_value": 1000.0, "cost": 900.0,
         "principal_amount": None, "interest_rate": 0.105, "pik_rate": None,
         "basis_spread": 5.0, "asset_class": "PRIVATE_CREDIT"},
        {"issuer_name": "Beta LLC", "bdc_investment_identifier": "Beta LLC 2L",
         "report_date": "2025-12-31", "fair_value": 2000.0, "cost": 2100.0,
         "principal_amount": 2050.0, "interest_rate": 11.5, "pik_rate": 2.0,
         "basis_spread": 6.0, "asset_class": "PRIVATE_CREDIT"},
    ])


def test_rate_rescale_selected_rows_only():
    df, audit = ap.apply_rate_rescale(_value_frame(), {
        "field": "interest_rate", "factor": 100,
        "row_selector": {"issuer_name": "Alpha Corp"}})
    assert audit["status"] == "ok" and audit["rows_changed"] == 1
    assert df.loc[df["issuer_name"] == "Alpha Corp", "interest_rate"].iloc[0] == 10.5
    assert df.loc[df["issuer_name"] == "Beta LLC", "interest_rate"].iloc[0] == 11.5
    assert audit["fv_delta"] == 0.0


def test_rate_rescale_missing_selector_column_fails_safe():
    df, audit = ap.apply_rate_rescale(_value_frame(), {
        "field": "interest_rate", "factor": 100, "row_selector": {"table_index": 5}})
    assert audit["status"] == "error"
    assert df["interest_rate"].tolist() == [0.105, 11.5]


def test_unit_rescale_fair_value_records_delta():
    df, audit = ap.apply_unit_rescale(_value_frame(), {
        "field": "fair_value", "factor": 1000,
        "row_selector": {"issuer_name": "Alpha Corp"}})
    assert audit["status"] == "ok" and audit["rows_changed"] == 1
    assert audit["fv_delta"] == 999000.0
    assert df.loc[df["issuer_name"] == "Beta LLC", "fair_value"].iloc[0] == 2000.0


def test_column_remap_moves_and_clears():
    frame = _value_frame()
    df, audit = ap.apply_column_remap(frame, {
        "from_field": "basis_spread", "to_field": "principal_amount",
        "row_selector": {"issuer_name": "Alpha Corp"}})
    assert audit["status"] == "ok" and audit["rows_changed"] == 1
    a = df[df["issuer_name"] == "Alpha Corp"].iloc[0]
    assert a["principal_amount"] == 5.0 and pd.isna(a["basis_spread"])
    b = df[df["issuer_name"] == "Beta LLC"].iloc[0]
    assert b["principal_amount"] == 2050.0 and b["basis_spread"] == 6.0
    assert audit["rows_overwritten"] == 0


def test_column_remap_counts_overwrites():
    df, audit = ap.apply_column_remap(_value_frame(), {
        "from_field": "basis_spread", "to_field": "principal_amount",
        "row_selector": {"issuer_name": "Beta LLC"}})
    assert audit["rows_overwritten"] == 1  # Beta already had principal_amount


def test_classification_fix_sets_value_and_records_prior():
    df, audit = ap.apply_classification_fix(_value_frame(), {
        "field": "asset_class", "value": "PRIVATE_EQUITY",
        "row_selector": {"issuer_name": "Alpha Corp"}})
    assert audit["status"] == "ok" and audit["rows_changed"] == 1
    assert df.loc[df["issuer_name"] == "Alpha Corp", "asset_class"].iloc[0] == "PRIVATE_EQUITY"
    assert audit["prior_values"] == {"PRIVATE_CREDIT": 1}
    assert df.loc[df["issuer_name"] == "Beta LLC", "asset_class"].iloc[0] == "PRIVATE_CREDIT"


def test_all_pik_normalization_sets_legs():
    df, audit = ap.apply_all_pik_normalization(_value_frame(), {
        "row_selector": {"issuer_name": "Beta LLC"},
        "cash_rate": 9.5, "pik_rate": 2.5, "set_interest_to_cash": True})
    assert audit["status"] == "ok" and audit["rows_changed"] == 1
    b = df[df["issuer_name"] == "Beta LLC"].iloc[0]
    assert b["interest_rate"] == 9.5 and b["pik_rate"] == 2.5


def test_all_pik_normalization_requires_a_leg():
    _, audit = ap.apply_all_pik_normalization(_value_frame(), {
        "row_selector": {"issuer_name": "Beta LLC"}})
    assert audit["status"] == "error"


def test_missing_position_add_requires_source_row_id():
    _, audit = ap.apply_missing_position_add(_value_frame(), {
        "positions": [{"issuer_name": "Gamma Bill", "fair_value": 500.0,
                       "report_date": "2025-12-31"}]})
    assert audit["status"] == "error"
    assert "source_row_id" in audit["message"]


def test_missing_position_add_appends_grounded_position():
    df, audit = ap.apply_missing_position_add(_value_frame(), {
        "positions": [{"issuer_name": "Gamma Bill", "fair_value": 500.0,
                       "report_date": "2025-12-31", "source_row_id": "SRC-42"}]})
    assert audit["status"] == "ok" and audit["rows_changed"] == 1
    assert len(df) == 3 and audit["fv_delta"] == 500.0
    assert audit["source_row_ids"] == ["SRC-42"]
    # source_row_id is grounding metadata, never a holdings column
    assert "source_row_id" not in df.columns


# --------------------------------------------------------------- quarter scoping (2026-08-13)


def _two_quarter_frame():
    return pd.DataFrame([
        {"issuer_name": "Alpha Corp", "report_date": "2025-12-31",
         "fair_value": 1000.0, "interest_rate": 0.105},
        {"issuer_name": "Alpha Corp", "report_date": "2023-09-30",
         "fair_value": 900.0, "interest_rate": 0.100},  # same defect, historical
        {"issuer_name": "Alpha Corp", "report_date": "2023-06-30",
         "fair_value": 800.0, "interest_rate": 9.5},    # historical, already correct
    ])


def test_apply_scoped_protects_out_of_scope_quarters():
    # The selector matches ALL Alpha rows; the scope physically restricts the applier
    # to 2025-12-31 -- the historical rows cannot be touched.
    corr = {"fix_class": "rate_rescale", "scope": {"quarters": ["2025-12-31"]},
            "template": {"field": "interest_rate", "factor": 100,
                         "row_selector": {"issuer_name": "Alpha Corp"}}}
    df, audit = ap.apply_scoped(_two_quarter_frame(), corr)
    assert audit["status"] == "ok" and audit["rows_changed"] == 1
    assert audit["rows_out_of_scope_protected"] == 2
    by_q = df.set_index("report_date")["interest_rate"]
    assert by_q["2025-12-31"] == 10.5
    assert by_q["2023-09-30"] == 0.100   # untouched despite matching selector
    assert by_q["2023-06-30"] == 9.5
    # original row order preserved
    assert df["report_date"].tolist() == ["2025-12-31", "2023-09-30", "2023-06-30"]


def test_apply_scoped_multi_quarter_evidence():
    # A defect evidenced in BOTH quarters may scope both -- and still leaves the
    # correct quarter alone only via its own evidence, not accident.
    corr = {"fix_class": "rate_rescale",
            "scope": {"quarters": ["2025-12-31", "2023-09-30"]},
            "template": {"field": "interest_rate", "factor": 100,
                         "row_selector": {"issuer_name": "Alpha Corp"}}}
    df, audit = ap.apply_scoped(_two_quarter_frame(), corr)
    assert audit["rows_changed"] == 2
    by_q = df.set_index("report_date")["interest_rate"]
    assert by_q["2025-12-31"] == 10.5 and by_q["2023-09-30"] == 10.0
    assert by_q["2023-06-30"] == 9.5


def test_apply_scoped_noop_when_no_rows_in_scope():
    corr = {"fix_class": "rate_rescale", "scope": {"quarters": ["2020-03-31"]},
            "template": {"field": "interest_rate", "factor": 100,
                         "row_selector": {"issuer_name": "Alpha Corp"}}}
    df, audit = ap.apply_scoped(_two_quarter_frame(), corr)
    assert audit["status"] == "ok" and audit["rows_changed"] == 0
    assert df["interest_rate"].tolist() == [0.105, 0.100, 9.5]


# --------------------------------------------------------------------------- 2026-08-21 row_id selector


def test_rate_rescale_selects_by_row_id():
    frame = _value_frame()
    frame["row_id"] = ["ROW-00000000000000aa", "ROW-00000000000000bb"]
    df, audit = ap.apply_rate_rescale(frame, {
        "field": "interest_rate", "factor": 100,
        "row_selector": {"row_id": "ROW-00000000000000aa"}})
    assert audit["status"] == "ok" and audit["rows_changed"] == 1
    assert df.loc[df["row_id"] == "ROW-00000000000000aa", "interest_rate"].iloc[0] == 10.5
    assert df.loc[df["row_id"] == "ROW-00000000000000bb", "interest_rate"].iloc[0] == 11.5


def test_row_id_selector_no_match_is_noop():
    # rate_rescale reports ok/rows_changed=0 on a no-match selector; the
    # no-op is refused downstream by the gate (selector_noop), not the applier.
    frame = _value_frame()
    frame["row_id"] = ["ROW-00000000000000aa", "ROW-00000000000000bb"]
    df, audit = ap.apply_rate_rescale(frame, {
        "field": "interest_rate", "factor": 100,
        "row_selector": {"row_id": "ROW-00000000000000cc"}})
    assert audit["status"] == "ok" and audit["rows_changed"] == 0
    assert df["interest_rate"].tolist() == [0.105, 11.5]


# --- selector lists + dedup row_selector (2026-08-21) -----------------------------


def test_dedup_row_selector_bounds_blast_radius():
    # Two duplicate GROUPS exist; a selector on one group's rows must leave the other
    # group untouched (q4b2r4an: key-only dedup for two cited rows collapsed 563 groups).
    df = pd.DataFrame([
        {"row_id": "ROW-aaaaaaaaaaaaaaaa", "issuer_name": "AAH Topco",
         "interest_rate": 9.06, "report_date": "2025-12-31", "fair_value": 100.0},
        {"row_id": "ROW-bbbbbbbbbbbbbbbb", "issuer_name": "AAH Topco",
         "interest_rate": 9.06, "report_date": "2025-12-31", "fair_value": 200.0},
        {"row_id": "ROW-cccccccccccccccc", "issuer_name": "Other Dup Co",
         "interest_rate": 5.0, "report_date": "2025-12-31", "fair_value": 300.0},
        {"row_id": "ROW-dddddddddddddddd", "issuer_name": "Other Dup Co",
         "interest_rate": 5.0, "report_date": "2025-12-31", "fair_value": 300.0},
    ])
    out, audit = ap.apply_dedup(df, {
        "match_fields": ["issuer_name", "interest_rate", "report_date"], "keep": "first",
        "row_selector": [{"row_id": "ROW-aaaaaaaaaaaaaaaa"},
                         {"row_id": "ROW-bbbbbbbbbbbbbbbb"}]})
    assert audit["status"] == "ok"
    assert audit["rows_dropped"] == 1                       # only the selected AAH dup
    assert (out["issuer_name"] == "Other Dup Co").sum() == 2  # other group untouched


def test_dedup_row_selector_no_match_fails_safe():
    df = _holdings()
    out, audit = ap.apply_dedup(df, {
        "match_fields": ["issuer_name", "report_date", "period"],
        "row_selector": {"issuer_name": "No Such Issuer"}})
    assert audit["status"] == "error"
    assert len(out) == len(df)


def test_selector_list_or_combines_rows():
    df = _holdings()
    out, audit = ap.apply_rate_rescale(df, {
        "field": "interest_rate", "factor": 0.1,
        "row_selector": [{"issuer_name": "WDE TorcSill"},
                         {"issuer_name": "Acme Term Loan"}]})
    assert audit["status"] == "ok"
    assert audit["rows_changed"] == 4       # both issuers' rows selected
    assert (pd.to_numeric(out["interest_rate"]) < 3).all()


def test_selector_list_entry_error_fails_whole_selector():
    df = _holdings()
    out, audit = ap.apply_rate_rescale(df, {
        "field": "interest_rate", "factor": 0.1,
        "row_selector": [{"issuer_name": "WDE TorcSill"},
                         {"nonexistent_col": "x"}]})
    assert audit["status"] == "error"
    assert "row_selector[1]" in audit["message"]
    assert (pd.to_numeric(out["interest_rate"]) > 3).any()  # unchanged


def test_source_anchored_value_sets_filing_value():
    df = pd.DataFrame([
        {"row_id": "ROW-00000000000000aa", "issuer_name": "AAM", "report_date": "2025-12-31",
         "interest_rate": None, "pik_rate": 12.0, "fair_value": 58702000.0},
        {"row_id": "ROW-00000000000000bb", "issuer_name": "Other", "report_date": "2025-12-31",
         "interest_rate": 9.0, "pik_rate": None, "fair_value": 995000.0},
    ])
    out, audit = ap.apply_source_anchored_value(df, {"assertions": [{
        "row_selector": {"row_id": "ROW-00000000000000aa"},
        "field": "interest_rate",
        "source": {"accession_number": "0001628280-26-020206", "table_index": 0,
                   "row_index": 1, "cell_index": 2, "quoted_text": "12.00 %",
                   "value": 12.0, "unit_multiplier": 1},
        "witnesses": [{"cell_index": 5, "field": "fair_value", "value": 58702}],
    }]})
    assert audit["status"] == "ok"
    assert audit["rows_changed"] == 1
    assert out.loc[out["row_id"] == "ROW-00000000000000aa", "interest_rate"].iloc[0] == 12.0
    assert out.loc[out["row_id"] == "ROW-00000000000000bb", "interest_rate"].iloc[0] == 9.0


def test_source_anchored_value_all_or_nothing():
    df = pd.DataFrame([
        {"row_id": "ROW-00000000000000aa", "issuer_name": "AAM", "report_date": "2025-12-31",
         "interest_rate": 1.0, "fair_value": 100.0},
    ])
    out, audit = ap.apply_source_anchored_value(df, {"assertions": [
        {"row_selector": {"row_id": "ROW-00000000000000aa"}, "field": "interest_rate",
         "source": {"value": 12.0}},
        {"row_selector": {"row_id": "ROW-00000000000000zz"}, "field": "interest_rate",
         "source": {"value": 8.0}},
    ]})
    assert audit["status"] == "error"
    assert "matched no rows" in audit["message"]
    assert out.loc[0, "interest_rate"] == 1.0   # first assertion NOT applied
