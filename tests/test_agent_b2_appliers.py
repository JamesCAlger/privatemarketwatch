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
