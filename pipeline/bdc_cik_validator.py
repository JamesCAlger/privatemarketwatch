"""CIK-level validation packet helpers for BDC review agents.

This module combines existing validation artifacts into the packet shape used
by the BDC CIK validator skill.  It is intentionally additive: source
reconciliation remains the row-level authority and GAV remains an independent
fund-level gate/context signal.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

import pandas as pd


STRONG_GAV_SOURCE = "investments_at_fair_value"
MODERATE_GAV_SOURCES = {"total_assets_companyfacts"}
CONTEXT_ONLY_GAV_SCOPES = {"non_indexable_denominator"}


def normalize_cik(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.zfill(10) if digits else ""


def gav_gate_role(gav_row: dict[str, Any] | pd.Series) -> str:
    """Return ``strong_gate``, ``moderate_gate``, or ``context_only``.

    The distinction follows denominator strength, not whether the ratio is
    currently passing.  Weak, missing, ambiguous, or non-indexable denominators
    stay context-only so they cannot independently block a CIK correction.
    """
    row = dict(gav_row)
    source = str(row.get("comparison_source") or row.get("comparison_denominator_source") or "")
    evidence_scope = str(row.get("gav_evidence_scope") or "")
    confidence = str(row.get("comparison_confidence") or "").upper()
    comparison_value = pd.to_numeric(pd.Series([row.get("comparison_value")]), errors="coerce").iloc[0]

    if evidence_scope in CONTEXT_ONLY_GAV_SCOPES or pd.isna(comparison_value):
        return "context_only"
    if source == STRONG_GAV_SOURCE and confidence in {"", "STRONG"}:
        return "strong_gate"
    if source in MODERATE_GAV_SOURCES and confidence in {"", "MODERATE"}:
        return "moderate_gate"
    return "context_only"


def gav_condition(gav_row: dict[str, Any] | pd.Series) -> str:
    """Classify a GAV row for the CIK validation matrix."""
    row = dict(gav_row)
    role = gav_gate_role(row)
    flag = str(row.get("flag") or "")
    status = str(row.get("reconciliation_status") or "")
    if role == "context_only":
        if flag == "no_comparison" or status == "SKIP":
            return "missing_or_weak"
        return "weak_context"
    if flag in {"under_coverage", "over_coverage"}:
        return flag
    if status in {"PASS", "WARN", "FAIL"}:
        return "ok" if flag == "ok" and status == "PASS" else flag or status.lower()
    return "missing_or_weak"


def validation_matrix_cell(has_source_blockers: bool, gav_cond: str) -> str:
    """Combine row-level source blockers with GAV condition."""
    if gav_cond in {"missing_or_weak", "weak_context"}:
        return (
            "source_blockers_gav_context_only"
            if has_source_blockers
            else "source_ok_gav_context_only"
        )
    if has_source_blockers and gav_cond == "under_coverage":
        return "source_blockers_gav_undercoverage"
    if has_source_blockers and gav_cond == "ok":
        return "source_blockers_gav_ok"
    if not has_source_blockers and gav_cond == "over_coverage":
        return "source_ok_gav_overcoverage"
    if has_source_blockers:
        return f"source_blockers_gav_{gav_cond}"
    return f"source_ok_gav_{gav_cond}"


def build_cik_validation_packet(
    cik: str,
    report_dates: Optional[Iterable[str]] = None,
    *,
    holdings_df: Optional[pd.DataFrame] = None,
    source_residual_df: Optional[pd.DataFrame] = None,
    source_only_df: Optional[pd.DataFrame] = None,
    gav_df: Optional[pd.DataFrame] = None,
    pct_df: Optional[pd.DataFrame] = None,
    purity_df: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """Build the packet consumed by the BDC CIK validation skill.

    Callers pass already-built validation DataFrames so this helper does not
    trigger extraction or downloads.
    """
    norm_cik = normalize_cik(cik)
    dates = sorted({str(d) for d in report_dates or [] if str(d)})

    holdings = _filter_cik(holdings_df, norm_cik, dates)
    source_residual = _filter_cik(source_residual_df, norm_cik, dates)
    source_only = _filter_cik(source_only_df, norm_cik, dates)
    gav = _filter_cik(gav_df, norm_cik, dates)
    pct = _filter_cik(pct_df, norm_cik, dates)
    purity = _filter_cik(purity_df, norm_cik, dates)

    packet_dates = sorted(set(dates) | _dates_from(holdings) | _dates_from(gav))
    blocker_rows = _source_blocker_rows(source_residual, source_only)
    blocker_count = len(blocker_rows)

    gav_rows = []
    for row in gav.to_dict("records"):
        gate_role = gav_gate_role(row)
        condition = gav_condition(row)
        gav_rows.append({
            "report_date": str(row.get("report_date", "")),
            "gate_role": gate_role,
            "condition": condition,
            "status": str(row.get("reconciliation_status", "")),
            "flag": str(row.get("flag", "")),
            "comparison_source": str(row.get("comparison_source", "")),
            "denominator_scope": str(row.get("denominator_scope", "")),
            "gav_ratio": _number_or_none(row.get("gav_ratio")),
            "gav_ratio_adjusted": _number_or_none(row.get("gav_ratio_adjusted")),
            "gav_evidence_scope": str(row.get("gav_evidence_scope", "")),
        })

    matrix = []
    for report_date in packet_dates:
        date_blockers = [
            row for row in blocker_rows if str(row.get("report_date", "")) == report_date
        ]
        date_gav = next((row for row in gav_rows if row["report_date"] == report_date), None)
        condition = date_gav["condition"] if date_gav else "missing_or_weak"
        matrix.append({
            "report_date": report_date,
            "source_blockers": len(date_blockers),
            "gav_condition": condition,
            "matrix_cell": validation_matrix_cell(bool(date_blockers), condition),
        })

    return {
        "schema_version": "bdc-cik-validation-packet.v1",
        "cik": norm_cik,
        "report_dates": packet_dates,
        "source_reconciliation": {
            "blocker_count": blocker_count,
            "blockers": blocker_rows[:25],
            "residual_mechanisms": _mechanism_summary(source_residual),
            "source_only_blockers": _records(source_only),
        },
        "unified_holdings_summary": _holdings_summary(holdings),
        "gav_reconciliation": {
            "rows": gav_rows,
            "gate_summary": _count_by(gav_rows, "gate_role"),
        },
        "position_quality_context": {
            "pct_of_net_assets": _records(pct),
            "position_purity": _records(purity),
            "aggregate_leak_context": _aggregate_leak_context(purity),
        },
        "validation_matrix": matrix,
    }


def _filter_cik(df: Optional[pd.DataFrame], cik: str, dates: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "cik" not in out.columns:
        return pd.DataFrame(columns=out.columns)
    out["_norm_cik"] = out["cik"].map(normalize_cik)
    out = out[out["_norm_cik"] == cik].drop(columns=["_norm_cik"])
    if dates and "report_date" in out.columns:
        out = out[out["report_date"].astype(str).isin(dates)]
    return out


def _dates_from(df: pd.DataFrame) -> set[str]:
    if df.empty or "report_date" not in df.columns:
        return set()
    return {str(d) for d in df["report_date"].dropna().astype(str) if str(d)}


def _source_blocker_rows(
    source_residual: pd.DataFrame,
    source_only: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not source_residual.empty and "blocking_issue" in source_residual.columns:
        mask = source_residual["blocking_issue"].astype(str).str.lower().isin(["true", "1", "yes"])
        rows.extend(_records(source_residual[mask]))
    if not source_only.empty and "is_blocking" in source_only.columns:
        mask = source_only["is_blocking"].astype(str).str.lower().isin(["true", "1", "yes"])
        rows.extend(_records(source_only[mask]))
    return rows


def _holdings_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"row_count": 0, "fair_value": 0.0, "by_report_date": []}
    fair_value = _numeric_series(df, "fair_value").fillna(0)
    summary = df.assign(_fair_value=fair_value)
    by_date = (
        summary.groupby("report_date", dropna=False)
        .agg(row_count=("report_date", "size"), fair_value=("_fair_value", "sum"))
        .reset_index()
        .sort_values("report_date")
        .to_dict("records")
        if "report_date" in summary.columns
        else []
    )
    return {
        "row_count": int(len(df)),
        "fair_value": float(fair_value.sum()),
        "by_report_date": by_date,
    }


def _mechanism_summary(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty or "mechanism" not in df.columns:
        return []
    grouped = (
        df.groupby("mechanism", dropna=False)
        .size()
        .reset_index(name="row_count")
        .sort_values(["row_count", "mechanism"], ascending=[False, True])
    )
    return _records(grouped)


def _aggregate_leak_context(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"subtotal_candidate_rows": 0, "duplicate_dimension_candidate_rows": 0}
    return {
        "subtotal_candidate_rows": int(
            _numeric_series(df, "subtotal_candidate_rows").fillna(0).sum()
        ),
        "duplicate_dimension_candidate_rows": int(
            _numeric_series(df, "duplicate_dimension_candidate_rows").fillna(0).sum()
        ),
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return [
        {key: _json_value(value) for key, value in row.items()}
        for row in df.to_dict("records")
    ]


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([0] * len(df), index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _number_or_none(value: Any) -> Optional[float]:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(number) else float(number)
