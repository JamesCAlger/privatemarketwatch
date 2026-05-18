"""Shared display status helpers for validation summaries."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


STATUS_ORDER = ("FAIL", "WARN", "SKIP", "PASS")


def normalize_status(status: object) -> str:
    """Normalize validation status labels for display without changing CSV schemas."""
    value = str(status or "").strip().upper()
    if value in {"SKIP", "SKIPPED"}:
        return "SKIP"
    if value in {"PASS", "WARN", "FAIL"}:
        return value
    return value or "PASS"


def status_from_reports(reports: Mapping[str, object]) -> str:
    """Summarize report dictionaries that use non-empty frames as warnings."""
    if any(len(df) for df in reports.values()):
        return "WARN"
    return "PASS"


def status_from_rule_aggregate(aggregate_df: pd.DataFrame) -> str:
    """Summarize rule aggregate statuses using display-normalized labels."""
    if aggregate_df.empty or "status" not in aggregate_df.columns:
        return "PASS"
    statuses = {normalize_status(status) for status in aggregate_df["status"]}
    for status in STATUS_ORDER:
        if status in statuses:
            return status
    return "PASS"
