"""Tests for the sample trial build's summary and comparison (scripts/rebuild_sample_trial.py)."""

from __future__ import annotations

import pandas as pd

from scripts import rebuild_sample_trial as rst

Q1, Q2 = "2025-12-31", "2026-03-31"


def _rows(*rows) -> pd.DataFrame:
    columns = ["row_id", "cik", "report_date", "fair_value", "cost", "issuer_name",
               "accounting_record_class", "entity_id"]
    return pd.DataFrame([dict(zip(columns, r)) for r in rows], columns=columns)


def test_summary_sums_the_published_basis_per_fund_quarter():
    frame = _rows(("R1", "0000000001", Q1, "100", "90", "A", "parent_schedule", "E1"),
                  ("R2", "0000000001", Q1, "50", "", "B", "parent_schedule", "E2"),
                  ("R3", "0000000001", Q1, "700", "700", "JV loan", "underlying_schedule", "E3"),
                  ("R4", "0000000001", Q2 + " 00:00:00", "10", "10", "A", "parent_schedule", "E1"))
    summary = rst.fund_quarter_summary(frame).set_index(["cik", "report_date"])
    first = summary.loc[("0000000001", Q1)]
    assert (first["rows"], first["published_rows"]) == (3, 2)
    assert (first["fair_value"], first["cost"]) == (150.0, 90.0)
    assert summary.loc[("0000000001", Q2), "fair_value"] == 10.0   # timestamp suffix folded


def test_compare_reports_added_removed_and_changed_rows_ignoring_order():
    before = _rows(("R1", "0000000001", Q1, "100", "90", "A", "parent_schedule", "E1"),
                   ("R2", "0000000001", Q1, "50", "45", "B", "parent_schedule", "E2"),
                   ("R3", "0000000001", Q1, "7", "7", "C", "parent_schedule", "E3"))
    after = _rows(("R4", "0000000001", Q1, "9", "9", "D", "parent_schedule", "E4"),
                  ("R2", "0000000001", Q1, "55", "45", "B", "parent_schedule", "E2"),
                  ("R1", "0000000001", Q1, "100", "90", "A", "parent_schedule", "E1"))
    report = rst.compare_runs(before, after)
    assert report["rows_added"] == ["R4"] and report["rows_removed"] == ["R3"]
    assert report["rows_changed"] == 1
    assert report["changed_by_column"] == {"fair_value": 1}
    delta = report["fund_quarters"][0]
    assert (delta["cik"], delta["report_date"]) == ("0000000001", Q1)
    assert delta["fair_value_before"] == 157.0 and delta["fair_value_after"] == 164.0
    assert delta["fair_value_delta"] == 7.0


def test_compare_treats_blank_and_missing_as_equal_and_numbers_by_value():
    before = _rows(("R1", "0000000001", Q1, "100.0", None, "A", "parent_schedule", "E1"))
    after = _rows(("R1", "0000000001", Q1, "100", "", "A", "parent_schedule", "E1"))
    report = rst.compare_runs(before, after)
    assert report["rows_changed"] == 0 and report["changed_by_column"] == {}
    assert report["fund_quarters"] == []


def test_cross_fund_columns_are_reported_apart_from_real_changes():
    before = _rows(("R1", "0000000001", Q1, "100", "90", "A", "parent_schedule", "E1"))
    after = _rows(("R1", "0000000001", Q1, "100", "90", "A", "parent_schedule", "E9"))
    report = rst.compare_runs(before, after)
    assert report["rows_changed"] == 0
    assert report["cross_fund_changes"] == {"entity_id": 1}


def test_identical_runs_report_nothing():
    frame = _rows(("R1", "0000000001", Q1, "100", "90", "A", "parent_schedule", "E1"))
    report = rst.compare_runs(frame, frame.copy())
    assert report["identical"] is True
    assert rst.compare_runs(frame, frame.iloc[0:0])["identical"] is False


def test_default_ciks_come_from_the_acceptance_scope():
    assert rst.default_ciks() == ["0001287750", "0001803498", "0001812554",
                                  "0001837532", "0001838126"]
