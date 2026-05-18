"""Trend computation for validation rule aggregate history."""

from __future__ import annotations

import math

import pandas as pd


TREND_COLUMNS = [
    "rule_id",
    "category",
    "prior_hit_count",
    "current_hit_count",
    "delta_pct",
    "prior_affected_fair_value",
    "current_affected_fair_value",
    "affected_fair_value_delta_pct",
    "consecutive_non_pass_runs",
    "trend_flag",
]


def _numeric(value: object) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return 0.0
    return float(parsed)


def _pct_delta(current: float, prior: float) -> float | None:
    if prior == 0:
        return None
    return (current - prior) / abs(prior)


def _status(value: object) -> str:
    status = str(value or "").strip().upper()
    if status == "SKIP":
        return "SKIPPED"
    return status or "PASS"


def _is_non_pass(value: object) -> bool:
    return _status(value) != "PASS"


def _sort_history(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    sorted_df = df.copy()
    if "run_timestamp" in sorted_df.columns:
        sorted_df["_sort_ts"] = pd.to_datetime(
            sorted_df["run_timestamp"], errors="coerce", utc=True
        )
    else:
        sorted_df["_sort_ts"] = pd.NaT
    sorted_df["_sort_pos"] = range(len(sorted_df))
    return sorted_df.sort_values(
        ["_sort_ts", "_sort_pos"], kind="mergesort", na_position="first"
    ).drop(columns=["_sort_ts", "_sort_pos"])


def _consecutive_non_pass(prior_rows: pd.DataFrame, current_row: pd.Series) -> int:
    rows = prior_rows.copy()
    if "run_id" in rows.columns:
        rows = rows[rows["run_id"].astype(str) != str(current_row.get("run_id", ""))]
    statuses = list(_sort_history(rows).get("status", pd.Series(dtype=object)))
    statuses.append(current_row.get("status", "PASS"))
    count = 0
    for status in reversed(statuses):
        if not _is_non_pass(status):
            break
        count += 1
    return count


def _latest_prior(prior_rows: pd.DataFrame, current_run_id: object) -> pd.Series | None:
    if prior_rows.empty:
        return None
    rows = prior_rows.copy()
    if "run_id" in rows.columns:
        rows = rows[rows["run_id"].astype(str) != str(current_run_id)]
    if rows.empty:
        return None
    return _sort_history(rows).iloc[-1]


def _flag(
    prior: pd.Series | None,
    current_row: pd.Series,
    prior_hits: float,
    current_hits: float,
    prior_fv: float,
    current_fv: float,
    consecutive: int,
) -> str:
    if prior is None:
        return "NEW"
    hit_delta = _pct_delta(current_hits, prior_hits)
    fv_delta = _pct_delta(current_fv, prior_fv)
    if (
        (prior_hits == 0 and current_hits > 0)
        or (hit_delta is not None and hit_delta > 0.50)
        or (fv_delta is not None and fv_delta > 0.25)
        or (prior_fv == 0 and current_fv > 0)
    ):
        return "REGRESSION"
    if _is_non_pass(current_row.get("status", "PASS")) and consecutive >= 4:
        return "CHRONIC"
    if (
        hit_delta is not None
        and fv_delta is not None
        and hit_delta < -0.50
        and fv_delta < -0.25
    ):
        return "IMPROVING"
    return "STABLE"


def _display_number(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def compute_trends(
    history_df: pd.DataFrame,
    current_aggregate_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compare the current rule aggregate to the latest prior comparable run."""
    if current_aggregate_df.empty:
        return pd.DataFrame(columns=TREND_COLUMNS)
    history = history_df.copy() if history_df is not None else pd.DataFrame()
    rows: list[dict] = []
    for _, current in current_aggregate_df.iterrows():
        rule_id = current["rule_id"]
        current_run_id = current.get("run_id", "")
        prior_rows = (
            history[history["rule_id"].astype(str) == str(rule_id)]
            if not history.empty and "rule_id" in history.columns
            else pd.DataFrame()
        )
        prior = _latest_prior(prior_rows, current_run_id)
        current_hits = _numeric(current.get("hit_count", 0))
        current_fv = _numeric(current.get("affected_fair_value", 0))
        prior_hits = _numeric(prior.get("hit_count", 0)) if prior is not None else 0.0
        prior_fv = _numeric(prior.get("affected_fair_value", 0)) if prior is not None else 0.0
        consecutive = _consecutive_non_pass(prior_rows, current)
        hit_delta = _pct_delta(current_hits, prior_hits) if prior is not None else None
        fv_delta = _pct_delta(current_fv, prior_fv) if prior is not None else None
        rows.append({
            "rule_id": rule_id,
            "category": current.get("category", ""),
            "prior_hit_count": int(prior_hits) if prior is not None else 0,
            "current_hit_count": int(current_hits),
            "delta_pct": _display_number(hit_delta),
            "prior_affected_fair_value": prior_fv if prior is not None else 0.0,
            "current_affected_fair_value": current_fv,
            "affected_fair_value_delta_pct": _display_number(fv_delta),
            "consecutive_non_pass_runs": consecutive,
            "trend_flag": _flag(
                prior,
                current,
                prior_hits,
                current_hits,
                prior_fv,
                current_fv,
                consecutive,
            ),
        })
    return pd.DataFrame(rows, columns=TREND_COLUMNS)
