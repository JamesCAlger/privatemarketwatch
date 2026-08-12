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
