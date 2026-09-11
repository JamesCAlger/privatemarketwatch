"""CIK-scoped oracle harness for BDC XBRL wrapper trials."""

from __future__ import annotations

import argparse
import json as json_mod
import logging
import math
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import pandas as pd

from pipeline.bdc_xbrl_wrapper import (
    add_bdc_xbrl_wrapper_columns,
    is_non_private_market_identifier,
    normalize_cik,
    normalize_wrapper_identifier,
    supported_prefixes_for_cik,
    supported_wrapper_ciks,
)

# Default CIK for oracle trials (Trinity Capital)
TRINITY_CIK = "0001786108"
from pipeline.wrapper_content_signatures import (
    WrapperDefinition,
    classify_content_signature_rows,
    load_wrapper_definition,
    validate_content_signatures,
    validate_fv_reconciliation,
)
from pipeline.config import (
    BDC_HOLDINGS_FILE,
    BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE,
    OUTPUT_DIR,
    OVERRIDES_DIR,
    SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.column_validation import validate_column_contracts
from pipeline.bdc_xbrl_oracle_exceptions import (
    ORACLE_EXCEPTION_SCHEMA_VERSION,
    load_bdc_xbrl_oracle_exceptions,
    reason_is_waived,
)
from pipeline.source_reconciliation import (
    DETAIL_COLUMNS,
    SOURCE_FACT_COLUMNS,
    _read_parquet_glob,
    reconcile_bdc_source_to_holdings,
)

logger = logging.getLogger(__name__)

ORACLE_SUMMARY_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "wrapper_source_rows",
    "wrapper_output_rows",
    "wrapper_rollup_candidates",
    "wrapper_leaf_outputs",
    "wrapper_leaf_source_rows",
    "cleared_rollup_rows",
    "cleared_rollup_fair_value",
    "remaining_blocking_rows",
    "remaining_blocking_fair_value",
    "remaining_wrapper_blocking_rows",
    "signature_fail_rows",
    "unclassified_prefix_rows",
    "unparsed_remainder_rows",
    "content_signature_pass_rate",
    "content_signature_violations",
    "unclassified_rate",
    "unclassified_rate_status",
    "unclassified_fv_rate",
    "unclassified_fv_rate_status",
    "fv_reconciliation_status",
    "fv_reconciliation_pct_diff",
    "exclusion_risk_count",
    "exclusion_risk_fv",
    "position_continuation_rate",
    "rate_outlier_count",
    "cost_fv_ratio_outlier_count",
    "parsed_field_quality_issue_count",
    "parsed_field_quality_fair_value",
    "fv_magnitude_shift",
    "rate_magnitude_shift",
    "concept_drift_flag",
    "unparsed_remainder_rate",
    "oracle_status",
    "oracle_fail_reasons",
]

# Default QoQ unclassified rate jump threshold (5 percentage points)
_UNCLASSIFIED_RATE_QOQ_JUMP_THRESHOLD = 0.05

# Position key continuation rate threshold (Gap #8)
_POSITION_CONTINUITY_MIN_RATE = 0.50

# QoQ unparsed_remainder_rate spike threshold in pp (Gap #5)
_UNPARSED_REMAINDER_QOQ_SPIKE_THRESHOLD = 0.10
_CONCEPT_DRIFT_CHURN_THRESHOLD = 0.30

# Gap #4 extension: per-field QoQ magnitude-shift detection
_MAGNITUDE_SHIFT_FIELDS = [
    "source_fair_value",
    "source_interest_rate",
    "source_cost",
    "source_basis_spread",
]
_MAGNITUDE_SHIFT_RATIO_THRESHOLD = 10.0  # 10x = one order of magnitude
_MAGNITUDE_SHIFT_MIN_VALUES = 5          # min non-null non-zero values per quarter

# Keywords indicating a row has real position data, used
# to detect false-positive exclusions (Gap #7)
_EXCLUSION_POSITION_EVIDENCE_TOKENS = [
    "type of investment",
    "investment type",
    "maturity date",
    "interest rate",
    "reference rate",
    "current coupon",
    "first lien",
    "1st lien",
    "second lien",
    "term loan",
    "revolving credit facility",
    "delayed draw",
]

_EXCLUSION_EVIDENCE_PATTERN = "|".join(
    re.escape(t) for t in _EXCLUSION_POSITION_EVIDENCE_TOKENS
)

PARSED_FIELD_QUALITY_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "accession_number",
    "source_row_id",
    "output_row_id",
    "bdc_investment_identifier",
    "column",
    "issue_type",
    "severity",
    "fair_value",
    "output_value",
    "evidence_token",
    "wrapper_disposition",
    "suggested_owner",
    "recommended_action",
]

ROW_DELTA_ATTRIBUTION_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "accession_number",
    "delta_type",
    "row_count",
    "fair_value_abs_sum",
    "production_row_count",
    "trial_row_count",
    "production_fair_value_abs_sum",
    "trial_fair_value_abs_sum",
    "sample_identifier",
    "sample_position_key",
    "changed_columns",
    "production_value",
    "trial_value",
    "likely_mechanism",
    "owner",
    "review_status",
]

HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS = [
    "cik",
    "entity_name",
    "cluster_label",
    "affected_report_dates",
    "quarter_count",
    "row_count",
    "fair_value_abs_sum",
    "fair_value_share",
    "max_quarter_fair_value_share",
    "source_family_guess",
    "suggested_wrapper_family",
    "output_index_classification",
    "output_asset_category",
    "output_exposure_type",
    "sample_identifiers",
    "sample_issuer_names",
    "sample_instrument_descriptions",
    "suggested_review_question",
    "owner",
    "review_status",
]

AGENT_ISSUE_PACKET_COLUMNS = [
    "issue_id",
    "rule_id",
    "source_rule_id",
    "packet_type",
    "severity",
    "materiality_tier",
    "likely_owner",
    "review_status",
    "cik",
    "entity_name",
    "report_date",
    "accession_number",
    "source_row_id",
    "output_row_id",
    "production_column",
    "source_value",
    "output_value",
    "affected_fair_value",
    "affected_fair_value_pct",
    "affected_row_count",
    "affected_row_pct",
    "evidence",
    "recommended_action",
]

AGENT_CLUSTER_PACKET_COLUMNS = [
    "issue_id",
    "rule_id",
    "source_rule_id",
    "packet_type",
    "severity",
    "materiality_tier",
    "likely_owner",
    "review_status",
    "cik",
    "entity_name",
    "report_date",
    "affected_report_dates",
    "cluster_key",
    "cluster_label",
    "production_column",
    "affected_fair_value",
    "affected_fair_value_pct",
    "affected_row_count",
    "affected_row_pct",
    "evidence",
    "representative_rows_path",
    "recommended_action",
]

COLUMN_DRIFT_SUMMARY_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "column",
    "baseline_quarter_count",
    "row_count",
    "fair_value_abs_sum",
    "js_divergence",
    "new_bucket_share",
    "current_dominant_bucket",
    "baseline_dominant_bucket",
    "status",
    "severity",
    "materiality_tier",
    "bucket_distribution",
    "baseline_bucket_distribution",
]

COLUMN_DRIFT_EXAMPLE_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "column",
    "bucket",
    "bdc_investment_identifier",
    "issuer_name",
    "instrument_description",
    "output_value",
    "fair_value",
]

AGENT_VERDICT_SUMMARY_COLUMNS = [
    "verdict",
    "likely_owner",
    "materiality_tier",
    "issue_count",
    "affected_fair_value",
    "max_confidence",
    "promotion_effect",
]

_AGENT_VERDICT_ALLOWED_VALUES = frozenset({
    "true_wrapper_error",
    "false_positive",
    "inconclusive",
    "not_wrapper_owned",
    "real_filing_change",
    "source_format_change_normalized_ok",
})
_AGENT_VERDICT_ALLOWED_OWNERS = frozenset({
    "wrapper",
    "global_staging",
    "classification",
    "source_data",
    "enrichment",
    "validation_rule",
    "unknown",
})
_WRAPPER_SOFT_PACKET_RULE_IDS = {
    "WRAP.PARSED_FIELD_CONTAMINATION",
    "WRAP.SOURCE_CORRUPTED_IDENTIFIER",
    "WRAP.SOURCE_VERBOSE_IDENTIFIER",
    "WRAP.COST_FV_RATIO_OUTLIER",
    "WRAP.PRODUCTION_COLUMN_VALIDATION",
    "WRAP.ROW_DELTA_ATTRIBUTION",
    "WRAP.HIGH_FV_UNCLASSIFIED_CLUSTER",
    "WRAP.COLUMN_DISTRIBUTION_DRIFT",
    "WRAP.NO_WRAPPER_ROWS",
}
_MATERIALITY_P1_FV_ABS = 5_000_000.0
_MATERIALITY_P1_FV_PCT = 0.0025
_MATERIALITY_P0_FV_ABS = 25_000_000.0
_MATERIALITY_P0_FV_PCT = 0.01
_MATERIALITY_P1_ROW_ABS = 5
_MATERIALITY_P1_ROW_PCT = 0.02
_MATERIALITY_P0_ROW_ABS = 15
_MATERIALITY_P0_ROW_PCT = 0.05
_DRIFT_COLUMNS = [
    "issuer_name",
    "instrument_description",
    "bdc_investment_identifier",
    "position_key",
    "interest_rate",
    "basis_spread",
    "pik_rate",
    "maturity_date",
    "coupon_type",
    "reference_rate_type",
    "index_classification",
    "asset_category",
    "exposure_type",
    "asset_class",
]
_DRIFT_TEXT_COLUMNS = {
    "issuer_name",
    "instrument_description",
    "bdc_investment_identifier",
    "position_key",
}
_DRIFT_BASELINE_QUARTERS = 4
_DRIFT_MIN_BASELINE_QUARTERS = 2
_DRIFT_JS_THRESHOLD = 0.25
_DRIFT_NEW_BUCKET_SHARE_THRESHOLD = 0.20
_DRIFT_TEXT_JS_THRESHOLD = 0.12
_DRIFT_TEXT_NEW_BUCKET_SHARE_THRESHOLD = 0.10

_PARSED_FIELD_HIERARCHY_PATTERN = re.compile(
    r"non[-\s]?controlled|non[-\s]?affiliated|controlled investments?|"
    r"affiliated investments?|debt investments?|equity investments?|"
    r"short[-\s]?term investments?|cash equivalents?|senior loans?\s+\d",
    re.IGNORECASE,
)
_PARSED_FIELD_RATE_DATE_PATTERN = re.compile(
    r"interest rate|reference rate|current coupon|maturity date|"
    r"acquisition date|initial acquisition date|\bsofr\b|\blibor\b",
    re.IGNORECASE,
)
_PARSED_FIELD_EXPLICIT_RATE_DATE_PATTERN = re.compile(
    r"interest rate|reference rate|current coupon|maturity date|"
    r"acquisition date|initial acquisition date",
    re.IGNORECASE,
)
_PARSED_FIELD_LABEL_PATTERN = re.compile(
    r"type of investment|investment type|investment date|initial acquisition date|"
    r"maturity date|maturity/dissolution date|interest rate|reference rate|"
    r"current coupon|acquisition date|expiration date|cost|fair value",
    re.IGNORECASE,
)
_PARSED_SOURCE_SECTION_PATTERN = re.compile(
    r"non[-\s]?controlled|non[-\s]?affiliated|controlled investments?|"
    r"affiliated investments?|debt investments?|equity investments?|"
    r"short[-\s]?term investments?|cash equivalents?|senior loans?\s+\d|"
    r"portfolio company debt securities|portfolio company equity investments|"
    r"portfolio company warrant investments",
    re.IGNORECASE,
)
_PARSED_FIELD_PCT_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%")
_PARSED_POSITION_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_ROW_DELTA_AGGREGATE_PATTERN = re.compile(
    r"\b(sub[-\s]?total|total investments?|total debt investments?|"
    r"total equity investments?|portfolio investments?)\b",
    re.IGNORECASE,
)
_ROW_DELTA_CATEGORY_PREFIX_PATTERN = re.compile(
    r"^\s*(debt investments?|equity investments?|senior loans?|"
    r"short[-\s]?term investments?|cash equivalents?)\b",
    re.IGNORECASE,
)
_ROW_DELTA_NUMERIC_COLUMNS = [
    "fair_value",
    "cost",
    "principal_amount",
    "interest_rate",
    "basis_spread",
    "pik_rate",
]
_ROW_DELTA_CLASSIFICATION_COLUMNS = [
    "index_classification",
    "asset_class",
    "exposure_type",
    "asset_category",
    "issuer_category",
]
_ROW_DELTA_TEXT_COLUMNS = [
    "issuer_name",
    "instrument_description",
    "position_key",
]
_HIGH_FV_FUND_PATTERN = re.compile(
    r"\b(funds?|co[-\s]?invest(?:ment)?|lp interest|l\.p\.|limited partnership|"
    r"private credit|senior loan program)\b",
    re.IGNORECASE,
)
_HIGH_FV_DEBT_PATTERN = re.compile(
    r"\b(loan|debt|revolver|revolving|sofr|libor|term loan|first lien|"
    r"second lien|delayed draw|unitranche|notes?)\b",
    re.IGNORECASE,
)
_HIGH_FV_EQUITY_PATTERN = re.compile(
    r"\b(common stock|preferred|equity|shares?|units?)\b",
    re.IGNORECASE,
)
_HIGH_FV_WARRANT_PATTERN = re.compile(r"\bwarrants?\b", re.IGNORECASE)
_HIGH_FV_CLO_PATTERN = re.compile(
    r"\b(clo|collateralized loan obligation)\b",
    re.IGNORECASE,
)
_SOURCE_CORRUPTED_FIELD_TOKEN_PATTERN = re.compile(
    r"interest rate|reference rate|current coupon|maturity date|"
    r"investment date|type of investment|initial acquisition date",
    re.IGNORECASE,
)
_SOURCE_CORRUPTED_HIERARCHY_PCT_PATTERN = re.compile(
    r"\b(?:senior loans?|debt investments?|equity investments?|"
    r"non[-\s]?controlled|non[-\s]?affiliated)\b[^|,;]{0,80}\d+(?:\.\d+)?%",
    re.IGNORECASE,
)

REMAINING_MECHANISM_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "mechanism",
    "row_count",
    "source_fair_value",
    "candidate_output_count",
    "candidate_output_fair_value",
    "candidate_source_child_count",
    "candidate_source_child_fair_value",
    "raw_bdc_present_count",
    "unified_present_count",
    "sample_identifiers",
]

BASELINE_COMPARISON_COLUMNS = [
    "cik",
    "report_date",
    "current_blocking_rows",
    "baseline_blocking_rows",
    "blocking_rows_delta",
    "current_documented_source_rollup_exact_rows",
    "baseline_documented_source_rollup_exact_rows",
    "documented_rollup_delta",
    "current_blocking_fair_value",
    "baseline_blocking_fair_value",
    "blocking_fair_value_delta",
    "current_cleared_rollup_fair_value",
    "baseline_cleared_rollup_fair_value",
    "cleared_rollup_fair_value_delta",
]

QUEUE_COLUMNS = [
    "rank",
    "cik",
    "entity_name",
    "blocking_packets",
    "blocking_rows",
    "source_fair_value",
    "supported_wrapper",
    "mechanisms",
]

PROFILE_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "detected_prefix",
    "candidate_disposition",
    "recommended_action",
    "packet_count",
    "blocking_rows",
    "source_fair_value",
    "sample_identifiers",
]

CANDIDATE_RULE_COLUMNS = [
    "cik",
    "entity_name",
    "detected_prefix",
    "candidate_disposition",
    "recommended_action",
    "packet_count",
    "blocking_rows",
    "source_fair_value",
    "sample_identifiers",
]

QUEUE_SUMMARY_COLUMNS = [
    "cik",
    "entity_name",
    "supported_wrapper",
    "blocking_rows",
    "profile_rows",
    "candidate_rule_rows",
    "oracle_summary_rows",
    "oracle_remaining_blocking_rows",
    "status",
]

# ---------------------------------------------------------------------------
# Promotion gate
# ---------------------------------------------------------------------------

PROMOTION_GATE_COLUMNS = [
    "cik",
    "report_date",
    "current_blocking_rows",
    "baseline_blocking_rows",
    "blocking_rows_delta",
    "current_blocking_fv",
    "baseline_blocking_fv",
    "blocking_fv_delta",
    "current_cleared_rollup_rows",
    "baseline_cleared_rollup_rows",
    "cleared_rollup_delta",
    "current_unclassified_rate",
    "current_unclassified_fv_rate",
    "current_oracle_status",
    "waived_oracle_reasons",
    "unwaived_oracle_reasons",
    "effective_oracle_status",
    "quarter_verdict",
    "quarter_reasons",
]

# Oracle fail reasons that trigger hard promotion rejection
_PROMOTION_REJECT_REASONS = frozenset({
    "wrapper_blockers_remaining",
    "wrapper_no_archetypes",
})

# Oracle fail reasons that require human review before promotion
_PROMOTION_REVIEW_REASONS = frozenset({
    "unclassified_rate_exceeded",
    "unclassified_fv_rate_exceeded",
    "unclassified_rate_qoq_jump",
    "content_signatures_fail",
    "unparsed_remainder_rows",
    "exclusion_risk_detected",
    "low_position_continuity",
    "rate_outliers_detected",
    "cost_fv_ratio_outliers",
    "concept_drift_detected",
    "unparsed_remainder_spike",
    "fv_magnitude_shift_detected",
    "rate_magnitude_shift_detected",
    "cost_magnitude_shift_detected",
    "spread_magnitude_shift_detected",
})

_PROMOTION_EXCEPTION_ELIGIBLE_REASONS = frozenset({
    "unclassified_rate_exceeded",
    "unclassified_fv_rate_exceeded",
    "unclassified_rate_qoq_jump",
    "content_signatures_fail",
    "unparsed_remainder_rows",
    "unparsed_remainder_spike",
    "low_position_continuity",
    "rate_outliers_detected",
    "cost_fv_ratio_outliers",
    "concept_drift_detected",
    "fv_magnitude_shift_detected",
    "rate_magnitude_shift_detected",
    "cost_magnitude_shift_detected",
    "spread_magnitude_shift_detected",
})


@dataclass
class PromotionVerdict:
    """Result of evaluating a wrapper promotion gate."""
    status: str  # "promote", "reject", "review_required"
    blocking_rows_delta: int
    blocking_fv_delta: float
    reasons: list[str]
    improvements: list[str]
    per_quarter: pd.DataFrame


def _safe_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _slug(value: Any, *, max_len: int = 80) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip()).strip("-")
    return text[:max_len] or "blank"


def _packet_issue_id(
    *,
    cik: str,
    report_date: str,
    rule_id: str,
    unique: Any,
) -> str:
    return "|".join([
        "WRAP",
        normalize_cik(cik),
        str(report_date or ""),
        rule_id,
        _slug(unique, max_len=100),
    ])


def _quarter_totals(holdings_df: pd.DataFrame | None, *, cik: str) -> pd.DataFrame:
    columns = ["cik", "report_date", "total_fair_value_abs", "total_rows"]
    if holdings_df is None or holdings_df.empty:
        return pd.DataFrame(columns=columns)
    df = holdings_df.copy()
    if "cik" in df.columns:
        df["cik"] = df["cik"].map(normalize_cik)
        df = df[df["cik"].eq(normalize_cik(cik))].copy()
    else:
        df["cik"] = normalize_cik(cik)
    if "source" in df.columns:
        source = df["source"].fillna("").astype(str).str.lower()
        df = df[source.eq("bdc") | source.eq("")].copy()
    if "report_date" not in df.columns or df.empty:
        return pd.DataFrame(columns=columns)
    if "fair_value" not in df.columns:
        df["fair_value"] = 0
    df["_fv_abs"] = pd.to_numeric(df["fair_value"], errors="coerce").abs().fillna(0)
    return (
        df.groupby(["cik", "report_date"], dropna=False)
        .agg(
            total_fair_value_abs=("_fv_abs", "sum"),
            total_rows=("cik", "size"),
        )
        .reset_index()[columns]
    )


def _totals_for_report(
    quarter_totals: pd.DataFrame | None,
    *,
    cik: str,
    report_date: str,
) -> tuple[float, int]:
    if quarter_totals is None or quarter_totals.empty:
        return 0.0, 0
    qt = quarter_totals.copy()
    match = qt[
        qt["cik"].map(normalize_cik).eq(normalize_cik(cik))
        & qt["report_date"].astype(str).eq(str(report_date))
    ]
    if match.empty:
        return 0.0, 0
    row = match.iloc[0]
    return _safe_float(row.get("total_fair_value_abs", 0)), _safe_int(row.get("total_rows", 0))


def _materiality_metrics(
    *,
    affected_fair_value: Any,
    total_fair_value: Any,
    affected_rows: Any,
    total_rows: Any,
    quarter_count: int = 1,
) -> dict[str, Any]:
    affected_fv = abs(_safe_float(affected_fair_value))
    total_fv = abs(_safe_float(total_fair_value))
    affected_count = _safe_int(affected_rows)
    total_count = _safe_int(total_rows)
    fv_pct = affected_fv / total_fv if total_fv > 0 else 0.0
    row_pct = affected_count / total_count if total_count > 0 else 0.0

    p0_fv = affected_fv >= max(_MATERIALITY_P0_FV_ABS, _MATERIALITY_P0_FV_PCT * total_fv)
    p1_fv = affected_fv >= max(_MATERIALITY_P1_FV_ABS, _MATERIALITY_P1_FV_PCT * total_fv)
    p0_rows = affected_count >= max(
        _MATERIALITY_P0_ROW_ABS,
        math.ceil(_MATERIALITY_P0_ROW_PCT * total_count),
    )
    p1_rows = affected_count >= max(
        _MATERIALITY_P1_ROW_ABS,
        math.ceil(_MATERIALITY_P1_ROW_PCT * total_count),
    )

    if p0_fv or p0_rows:
        tier = "P0"
    elif p1_fv or p1_rows or (quarter_count >= 2 and affected_count > 0):
        tier = "P1"
    else:
        tier = "P2"
    return {
        "materiality_tier": tier,
        "affected_fair_value": round(affected_fv, 2),
        "affected_fair_value_pct": round(fv_pct, 6),
        "affected_row_count": affected_count,
        "affected_row_pct": round(row_pct, 6),
    }


def _write_jsonl_from_df(df: pd.DataFrame, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in df.fillna("").to_dict(orient="records"):
            fh.write(json_mod.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def _first_non_empty(row: pd.Series, *columns: str) -> str:
    for col in columns:
        value = row.get(col, "")
        if pd.notna(value) and str(value).strip():
            return str(value)
    return ""


def _normalize_delta_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _join_unique_values(series: pd.Series, *, limit: int = 3) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for value in series:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
        if len(values) >= limit:
            break
    return " | ".join(values)


def _format_delta_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(number):
        return ""
    return f"{number:.10g}"


def _sum_delta_numeric(series: pd.Series) -> float:
    return pd.to_numeric(series, errors="coerce").sum(min_count=1)


def _numeric_delta_changed(column: str, production_value: Any, trial_value: Any) -> bool:
    prod_blank = production_value is None or pd.isna(production_value) or str(production_value).strip() == ""
    trial_blank = trial_value is None or pd.isna(trial_value) or str(trial_value).strip() == ""
    if prod_blank and trial_blank:
        return False
    prod_num = pd.to_numeric(pd.Series([production_value]), errors="coerce").iloc[0]
    trial_num = pd.to_numeric(pd.Series([trial_value]), errors="coerce").iloc[0]
    if pd.isna(prod_num) or pd.isna(trial_num):
        return prod_blank != trial_blank or str(production_value).strip() != str(trial_value).strip()
    diff = abs(float(prod_num) - float(trial_num))
    scale = max(abs(float(prod_num)), abs(float(trial_num)))
    if column in {"fair_value", "cost", "principal_amount"}:
        tolerance = max(1.0, 0.0001 * scale)
    else:
        tolerance = max(0.0001, 0.0001 * scale)
    return diff > tolerance


def _filter_delta_holdings(df: pd.DataFrame | None, *, cik: str) -> pd.DataFrame:
    columns = [
        "cik",
        "entity_name",
        "source",
        "report_date",
        "accession_number",
        "bdc_investment_identifier",
        "investment_identifier",
        "position_key",
        *_ROW_DELTA_TEXT_COLUMNS,
        *_ROW_DELTA_CLASSIFICATION_COLUMNS,
        *_ROW_DELTA_NUMERIC_COLUMNS,
    ]
    columns = list(dict.fromkeys(columns))
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    out["cik"] = out["cik"].map(normalize_cik)
    out = out[out["cik"].eq(normalize_cik(cik))].copy()
    if "source" in out.columns:
        source = out["source"].fillna("").astype(str).str.lower()
        out = out[source.eq("bdc") | source.eq("")].copy()
    for col in _ROW_DELTA_NUMERIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[columns]


def _delta_row_key(row: pd.Series) -> str:
    cik = normalize_cik(row.get("cik", ""))
    report_date = str(row.get("report_date", "") or "")
    accession = str(row.get("accession_number", "") or "")
    identifier = _first_non_empty(
        row,
        "bdc_investment_identifier",
        "investment_identifier",
    )
    identifier_key = normalize_wrapper_identifier(identifier)
    if identifier_key:
        return "|".join(["id", cik, report_date, accession, identifier_key])
    position_key = normalize_wrapper_identifier(row.get("position_key", ""))
    fair_value = _format_delta_number(_safe_float(row.get("fair_value", 0)))
    return "|".join(["fallback", cik, report_date, accession, position_key, fair_value])


def _aggregate_delta_holdings(df: pd.DataFrame | None, *, cik: str) -> pd.DataFrame:
    filtered = _filter_delta_holdings(df, cik=cik)
    if filtered.empty:
        return pd.DataFrame()
    filtered["_delta_key"] = filtered.apply(_delta_row_key, axis=1)
    filtered["_fair_value_abs"] = filtered["fair_value"].abs().fillna(0)
    agg_spec: dict[str, Any] = {
        "cik": ("cik", "first"),
        "entity_name": ("entity_name", _join_unique_values),
        "report_date": ("report_date", "first"),
        "accession_number": ("accession_number", "first"),
        "row_count": ("cik", "size"),
        "fair_value_abs_sum": ("_fair_value_abs", "sum"),
        "sample_identifier": ("bdc_investment_identifier", _join_unique_values),
        "sample_position_key": ("position_key", _join_unique_values),
    }
    for col in _ROW_DELTA_TEXT_COLUMNS + _ROW_DELTA_CLASSIFICATION_COLUMNS:
        agg_spec[col] = (col, _join_unique_values)
    for col in _ROW_DELTA_NUMERIC_COLUMNS:
        agg_spec[f"{col}_sum"] = (col, _sum_delta_numeric)
    grouped = filtered.groupby("_delta_key", dropna=False).agg(**agg_spec).reset_index()
    missing_identifier = grouped["sample_identifier"].fillna("").astype(str).str.strip().eq("")
    if missing_identifier.any():
        grouped.loc[missing_identifier, "sample_identifier"] = grouped.loc[
            missing_identifier,
            "sample_position_key",
        ]
    return grouped


def _holding_looks_non_private(row: pd.Series) -> bool:
    exposure = str(row.get("exposure_type", "") or "").upper()
    index_class = str(row.get("index_classification", "") or "").upper()
    issuer_category = str(row.get("issuer_category", "") or "").upper()
    if exposure == "LIQUID" or index_class == "CASH" or issuer_category == "GOVERNMENT":
        return True
    text = " ".join(
        str(row.get(col, "") or "")
        for col in [
            "sample_identifier",
            "sample_position_key",
            "issuer_name",
            "instrument_description",
        ]
    )
    return is_non_private_market_identifier(text)


def _holding_looks_aggregate(row: pd.Series) -> bool:
    text = " ".join(
        str(row.get(col, "") or "")
        for col in [
            "sample_identifier",
            "sample_position_key",
            "issuer_name",
            "instrument_description",
        ]
    )
    if _ROW_DELTA_AGGREGATE_PATTERN.search(text):
        return True
    has_position_evidence = re.search(_EXCLUSION_EVIDENCE_PATTERN, text, re.IGNORECASE)
    return bool(_ROW_DELTA_CATEGORY_PREFIX_PATTERN.search(text) and not has_position_evidence)


def _row_delta_record(
    *,
    cik: str,
    delta_type: str,
    row_count: int,
    fair_value_abs_sum: float,
    production_row: pd.Series | None = None,
    trial_row: pd.Series | None = None,
    changed_columns: str = "",
    production_value: str = "",
    trial_value: str = "",
) -> dict[str, Any]:
    row = trial_row if trial_row is not None else production_row
    assert row is not None
    production_count = int(production_row.get("row_count", 0)) if production_row is not None else 0
    trial_count = int(trial_row.get("row_count", 0)) if trial_row is not None else 0
    production_fv = float(production_row.get("fair_value_abs_sum", 0)) if production_row is not None else 0.0
    trial_fv = float(trial_row.get("fair_value_abs_sum", 0)) if trial_row is not None else 0.0
    likely_mechanism_by_type = {
        "added_position_leaf": "trial adds a BDC row absent from current production",
        "removed_non_private": "trial removes a row that looks non-private or liquid",
        "removed_aggregate": "trial removes a row with subtotal or category hierarchy signals",
        "removed_position_leaf": "trial removes a row that does not have safe aggregate or non-private signals",
        "changed_index_classification": "trial changes one or more classification fields",
        "changed_issuer_name": "trial changes parsed issuer_name",
        "changed_instrument_description": "trial changes parsed instrument_description",
        "changed_position_key": "trial changes normalized position_key",
        "changed_numeric_value": "trial changes one or more numeric production fields",
        "unknown": "duplicate or ambiguous row group needs manual attribution",
    }
    review_status = "info" if delta_type in {"removed_non_private", "removed_aggregate"} else "review"
    return {
        "cik": cik,
        "entity_name": _first_non_empty(row, "entity_name"),
        "report_date": _first_non_empty(row, "report_date"),
        "accession_number": _first_non_empty(row, "accession_number"),
        "delta_type": delta_type,
        "row_count": row_count,
        "fair_value_abs_sum": round(float(fair_value_abs_sum), 2),
        "production_row_count": production_count,
        "trial_row_count": trial_count,
        "production_fair_value_abs_sum": round(production_fv, 2),
        "trial_fair_value_abs_sum": round(trial_fv, 2),
        "sample_identifier": _first_non_empty(row, "sample_identifier"),
        "sample_position_key": _first_non_empty(row, "sample_position_key"),
        "changed_columns": changed_columns,
        "production_value": production_value,
        "trial_value": trial_value,
        "likely_mechanism": likely_mechanism_by_type.get(delta_type, ""),
        "owner": "unknown" if delta_type == "unknown" else "wrapper",
        "review_status": review_status,
    }


def _value_summary(row: pd.Series, columns: list[str]) -> str:
    parts: list[str] = []
    for col in columns:
        value_col = f"{col}_sum" if col in _ROW_DELTA_NUMERIC_COLUMNS else col
        value = row.get(value_col, "")
        formatted = _format_delta_number(value) if col in _ROW_DELTA_NUMERIC_COLUMNS else str(value or "")
        parts.append(f"{col}={formatted}")
    return "; ".join(parts)


def _build_row_delta_attribution(
    trial_holdings_df: pd.DataFrame,
    production_holdings_df: pd.DataFrame | None,
    *,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    """Compare one-CIK trial holdings to current production holdings."""
    cik_norm = normalize_cik(cik)
    trial = _aggregate_delta_holdings(trial_holdings_df, cik=cik_norm)
    production = _aggregate_delta_holdings(production_holdings_df, cik=cik_norm)
    if trial.empty and production.empty:
        return pd.DataFrame(columns=ROW_DELTA_ATTRIBUTION_COLUMNS)

    records: list[dict[str, Any]] = []
    trial_by_key = {str(row["_delta_key"]): row for _, row in trial.iterrows()} if not trial.empty else {}
    production_by_key = {
        str(row["_delta_key"]): row for _, row in production.iterrows()
    } if not production.empty else {}

    for key in sorted(set(trial_by_key) | set(production_by_key)):
        trial_row = trial_by_key.get(key)
        production_row = production_by_key.get(key)
        if production_row is None and trial_row is not None:
            records.append(
                _row_delta_record(
                    cik=cik_norm,
                    delta_type="added_position_leaf",
                    row_count=int(trial_row.get("row_count", 0)),
                    fair_value_abs_sum=float(trial_row.get("fair_value_abs_sum", 0)),
                    trial_row=trial_row,
                )
            )
            continue
        if trial_row is None and production_row is not None:
            if _holding_looks_non_private(production_row):
                delta_type = "removed_non_private"
            elif _holding_looks_aggregate(production_row):
                delta_type = "removed_aggregate"
            else:
                delta_type = "removed_position_leaf"
            records.append(
                _row_delta_record(
                    cik=cik_norm,
                    delta_type=delta_type,
                    row_count=int(production_row.get("row_count", 0)),
                    fair_value_abs_sum=float(production_row.get("fair_value_abs_sum", 0)),
                    production_row=production_row,
                )
            )
            continue
        if trial_row is None or production_row is None:
            continue
        if int(trial_row.get("row_count", 0)) > 1 or int(production_row.get("row_count", 0)) > 1:
            records.append(
                _row_delta_record(
                    cik=cik_norm,
                    delta_type="unknown",
                    row_count=max(
                        int(production_row.get("row_count", 0)),
                        int(trial_row.get("row_count", 0)),
                    ),
                    fair_value_abs_sum=max(
                        float(production_row.get("fair_value_abs_sum", 0)),
                        float(trial_row.get("fair_value_abs_sum", 0)),
                    ),
                    production_row=production_row,
                    trial_row=trial_row,
                )
            )
            continue

        classification_changes = [
            col for col in _ROW_DELTA_CLASSIFICATION_COLUMNS
            if _normalize_delta_text(production_row.get(col, "")) != _normalize_delta_text(trial_row.get(col, ""))
        ]
        if classification_changes:
            records.append(
                _row_delta_record(
                    cik=cik_norm,
                    delta_type="changed_index_classification",
                    row_count=1,
                    fair_value_abs_sum=max(
                        float(production_row.get("fair_value_abs_sum", 0)),
                        float(trial_row.get("fair_value_abs_sum", 0)),
                    ),
                    production_row=production_row,
                    trial_row=trial_row,
                    changed_columns="|".join(classification_changes),
                    production_value=_value_summary(production_row, classification_changes),
                    trial_value=_value_summary(trial_row, classification_changes),
                )
            )
        for text_col, delta_type in [
            ("issuer_name", "changed_issuer_name"),
            ("instrument_description", "changed_instrument_description"),
            ("position_key", "changed_position_key"),
        ]:
            if _normalize_delta_text(production_row.get(text_col, "")) != _normalize_delta_text(trial_row.get(text_col, "")):
                records.append(
                    _row_delta_record(
                        cik=cik_norm,
                        delta_type=delta_type,
                        row_count=1,
                        fair_value_abs_sum=max(
                            float(production_row.get("fair_value_abs_sum", 0)),
                            float(trial_row.get("fair_value_abs_sum", 0)),
                        ),
                        production_row=production_row,
                        trial_row=trial_row,
                        changed_columns=text_col,
                        production_value=str(production_row.get(text_col, "") or ""),
                        trial_value=str(trial_row.get(text_col, "") or ""),
                    )
                )
        numeric_changes = [
            col for col in _ROW_DELTA_NUMERIC_COLUMNS
            if _numeric_delta_changed(
                col,
                production_row.get(f"{col}_sum", ""),
                trial_row.get(f"{col}_sum", ""),
            )
        ]
        if numeric_changes:
            records.append(
                _row_delta_record(
                    cik=cik_norm,
                    delta_type="changed_numeric_value",
                    row_count=1,
                    fair_value_abs_sum=max(
                        float(production_row.get("fair_value_abs_sum", 0)),
                        float(trial_row.get("fair_value_abs_sum", 0)),
                    ),
                    production_row=production_row,
                    trial_row=trial_row,
                    changed_columns="|".join(numeric_changes),
                    production_value=_value_summary(production_row, numeric_changes),
                    trial_value=_value_summary(trial_row, numeric_changes),
                )
            )

    if not records:
        return pd.DataFrame(columns=ROW_DELTA_ATTRIBUTION_COLUMNS)
    result = pd.DataFrame(records, columns=ROW_DELTA_ATTRIBUTION_COLUMNS)
    return result.sort_values(
        ["report_date", "delta_type", "sample_identifier"],
        kind="stable",
    ).reset_index(drop=True)


def _cluster_label_for_row(row: pd.Series) -> tuple[str, str]:
    for col in ["issuer_name", "instrument_description", "bdc_investment_identifier", "investment_identifier"]:
        value = str(row.get(col, "") or "").strip()
        if value:
            return value, normalize_wrapper_identifier(value)
    return "", ""


def _family_guess_from_text(text: str) -> str:
    if _HIGH_FV_CLO_PATTERN.search(text):
        return "clo"
    if _HIGH_FV_WARRANT_PATTERN.search(text):
        return "warrant"
    if _HIGH_FV_FUND_PATTERN.search(text):
        return "fund"
    if _HIGH_FV_DEBT_PATTERN.search(text):
        return "debt"
    if _HIGH_FV_EQUITY_PATTERN.search(text):
        return "equity"
    return "unknown"


def _high_fv_output_field(group: pd.DataFrame, column: str) -> str:
    if column not in group.columns:
        return ""
    values = group[column].fillna("").astype(str).str.strip()
    values = values[values.ne("")]
    if values.empty:
        return ""
    counts = values.value_counts()
    return str(counts.index[0])


def _build_high_fv_unclassified_clusters(
    holdings_df: pd.DataFrame,
    wrapper: WrapperDefinition | None,
    *,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    """Build cluster packets for high-FV unclassified wrapper output rows."""
    if wrapper is None or wrapper.unclassified_rate is None:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)
    if holdings_df is None or holdings_df.empty:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)

    cik_norm = normalize_cik(cik)
    h = holdings_df.copy()
    if "cik" in h.columns:
        h["cik"] = h["cik"].map(normalize_cik)
        h = h[h["cik"].eq(cik_norm)].copy()
    else:
        h["cik"] = cik_norm
    if "source" in h.columns:
        source = h["source"].fillna("").astype(str).str.lower()
        h = h[source.eq("bdc") | source.eq("")].copy()
    if h.empty:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)

    for col in [
        "entity_name",
        "report_date",
        "bdc_investment_identifier",
        "investment_identifier",
        "issuer_name",
        "instrument_description",
        "index_classification",
        "asset_category",
        "exposure_type",
    ]:
        if col not in h.columns:
            h[col] = ""
    h["_row_index"] = h.index
    classified = classify_content_signature_rows(wrapper, h)
    if classified.empty:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)
    classified = classified.rename(columns={"fair_value": "_signature_fair_value_abs"})
    h = h.merge(
        classified[["row_index", "archetype", "_signature_fair_value_abs"]],
        left_on="_row_index",
        right_on="row_index",
        how="left",
    )
    h["_signature_fair_value_abs"] = pd.to_numeric(
        h["_signature_fair_value_abs"],
        errors="coerce",
    ).fillna(0)
    h["archetype"] = h["archetype"].fillna("").astype(str)

    quarter_fv = h.groupby("report_date", dropna=False)["_signature_fair_value_abs"].sum()
    unclassified = h[h["archetype"].eq("")].copy()
    if unclassified.empty:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)
    unclassified_fv = unclassified.groupby("report_date", dropna=False)["_signature_fair_value_abs"].sum()
    affected_reports = {
        str(report_date)
        for report_date, fv in unclassified_fv.items()
        if float(quarter_fv.get(report_date, 0) or 0) > 0
        and (float(fv) / float(quarter_fv.get(report_date, 0))) > wrapper.unclassified_rate.max_fv_pct
    }
    if not affected_reports:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)
    unclassified = unclassified[unclassified["report_date"].astype(str).isin(affected_reports)].copy()
    if unclassified.empty:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)

    labels = unclassified.apply(_cluster_label_for_row, axis=1, result_type="expand")
    unclassified["_cluster_label"] = labels[0]
    unclassified["_cluster_key"] = labels[1]
    unclassified = unclassified[unclassified["_cluster_key"].astype(str).ne("")].copy()
    if unclassified.empty:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)

    total_affected_fv = float(
        quarter_fv[[idx for idx in quarter_fv.index if str(idx) in affected_reports]].sum()
    )
    rows: list[dict[str, Any]] = []
    for _, group in unclassified.groupby("_cluster_key", dropna=False):
        report_dates = sorted(str(value) for value in group["report_date"].dropna().astype(str).unique())
        cluster_fv = float(group["_signature_fair_value_abs"].sum())
        quarter_shares: list[float] = []
        for report_date, q_group in group.groupby("report_date", dropna=False):
            denominator = float(quarter_fv.get(report_date, 0) or 0)
            if denominator > 0:
                quarter_shares.append(float(q_group["_signature_fair_value_abs"].sum()) / denominator)
        text_blob = " ".join(
            _join_unique_values(group[col]) for col in [
                "_cluster_label",
                "bdc_investment_identifier",
                "instrument_description",
                "issuer_name",
            ]
        )
        source_family_guess = _family_guess_from_text(text_blob)
        rows.append({
            "cik": cik_norm,
            "entity_name": _join_unique_values(group["entity_name"]),
            "cluster_label": _join_unique_values(group["_cluster_label"]),
            "affected_report_dates": "|".join(report_dates),
            "quarter_count": len(report_dates),
            "row_count": int(len(group)),
            "fair_value_abs_sum": round(cluster_fv, 2),
            "fair_value_share": round(cluster_fv / total_affected_fv, 6) if total_affected_fv > 0 else 0,
            "max_quarter_fair_value_share": round(max(quarter_shares), 6) if quarter_shares else 0,
            "source_family_guess": source_family_guess,
            "suggested_wrapper_family": source_family_guess,
            "output_index_classification": _high_fv_output_field(group, "index_classification"),
            "output_asset_category": _high_fv_output_field(group, "asset_category"),
            "output_exposure_type": _high_fv_output_field(group, "exposure_type"),
            "sample_identifiers": _join_unique_values(group["bdc_investment_identifier"]),
            "sample_issuer_names": _join_unique_values(group["issuer_name"]),
            "sample_instrument_descriptions": _join_unique_values(group["instrument_description"]),
            "suggested_review_question": (
                "Should this repeated high-FV unclassified label be covered by a "
                "CIK-local wrapper family or archetype?"
            ),
            "owner": "wrapper",
            "review_status": "review",
        })

    if not rows:
        return pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)
    return pd.DataFrame(rows, columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS).sort_values(
        ["fair_value_abs_sum", "row_count", "cluster_label"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)


def _detail_row_is_remaining_blocker(row: pd.Series) -> bool:
    status = str(row.get("status", "") or "").lower()
    calibrated = str(row.get("calibrated_status", "") or "").lower()
    residual = str(row.get("residual_class", "") or "").lower()
    blocking_issue = row.get("blocking_issue", False)
    if isinstance(blocking_issue, str):
        blocking = blocking_issue.strip().lower() in {"true", "1", "yes"}
    else:
        blocking = bool(blocking_issue)
    return (
        blocking
        or "blocking" in calibrated
        or status in {"missing_from_pipeline", "source_only"}
        or residual.startswith("blocking")
    )


def _source_identifier_is_verbose(raw_identifier: str) -> bool:
    token_count = len(_SOURCE_CORRUPTED_FIELD_TOKEN_PATTERN.findall(raw_identifier))
    hierarchy_pct = bool(_SOURCE_CORRUPTED_HIERARCHY_PCT_PATTERN.search(raw_identifier))
    very_long_with_fields = len(raw_identifier) >= 180 and token_count >= 1
    return token_count >= 2 or hierarchy_pct or very_long_with_fields


def _output_has_field_label_residue(row: pd.Series) -> bool:
    output_blob = " ".join(
        str(row.get(col, "") or "")
        for col in [
            "issuer_name",
            "instrument_description",
            "output_wrapper_position_key",
            "bdc_investment_identifier",
        ]
    )
    if not output_blob.strip():
        return False
    return bool(
        _PARSED_FIELD_LABEL_PATTERN.search(output_blob)
        or _PARSED_SOURCE_SECTION_PATTERN.search(output_blob)
    )


def _build_source_verbose_identifier_packets(
    detail_df: pd.DataFrame,
    holdings_df: pd.DataFrame | None,
    *,
    parsed_field_quality: pd.DataFrame | None = None,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    """Flag verbose source identifiers only when they coincide with output risk.

    Verbose raw source identifiers are common in some filings and are not enough
    to prove wrapper failure. This packet fires when verbose source text appears
    with output contamination or an unresolved blocker.
    """
    detail = _ensure_detail_columns(detail_df)
    if detail.empty:
        return pd.DataFrame(columns=AGENT_ISSUE_PACKET_COLUMNS)
    cik_norm = normalize_cik(cik)
    detail = detail[detail["cik"].map(normalize_cik).eq(cik_norm)].copy()
    if detail.empty:
        return pd.DataFrame(columns=AGENT_ISSUE_PACKET_COLUMNS)
    quarter_totals = _quarter_totals(holdings_df, cik=cik_norm)
    parsed_source_ids: set[str] = set()
    parsed_output_ids: set[str] = set()
    if parsed_field_quality is not None and not parsed_field_quality.empty:
        parsed_source_ids = set(parsed_field_quality.get("source_row_id", pd.Series(dtype=str)).fillna("").astype(str))
        parsed_output_ids = set(parsed_field_quality.get("output_row_id", pd.Series(dtype=str)).fillna("").astype(str))
    records: list[dict[str, Any]] = []
    for idx, row in detail.iterrows():
        raw_identifier = str(row.get("raw_investment_identifier", "") or "")
        if not raw_identifier.strip():
            continue
        if not _source_identifier_is_verbose(raw_identifier):
            continue
        source_row_id = str(row.get("source_row_id", "") or "")
        output_row_id = str(row.get("output_row_id", "") or "")
        parsed_hit = source_row_id in parsed_source_ids or output_row_id in parsed_output_ids
        output_residue = _output_has_field_label_residue(row) or parsed_hit
        remaining_blocker = _detail_row_is_remaining_blocker(row)
        if not output_residue and not remaining_blocker:
            continue
        report_date = str(row.get("report_date", "") or "")
        total_fv, total_rows = _totals_for_report(
            quarter_totals,
            cik=cik_norm,
            report_date=report_date,
        )
        materiality = _materiality_metrics(
            affected_fair_value=row.get("source_fair_value", 0),
            total_fair_value=total_fv,
            affected_rows=1,
            total_rows=total_rows,
        )
        owner = "wrapper" if output_residue else "source_data"
        evidence = (
            "verbose source identifier coincides with output field-label residue"
            if output_residue
            else "verbose source identifier coincides with unresolved source blocker"
        )
        records.append({
            "issue_id": _packet_issue_id(
                cik=cik_norm,
                report_date=report_date,
                rule_id="WRAP.SOURCE_VERBOSE_IDENTIFIER",
                unique=row.get("source_row_id", idx),
            ),
            "rule_id": "WRAP.SOURCE_VERBOSE_IDENTIFIER",
            "source_rule_id": "WRAP.SOURCE_CORRUPTED_IDENTIFIER",
            "packet_type": "row",
            "severity": "review" if materiality["materiality_tier"] in {"P0", "P1"} else "warn",
            "materiality_tier": materiality["materiality_tier"],
            "likely_owner": owner,
            "review_status": "review",
            "cik": cik_norm,
            "entity_name": str(row.get("entity_name", "") or ""),
            "report_date": report_date,
            "accession_number": str(row.get("accession_number", "") or ""),
            "source_row_id": source_row_id,
            "output_row_id": output_row_id,
            "production_column": "bdc_investment_identifier",
            "source_value": raw_identifier,
            "output_value": str(row.get("issuer_name", "") or ""),
            **materiality,
            "evidence": evidence,
            "recommended_action": (
                "Review row against source filing; if output is contaminated, add a scoped "
                "wrapper parse rule, otherwise record the verbose source identifier as a false positive."
            ),
        })
    if not records:
        return pd.DataFrame(columns=AGENT_ISSUE_PACKET_COLUMNS)
    return pd.DataFrame(records, columns=AGENT_ISSUE_PACKET_COLUMNS)


def _build_source_corrupted_identifier_packets(
    detail_df: pd.DataFrame,
    holdings_df: pd.DataFrame | None,
    *,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    """Compatibility alias for the renamed source-verbose identifier packet."""
    return _build_source_verbose_identifier_packets(
        detail_df,
        holdings_df,
        parsed_field_quality=None,
        cik=cik,
    )


def _bucket_distribution(series: pd.Series) -> dict[str, float]:
    values = series.fillna("").astype(str)
    total = len(values)
    if total == 0:
        return {}
    counts = values.value_counts(dropna=False)
    return {str(bucket): float(count) / total for bucket, count in counts.items()}


def _format_distribution(dist: dict[str, float]) -> str:
    return "|".join(f"{bucket}:{share:.6f}" for bucket, share in sorted(dist.items()))


def _js_divergence(current: dict[str, float], baseline: dict[str, float]) -> float:
    if not current or not baseline:
        return 0.0
    keys = sorted(set(current) | set(baseline))
    midpoint = {key: (current.get(key, 0.0) + baseline.get(key, 0.0)) / 2.0 for key in keys}

    def kl(left: dict[str, float], right: dict[str, float]) -> float:
        out = 0.0
        for key in keys:
            p = left.get(key, 0.0)
            q = right.get(key, 0.0)
            if p > 0 and q > 0:
                out += p * math.log2(p / q)
        return out

    return round(0.5 * kl(current, midpoint) + 0.5 * kl(baseline, midpoint), 6)


def _dominant_bucket(dist: dict[str, float]) -> str:
    if not dist:
        return ""
    return sorted(dist.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _rate_bucket(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none"}:
        return "blank"
    lower = text.lower()
    number = pd.to_numeric(pd.Series([text.replace("%", "")]), errors="coerce").iloc[0]
    if pd.notna(number):
        numeric = float(number)
        if numeric == 0:
            return "zero"
        return "percent_string" if "%" in text else "numeric_pct"
    if any(token in lower for token in ["sofr", "libor", "prime", "cash", "pik"]):
        return "rate_text"
    return "other_text"


def _date_bucket(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none"}:
        return "blank"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return "yyyy-mm-dd"
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", text):
        return "slash_date"
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", text, re.IGNORECASE):
        return "text_date"
    return "other_text"


def _classification_bucket(value: Any) -> str:
    text = str(value or "").strip()
    return text.upper() if text else "blank"


def _text_shape_bucket(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none"}:
        return "blank"
    lower = text.lower()
    if _PARSED_FIELD_LABEL_PATTERN.search(text):
        return "field_label_text"
    if _PARSED_SOURCE_SECTION_PATTERN.search(text) and _PARSED_FIELD_PCT_PATTERN.search(text):
        return "hierarchy_pct_text"
    if re.fullmatch(r"[A-Z0-9\-./ ]+", text) and any(ch.isdigit() for ch in text):
        return "identifier_like"
    if len(text) >= 180:
        return "long_text"
    if any(token in lower for token in ["sofr", "libor", "prime", "pik"]):
        return "rate_embedded_text"
    token_count = len(_PARSED_POSITION_TOKEN_PATTERN.findall(lower))
    if token_count <= 2:
        return "short_text"
    if token_count <= 8:
        return "normal_text"
    return "verbose_text"


def _column_drift_bucket(column: str, value: Any) -> str:
    if column in {"interest_rate", "basis_spread", "pik_rate"}:
        return _rate_bucket(value)
    if column == "maturity_date":
        return _date_bucket(value)
    if column in _DRIFT_TEXT_COLUMNS:
        return _text_shape_bucket(value)
    return _classification_bucket(value)


def _drift_thresholds_for_column(column: str) -> tuple[float, float]:
    if column in _DRIFT_TEXT_COLUMNS:
        return _DRIFT_TEXT_JS_THRESHOLD, _DRIFT_TEXT_NEW_BUCKET_SHARE_THRESHOLD
    return _DRIFT_JS_THRESHOLD, _DRIFT_NEW_BUCKET_SHARE_THRESHOLD


def _build_column_drift_packets(
    holdings_df: pd.DataFrame,
    *,
    cik: str = TRINITY_CIK,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build CIK-column distribution drift summary and representative examples."""
    if holdings_df is None or holdings_df.empty:
        return (
            pd.DataFrame(columns=COLUMN_DRIFT_SUMMARY_COLUMNS),
            pd.DataFrame(columns=COLUMN_DRIFT_EXAMPLE_COLUMNS),
        )
    cik_norm = normalize_cik(cik)
    df = holdings_df.copy()
    if "cik" in df.columns:
        df["cik"] = df["cik"].map(normalize_cik)
        df = df[df["cik"].eq(cik_norm)].copy()
    else:
        df["cik"] = cik_norm
    if "source" in df.columns:
        source = df["source"].fillna("").astype(str).str.lower()
        df = df[source.eq("bdc") | source.eq("")].copy()
    if df.empty or "report_date" not in df.columns:
        return (
            pd.DataFrame(columns=COLUMN_DRIFT_SUMMARY_COLUMNS),
            pd.DataFrame(columns=COLUMN_DRIFT_EXAMPLE_COLUMNS),
        )
    for col in [
        "entity_name",
        "bdc_investment_identifier",
        "issuer_name",
        "instrument_description",
        "fair_value",
        *_DRIFT_COLUMNS,
    ]:
        if col not in df.columns:
            df[col] = ""
    df["_fv_abs"] = pd.to_numeric(df["fair_value"], errors="coerce").abs().fillna(0)
    quarters = sorted(str(q) for q in df["report_date"].dropna().astype(str).unique())
    summary_rows: list[dict[str, Any]] = []
    example_rows: list[dict[str, Any]] = []

    for column in _DRIFT_COLUMNS:
        df[f"_{column}_bucket"] = df[column].map(lambda value: _column_drift_bucket(column, value))
        for idx, report_date in enumerate(quarters):
            current = df[df["report_date"].astype(str).eq(report_date)].copy()
            previous_quarters = quarters[max(0, idx - _DRIFT_BASELINE_QUARTERS):idx]
            baseline_quarter_count = len(previous_quarters)
            bucket_col = f"_{column}_bucket"
            current_dist = _bucket_distribution(current[bucket_col])
            baseline_dist: dict[str, float] = {}
            js = 0.0
            new_bucket_share = 0.0
            status = "info"
            severity = "info"
            if baseline_quarter_count >= _DRIFT_MIN_BASELINE_QUARTERS:
                baseline = df[df["report_date"].astype(str).isin(previous_quarters)].copy()
                baseline_dist = _bucket_distribution(baseline[bucket_col])
                js = _js_divergence(current_dist, baseline_dist)
                new_bucket_share = round(
                    sum(share for bucket, share in current_dist.items() if bucket not in baseline_dist),
                    6,
                )
                js_threshold, new_bucket_threshold = _drift_thresholds_for_column(column)
                if js >= js_threshold or new_bucket_share >= new_bucket_threshold:
                    status = "review"
                    severity = "review"
                else:
                    status = "pass"
                    severity = "info"
            else:
                status = "insufficient_baseline"
                severity = "info"

            materiality = _materiality_metrics(
                affected_fair_value=current["_fv_abs"].sum(),
                total_fair_value=current["_fv_abs"].sum(),
                affected_rows=len(current),
                total_rows=len(current),
            )
            summary_rows.append({
                "cik": cik_norm,
                "entity_name": _join_unique_values(current["entity_name"]),
                "report_date": report_date,
                "column": column,
                "baseline_quarter_count": baseline_quarter_count,
                "row_count": int(len(current)),
                "fair_value_abs_sum": round(float(current["_fv_abs"].sum()), 2),
                "js_divergence": js,
                "new_bucket_share": new_bucket_share,
                "current_dominant_bucket": _dominant_bucket(current_dist),
                "baseline_dominant_bucket": _dominant_bucket(baseline_dist),
                "status": status,
                "severity": severity,
                "materiality_tier": materiality["materiality_tier"] if status == "review" else "P2",
                "bucket_distribution": _format_distribution(current_dist),
                "baseline_bucket_distribution": _format_distribution(baseline_dist),
            })

            if status == "review":
                example = current.sort_values("_fv_abs", ascending=False, kind="stable").head(5)
                for _, ex in example.iterrows():
                    example_rows.append({
                        "cik": cik_norm,
                        "entity_name": str(ex.get("entity_name", "") or ""),
                        "report_date": report_date,
                        "column": column,
                        "bucket": str(ex.get(bucket_col, "") or ""),
                        "bdc_investment_identifier": str(ex.get("bdc_investment_identifier", "") or ""),
                        "issuer_name": str(ex.get("issuer_name", "") or ""),
                        "instrument_description": str(ex.get("instrument_description", "") or ""),
                        "output_value": str(ex.get(column, "") or ""),
                        "fair_value": _safe_float(ex.get("fair_value", 0)),
                    })

    return (
        pd.DataFrame(summary_rows, columns=COLUMN_DRIFT_SUMMARY_COLUMNS),
        pd.DataFrame(example_rows, columns=COLUMN_DRIFT_EXAMPLE_COLUMNS),
    )


def _build_agent_issue_packets(
    *,
    parsed_field_quality: pd.DataFrame,
    source_corrupted_identifiers: pd.DataFrame | None = None,
    source_verbose_identifiers: pd.DataFrame | None = None,
    cost_fv_outliers: pd.DataFrame | None = None,
    column_validation_issues: pd.DataFrame | None = None,
    holdings_df: pd.DataFrame | None = None,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    cik_norm = normalize_cik(cik)
    quarter_totals = _quarter_totals(holdings_df, cik=cik_norm)

    if parsed_field_quality is not None and not parsed_field_quality.empty:
        for idx, row in parsed_field_quality.iterrows():
            report_date = str(row.get("report_date", "") or "")
            total_fv, total_rows = _totals_for_report(
                quarter_totals,
                cik=cik_norm,
                report_date=report_date,
            )
            materiality = _materiality_metrics(
                affected_fair_value=row.get("fair_value", 0),
                total_fair_value=total_fv,
                affected_rows=1,
                total_rows=total_rows,
            )
            owner = str(row.get("suggested_owner", "wrapper") or "wrapper")
            if owner not in _AGENT_VERDICT_ALLOWED_OWNERS:
                owner = "wrapper"
            records.append({
                "issue_id": _packet_issue_id(
                    cik=cik_norm,
                    report_date=report_date,
                    rule_id="WRAP.PARSED_FIELD_CONTAMINATION",
                    unique=f"{row.get('source_row_id', '')}-{row.get('column', '')}-{idx}",
                ),
                "rule_id": "WRAP.PARSED_FIELD_CONTAMINATION",
                "source_rule_id": "",
                "packet_type": "row",
                "severity": str(row.get("severity", "warn") or "warn"),
                "materiality_tier": materiality["materiality_tier"],
                "likely_owner": owner,
                "review_status": "review",
                "cik": cik_norm,
                "entity_name": str(row.get("entity_name", "") or ""),
                "report_date": report_date,
                "accession_number": str(row.get("accession_number", "") or ""),
                "source_row_id": str(row.get("source_row_id", "") or ""),
                "output_row_id": str(row.get("output_row_id", "") or ""),
                "production_column": str(row.get("column", "") or ""),
                "source_value": str(row.get("bdc_investment_identifier", "") or ""),
                "output_value": str(row.get("output_value", "") or ""),
                **materiality,
                "evidence": str(row.get("evidence_token", "") or ""),
                "recommended_action": str(row.get("recommended_action", "") or ""),
            })

    source_packets = source_verbose_identifiers
    if source_packets is None:
        source_packets = source_corrupted_identifiers
    if source_packets is not None and not source_packets.empty:
        records.extend(source_packets.to_dict(orient="records"))

    if cost_fv_outliers is not None and not cost_fv_outliers.empty:
        records.extend(cost_fv_outliers.to_dict(orient="records"))

    if column_validation_issues is not None and not column_validation_issues.empty:
        holdings_lookup = (
            holdings_df.reset_index(drop=True)
            if holdings_df is not None and not holdings_df.empty
            else pd.DataFrame()
        )
        for idx, row in column_validation_issues.iterrows():
            report_date = str(row.get("report_date", "") or "")
            total_fv, total_rows = _totals_for_report(
                quarter_totals,
                cik=cik_norm,
                report_date=report_date,
            )
            lookup_row = pd.Series(dtype=object)
            row_key = pd.to_numeric(pd.Series([row.get("row_key")]), errors="coerce").iloc[0]
            if pd.notna(row_key) and not holdings_lookup.empty:
                row_pos = int(row_key)
                if 0 <= row_pos < len(holdings_lookup):
                    lookup_row = holdings_lookup.iloc[row_pos]
            affected_fv = lookup_row.get("fair_value", 0) if not lookup_row.empty else 0
            materiality = _materiality_metrics(
                affected_fair_value=affected_fv,
                total_fair_value=total_fv,
                affected_rows=1,
                total_rows=total_rows,
            )
            rule_id = str(row.get("rule_id", "") or "")
            column = str(row.get("column", "") or "")
            owner = "validation_rule"
            if column in {
                "issuer_name",
                "instrument_description",
                "bdc_investment_identifier",
                "interest_rate",
                "basis_spread",
                "pik_rate",
                "maturity_date",
                "cost",
                "fair_value",
            }:
                owner = "wrapper"
            elif column in {"index_classification", "asset_category", "asset_class", "exposure_type"}:
                owner = "classification"
            severity = str(row.get("severity", "WARN") or "WARN").lower()
            records.append({
                "issue_id": _packet_issue_id(
                    cik=cik_norm,
                    report_date=report_date,
                    rule_id="WRAP.PRODUCTION_COLUMN_VALIDATION",
                    unique=f"{rule_id}-{row.get('row_key', '')}-{idx}",
                ),
                "rule_id": "WRAP.PRODUCTION_COLUMN_VALIDATION",
                "source_rule_id": rule_id,
                "packet_type": "row",
                "severity": "review" if severity == "fail" else "warn",
                "materiality_tier": materiality["materiality_tier"],
                "likely_owner": owner,
                "review_status": "review",
                "cik": cik_norm,
                "entity_name": str(lookup_row.get("entity_name", "") or ""),
                "report_date": report_date,
                "accession_number": str(lookup_row.get("accession_number", "") or ""),
                "source_row_id": "",
                "output_row_id": str(row.get("row_key", "") or ""),
                "production_column": column,
                "source_value": str(lookup_row.get("bdc_investment_identifier", "") or ""),
                "output_value": str(row.get("value", "") or ""),
                **materiality,
                "evidence": str(row.get("message", "") or row.get("evidence", "") or ""),
                "recommended_action": (
                    "Review the production validation issue against source evidence; if true, "
                    "repair the wrapper or upstream deterministic rule that produced the value."
                ),
            })

    if not records:
        return pd.DataFrame(columns=AGENT_ISSUE_PACKET_COLUMNS)
    return pd.DataFrame(records, columns=AGENT_ISSUE_PACKET_COLUMNS).drop_duplicates(
        "issue_id"
    ).reset_index(drop=True)


def _build_agent_cluster_packets(
    *,
    row_delta_attribution: pd.DataFrame,
    high_fv_unclassified_clusters: pd.DataFrame,
    column_drift_summary: pd.DataFrame,
    oracle_summary: pd.DataFrame | None = None,
    holdings_df: pd.DataFrame | None = None,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    cik_norm = normalize_cik(cik)
    quarter_totals = _quarter_totals(holdings_df, cik=cik_norm)

    if oracle_summary is not None and not oracle_summary.empty:
        no_rows = oracle_summary[
            oracle_summary.get("oracle_fail_reasons", pd.Series(dtype=str))
            .fillna("")
            .astype(str)
            .str.contains("no_wrapper_rows", regex=False)
        ]
        for idx, row in no_rows.iterrows():
            report_date = str(row.get("report_date", "") or "")
            total_fv, total_rows = _totals_for_report(
                quarter_totals,
                cik=cik_norm,
                report_date=report_date,
            )
            materiality = _materiality_metrics(
                affected_fair_value=total_fv,
                total_fair_value=total_fv,
                affected_rows=total_rows,
                total_rows=total_rows,
            )
            records.append({
                "issue_id": _packet_issue_id(
                    cik=cik_norm,
                    report_date=report_date,
                    rule_id="WRAP.NO_WRAPPER_ROWS",
                    unique=idx,
                ),
                "rule_id": "WRAP.NO_WRAPPER_ROWS",
                "source_rule_id": "no_wrapper_rows",
                "packet_type": "cluster",
                "severity": "review",
                "materiality_tier": materiality["materiality_tier"],
                "likely_owner": "wrapper",
                "review_status": "review",
                "cik": cik_norm,
                "entity_name": str(row.get("entity_name", "") or ""),
                "report_date": report_date,
                "affected_report_dates": report_date,
                "cluster_key": "no_wrapper_rows",
                "cluster_label": "wrapper definition produced no wrapper rows",
                "production_column": "wrapper_disposition",
                **materiality,
                "evidence": "wrapper definition exists but no source or output rows received wrapper dispositions",
                "representative_rows_path": "oracle_summary.csv",
                "recommended_action": (
                    "Review wrapper support detection and staging output before treating this CIK as unsupported."
                ),
            })

    if row_delta_attribution is not None and not row_delta_attribution.empty:
        for idx, row in row_delta_attribution.iterrows():
            if str(row.get("review_status", "") or "") == "info":
                continue
            report_date = str(row.get("report_date", "") or "")
            total_fv, total_rows = _totals_for_report(
                quarter_totals,
                cik=cik_norm,
                report_date=report_date,
            )
            materiality = _materiality_metrics(
                affected_fair_value=row.get("fair_value_abs_sum", 0),
                total_fair_value=total_fv,
                affected_rows=row.get("row_count", 0),
                total_rows=total_rows,
            )
            delta_type = str(row.get("delta_type", "") or "")
            records.append({
                "issue_id": _packet_issue_id(
                    cik=cik_norm,
                    report_date=report_date,
                    rule_id="WRAP.ROW_DELTA_ATTRIBUTION",
                    unique=f"{delta_type}-{row.get('sample_identifier', '')}-{idx}",
                ),
                "rule_id": "WRAP.ROW_DELTA_ATTRIBUTION",
                "source_rule_id": "",
                "packet_type": "cluster",
                "severity": "review" if materiality["materiality_tier"] in {"P0", "P1"} else "warn",
                "materiality_tier": materiality["materiality_tier"],
                "likely_owner": str(row.get("owner", "wrapper") or "wrapper"),
                "review_status": "review",
                "cik": cik_norm,
                "entity_name": str(row.get("entity_name", "") or ""),
                "report_date": report_date,
                "affected_report_dates": report_date,
                "cluster_key": f"{delta_type}:{normalize_wrapper_identifier(row.get('sample_identifier', ''))}",
                "cluster_label": str(row.get("sample_identifier", "") or row.get("sample_position_key", "") or delta_type),
                "production_column": str(row.get("changed_columns", "") or ""),
                **materiality,
                "evidence": str(row.get("likely_mechanism", "") or ""),
                "representative_rows_path": "row_delta_attribution.csv",
                "recommended_action": "Review trial-vs-production delta before promotion.",
            })

    if high_fv_unclassified_clusters is not None and not high_fv_unclassified_clusters.empty:
        for idx, row in high_fv_unclassified_clusters.iterrows():
            report_dates = str(row.get("affected_report_dates", "") or "")
            report_date = report_dates.split("|")[0] if report_dates else ""
            total_fv = 0.0
            total_rows = 0
            for rd in report_dates.split("|"):
                q_fv, q_rows = _totals_for_report(quarter_totals, cik=cik_norm, report_date=rd)
                total_fv += q_fv
                total_rows += q_rows
            materiality = _materiality_metrics(
                affected_fair_value=row.get("fair_value_abs_sum", 0),
                total_fair_value=total_fv,
                affected_rows=row.get("row_count", 0),
                total_rows=total_rows,
                quarter_count=_safe_int(row.get("quarter_count", 1)),
            )
            records.append({
                "issue_id": _packet_issue_id(
                    cik=cik_norm,
                    report_date=report_date,
                    rule_id="WRAP.HIGH_FV_UNCLASSIFIED_CLUSTER",
                    unique=row.get("cluster_label", idx),
                ),
                "rule_id": "WRAP.HIGH_FV_UNCLASSIFIED_CLUSTER",
                "source_rule_id": "",
                "packet_type": "cluster",
                "severity": "review",
                "materiality_tier": materiality["materiality_tier"],
                "likely_owner": "wrapper",
                "review_status": "review",
                "cik": cik_norm,
                "entity_name": str(row.get("entity_name", "") or ""),
                "report_date": report_date,
                "affected_report_dates": report_dates,
                "cluster_key": normalize_wrapper_identifier(row.get("cluster_label", "")),
                "cluster_label": str(row.get("cluster_label", "") or ""),
                "production_column": "index_classification",
                **materiality,
                "evidence": (
                    f"source_family_guess={row.get('source_family_guess', '')}; "
                    f"output_asset_category={row.get('output_asset_category', '')}"
                ),
                "representative_rows_path": "high_fv_unclassified_clusters.csv",
                "recommended_action": str(row.get("suggested_review_question", "") or ""),
            })

    if column_drift_summary is not None and not column_drift_summary.empty:
        drift = column_drift_summary[column_drift_summary["status"].astype(str).eq("review")]
        for idx, row in drift.iterrows():
            report_date = str(row.get("report_date", "") or "")
            total_fv, total_rows = _totals_for_report(
                quarter_totals,
                cik=cik_norm,
                report_date=report_date,
            )
            materiality = _materiality_metrics(
                affected_fair_value=row.get("fair_value_abs_sum", 0),
                total_fair_value=total_fv,
                affected_rows=row.get("row_count", 0),
                total_rows=total_rows,
            )
            column = str(row.get("column", "") or "")
            records.append({
                "issue_id": _packet_issue_id(
                    cik=cik_norm,
                    report_date=report_date,
                    rule_id="WRAP.COLUMN_DISTRIBUTION_DRIFT",
                    unique=f"{column}-{idx}",
                ),
                "rule_id": "WRAP.COLUMN_DISTRIBUTION_DRIFT",
                "source_rule_id": "",
                "packet_type": "cluster",
                "severity": str(row.get("severity", "review") or "review"),
                "materiality_tier": materiality["materiality_tier"],
                "likely_owner": "wrapper",
                "review_status": "review",
                "cik": cik_norm,
                "entity_name": str(row.get("entity_name", "") or ""),
                "report_date": report_date,
                "affected_report_dates": report_date,
                "cluster_key": f"{column}:{row.get('current_dominant_bucket', '')}",
                "cluster_label": f"{column} distribution drift",
                "production_column": column,
                **materiality,
                "evidence": (
                    f"js_divergence={row.get('js_divergence', '')}; "
                    f"new_bucket_share={row.get('new_bucket_share', '')}; "
                    f"current={row.get('bucket_distribution', '')}; "
                    f"baseline={row.get('baseline_bucket_distribution', '')}"
                ),
                "representative_rows_path": "column_drift_examples.csv",
                "recommended_action": (
                    "Review whether this is a real filing format change, normalized-safe "
                    "source drift, or wrapper-owned output drift."
                ),
            })

    if not records:
        return pd.DataFrame(columns=AGENT_CLUSTER_PACKET_COLUMNS)
    return pd.DataFrame(records, columns=AGENT_CLUSTER_PACKET_COLUMNS).drop_duplicates(
        "issue_id"
    ).reset_index(drop=True)


def _load_agent_verdict_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json_mod.loads(text)
            except json_mod.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on verdict line {line_no}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Verdict line {line_no} is not a JSON object")
            records.append(record)
    return records


def validate_agent_verdict_records(records: list[dict[str, Any]]) -> list[str]:
    """Validate wrapper oracle agent verdict JSONL records."""
    errors: list[str] = []
    seen_issue_ids: set[str] = set()
    required = [
        "issue_id",
        "rule_id",
        "severity",
        "materiality_tier",
        "likely_owner",
        "cik",
        "report_date",
        "verdict",
        "mechanism",
        "recommended_action",
        "confidence",
        "affected_fair_value",
        "evidence",
        "residual_risk",
    ]
    for idx, record in enumerate(records, start=1):
        prefix = f"line {idx}"
        for field in required:
            if str(record.get(field, "") or "").strip() == "":
                if field == "evidence" and record.get("verdict") == "inconclusive":
                    continue
                errors.append(f"{prefix}: missing {field}")
        issue_id = str(record.get("issue_id", "") or "").strip()
        if issue_id:
            if issue_id in seen_issue_ids:
                errors.append(f"{prefix}: duplicate issue_id {issue_id}")
            seen_issue_ids.add(issue_id)
        verdict = str(record.get("verdict", "") or "").strip()
        if verdict not in _AGENT_VERDICT_ALLOWED_VALUES:
            errors.append(f"{prefix}: invalid verdict {verdict}")
        owner = str(record.get("likely_owner", "") or "").strip()
        if owner not in _AGENT_VERDICT_ALLOWED_OWNERS:
            errors.append(f"{prefix}: invalid likely_owner {owner}")
        confidence = pd.to_numeric(pd.Series([record.get("confidence")]), errors="coerce").iloc[0]
        if pd.isna(confidence) or float(confidence) < 0.0 or float(confidence) > 1.0:
            errors.append(f"{prefix}: confidence must be between 0 and 1")
        mechanism = str(record.get("mechanism", "") or "").strip()
        if verdict == "true_wrapper_error" and not mechanism:
            errors.append(f"{prefix}: true_wrapper_error requires mechanism")
        action = str(record.get("recommended_action", "") or "").strip().lower()
        if verdict == "true_wrapper_error" and not action:
            errors.append(f"{prefix}: true_wrapper_error requires deterministic repair path")
        if "hand-edit" in action or "edit production output" in action or "edit csv" in action:
            errors.append(f"{prefix}: recommended_action cannot ask for hand-edited production output")
        if verdict == "false_positive" and not mechanism:
            errors.append(f"{prefix}: false_positive requires scoped reason in mechanism")
    return errors


def build_agent_verdict_summary(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Reduce validated agent verdicts to deterministic promotion effects."""
    if not records:
        return pd.DataFrame(columns=AGENT_VERDICT_SUMMARY_COLUMNS)
    errors = validate_agent_verdict_records(records)
    if errors:
        raise ValueError("Invalid agent verdict records: " + "; ".join(errors))
    rows: list[dict[str, Any]] = []
    for record in records:
        verdict = str(record.get("verdict", "") or "")
        owner = str(record.get("likely_owner", "") or "")
        tier = str(record.get("materiality_tier", "") or "P2")
        confidence = _safe_float(record.get("confidence", 0))
        affected_fv = _safe_float(record.get("affected_fair_value", 0))
        effect = "info"
        if verdict == "true_wrapper_error" and owner == "wrapper" and tier in {"P0", "P1"}:
            effect = "reject"
        elif verdict == "inconclusive" and tier in {"P0", "P1"}:
            effect = "review"
        elif verdict == "false_positive" and confidence < 0.80 and tier in {"P0", "P1"}:
            effect = "review"
        elif verdict == "not_wrapper_owned" and tier == "P0":
            effect = "review"
        rows.append({
            "verdict": verdict,
            "likely_owner": owner,
            "materiality_tier": tier,
            "affected_fair_value": affected_fv,
            "confidence": confidence,
            "promotion_effect": effect,
        })
    df = pd.DataFrame(rows)
    grouped = (
        df.groupby(["verdict", "likely_owner", "materiality_tier", "promotion_effect"], dropna=False)
        .agg(
            issue_count=("verdict", "size"),
            affected_fair_value=("affected_fair_value", "sum"),
            max_confidence=("confidence", "max"),
        )
        .reset_index()
    )
    return grouped[AGENT_VERDICT_SUMMARY_COLUMNS].sort_values(
        ["promotion_effect", "materiality_tier", "verdict", "likely_owner"],
        kind="stable",
    ).reset_index(drop=True)


def _load_agent_verdict_summary(out_dir: Path) -> pd.DataFrame:
    verdict_path = out_dir / "agent_verdicts.jsonl"
    records = _load_agent_verdict_records(verdict_path)
    return build_agent_verdict_summary(records)


def _parsed_field_issue_record(
    row: pd.Series,
    *,
    cik: str,
    column: str,
    issue_type: str,
    output_value: str,
    evidence_token: str,
    fair_value: Any,
    wrapper_disposition: str,
    source_row_id: str = "",
    output_row_id: str = "",
    bdc_investment_identifier: str = "",
) -> dict[str, Any]:
    return {
        "cik": cik,
        "entity_name": _first_non_empty(row, "entity_name"),
        "report_date": _first_non_empty(row, "report_date"),
        "accession_number": _first_non_empty(row, "accession_number"),
        "source_row_id": source_row_id or _first_non_empty(row, "source_row_id"),
        "output_row_id": output_row_id or _first_non_empty(row, "output_row_id"),
        "bdc_investment_identifier": (
            bdc_investment_identifier
            or _first_non_empty(
                row,
                "bdc_investment_identifier",
                "raw_investment_identifier",
                "investment_identifier",
                "normalized_investment_identifier",
            )
        ),
        "column": column,
        "issue_type": issue_type,
        "severity": "warn",
        "fair_value": _safe_float(fair_value),
        "output_value": output_value,
        "evidence_token": evidence_token,
        "wrapper_disposition": wrapper_disposition,
        "suggested_owner": "llm_review",
        "recommended_action": (
            "Review row against source filing; if true error, add or adjust the CIK wrapper "
            "so this field excludes hierarchy, rate/date, or low-information fragments."
        ),
    }


def _pattern_token(pattern: re.Pattern[str], value: str) -> str:
    match = pattern.search(value)
    return match.group(0) if match else ""


def _parsed_field_checks_for_value(*, column: str, value: str) -> list[tuple[str, str]]:
    text = str(value or "").strip()
    if not text:
        return []
    checks: list[tuple[str, str]] = []
    if column == "instrument_description":
        token = _pattern_token(_PARSED_FIELD_LABEL_PATTERN, text)
        if token:
            issue_type = (
                "rate_or_date_contamination"
                if _PARSED_FIELD_EXPLICIT_RATE_DATE_PATTERN.search(token)
                else "hierarchy_or_metric_contamination"
            )
            checks.append((issue_type, token))
        token = _pattern_token(_PARSED_SOURCE_SECTION_PATTERN, text)
        if token:
            checks.append(("hierarchy_or_metric_contamination", token))
        return checks
    if column == "issuer_name":
        token = _pattern_token(_PARSED_FIELD_PCT_PATTERN, text)
        if token:
            checks.append(("hierarchy_or_metric_contamination", token))
        token = _pattern_token(_PARSED_FIELD_HIERARCHY_PATTERN, text)
        if token:
            checks.append(("hierarchy_or_metric_contamination", token))
        token = _pattern_token(_PARSED_FIELD_RATE_DATE_PATTERN, text)
        if token:
            checks.append(("rate_or_date_contamination", token))
    elif column == "position_key":
        token = _pattern_token(_PARSED_FIELD_LABEL_PATTERN, text)
        if token:
            issue_type = (
                "rate_or_date_contamination"
                if _PARSED_FIELD_EXPLICIT_RATE_DATE_PATTERN.search(token)
                else "hierarchy_or_metric_contamination"
            )
            checks.append((issue_type, token))
        token = _pattern_token(_PARSED_FIELD_HIERARCHY_PATTERN, text)
        if token:
            checks.append(("hierarchy_or_metric_contamination", token))
        token = _pattern_token(_PARSED_FIELD_EXPLICIT_RATE_DATE_PATTERN, text)
        if token:
            checks.append(("rate_or_date_contamination", token))
        tokens = _PARSED_POSITION_TOKEN_PATTERN.findall(text.lower())
        if 0 < len(tokens) < 3:
            checks.append(("low_information_position_key", text))
    return checks


def _build_parsed_field_quality_packets(
    detail_df: pd.DataFrame,
    holdings_df: pd.DataFrame | None,
    *,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    """Build review-only packets for suspicious parsed wrapper output fields.

    These packets are intentionally scoped to one CIK and do not affect oracle
    pass/fail status. They give the agent row-level evidence when a wrapper may
    be putting hierarchy, rate/date, or low-information text into production
    output columns.
    """
    cik_norm = normalize_cik(cik)
    records: list[dict[str, Any]] = []

    if not detail_df.empty:
        detail = _ensure_detail_columns(detail_df)
        detail = detail[detail["cik"].eq(cik_norm)].copy()
        for _, row in detail.iterrows():
            fair_value = row.get("output_fair_value")
            if pd.isna(fair_value) or _safe_float(fair_value) == 0:
                fair_value = row.get("source_fair_value")
            wrapper_disposition = _first_non_empty(
                row,
                "output_wrapper_disposition",
                "source_wrapper_disposition",
            )
            for column in ("issuer_name", "instrument_description"):
                value = _first_non_empty(row, column)
                for issue_type, token in _parsed_field_checks_for_value(
                    column=column,
                    value=value,
                ):
                    records.append(
                        _parsed_field_issue_record(
                            row,
                            cik=cik_norm,
                            column=column,
                            issue_type=issue_type,
                            output_value=value,
                            evidence_token=token,
                            fair_value=fair_value,
                            wrapper_disposition=wrapper_disposition,
                        )
                    )
            value = _first_non_empty(row, "output_wrapper_position_key")
            for issue_type, token in _parsed_field_checks_for_value(
                column="position_key",
                value=value,
            ):
                records.append(
                    _parsed_field_issue_record(
                        row,
                        cik=cik_norm,
                        column="position_key",
                        issue_type=issue_type,
                        output_value=value,
                        evidence_token=token,
                        fair_value=fair_value,
                        wrapper_disposition=wrapper_disposition,
                    )
                )

    if holdings_df is not None and not holdings_df.empty and "cik" in holdings_df.columns:
        holdings = holdings_df.copy()
        holdings["cik"] = holdings["cik"].map(normalize_cik)
        holdings = holdings[holdings["cik"].eq(cik_norm)].copy()
        if "position_key" in holdings.columns and not holdings.empty:
            for _, row in holdings.iterrows():
                value = _first_non_empty(row, "position_key")
                wrapper_disposition = _first_non_empty(row, "wrapper_disposition")
                fair_value = _first_non_empty(row, "fair_value", "reported_value", "value")
                identifier = _first_non_empty(
                    row,
                    "bdc_investment_identifier",
                    "investment_identifier",
                    "raw_investment_identifier",
                )
                for issue_type, token in _parsed_field_checks_for_value(
                    column="position_key",
                    value=value,
                ):
                    records.append(
                        _parsed_field_issue_record(
                            row,
                            cik=cik_norm,
                            column="position_key",
                            issue_type=issue_type,
                            output_value=value,
                            evidence_token=token,
                            fair_value=fair_value,
                            wrapper_disposition=wrapper_disposition,
                            source_row_id="",
                            output_row_id="",
                            bdc_investment_identifier=identifier,
                        )
                    )

    if not records:
        return pd.DataFrame(columns=PARSED_FIELD_QUALITY_COLUMNS)
    packets = pd.DataFrame(records, columns=PARSED_FIELD_QUALITY_COLUMNS)
    return packets.drop_duplicates(PARSED_FIELD_QUALITY_COLUMNS).reset_index(drop=True)


def _append_parsed_field_quality_summary(
    summary_df: pd.DataFrame,
    packets_df: pd.DataFrame,
) -> pd.DataFrame:
    summary = summary_df.copy()
    for col in ORACLE_SUMMARY_COLUMNS:
        if col not in summary.columns:
            summary[col] = ""
    if summary.empty:
        return summary[ORACLE_SUMMARY_COLUMNS]
    summary["parsed_field_quality_issue_count"] = 0
    summary["parsed_field_quality_fair_value"] = 0.0
    if not packets_df.empty:
        packets = packets_df.copy()
        packets["report_date"] = packets["report_date"].astype(str)
        packets["fair_value"] = pd.to_numeric(packets["fair_value"], errors="coerce").fillna(0).abs()
        issue_counts = packets.groupby("report_date", dropna=False).agg(
            parsed_field_quality_issue_count=("issue_type", "size"),
        )
        material_rows = packets.drop_duplicates(
            [
                "report_date",
                "source_row_id",
                "output_row_id",
                "bdc_investment_identifier",
                "fair_value",
            ]
        )
        materiality = material_rows.groupby("report_date", dropna=False).agg(
            parsed_field_quality_fair_value=("fair_value", "sum"),
        )
        packet_summary = issue_counts.merge(
            materiality,
            left_index=True,
            right_index=True,
            how="left",
        )
        for idx, row in summary.iterrows():
            report_date = str(row.get("report_date", ""))
            if report_date in packet_summary.index:
                summary.at[idx, "parsed_field_quality_issue_count"] = int(
                    packet_summary.at[report_date, "parsed_field_quality_issue_count"]
                )
                summary.at[idx, "parsed_field_quality_fair_value"] = round(
                    float(packet_summary.at[report_date, "parsed_field_quality_fair_value"]),
                    2,
                )
    return summary[ORACLE_SUMMARY_COLUMNS]


def _split_reason_string(value: Any) -> set[str]:
    return {part for part in str(value or "").split("|") if part}


def _normalized_wrapper_versions(wrapper_version_by_cik: dict[str, Any] | None) -> dict[str, str]:
    if not wrapper_version_by_cik:
        return {}
    return {
        normalize_cik(cik): str(version)
        for cik, version in wrapper_version_by_cik.items()
        if str(version or "").strip()
    }


def _waiveable_reason_sets(
    reasons_set: set[str],
    *,
    cik: str,
    report_date: str,
    wrapper_version: str,
    oracle_exceptions: pd.DataFrame | None,
) -> tuple[set[str], set[str]]:
    waived: set[str] = set()
    unwaived: set[str] = set()
    for reason in reasons_set:
        if (
            reason in _PROMOTION_EXCEPTION_ELIGIBLE_REASONS
            and reason_is_waived(
                oracle_exceptions,
                cik=cik,
                report_date=report_date,
                oracle_reason=reason,
                wrapper_version=wrapper_version,
            )
        ):
            waived.add(reason)
        else:
            unwaived.add(reason)
    return waived, unwaived


def evaluate_promotion_gate(
    current_summary: pd.DataFrame,
    baseline_comparison: pd.DataFrame | None = None,
    *,
    oracle_exceptions: pd.DataFrame | None = None,
    wrapper_version_by_cik: dict[str, Any] | None = None,
    verdict_summary: pd.DataFrame | None = None,
) -> PromotionVerdict:
    """Evaluate whether a wrapper change should be promoted.

    Checks absolute oracle thresholds from ``current_summary`` and relative
    improvements from ``baseline_comparison`` (before/after blocking metrics
    produced by ``build_baseline_comparison``).

    Returns a ``PromotionVerdict`` with status ``"promote"``, ``"reject"``,
    or ``"review_required"``.
    """
    wrapper_versions = _normalized_wrapper_versions(wrapper_version_by_cik)
    reject_reasons: list[str] = []
    review_reasons: list[str] = []
    improvements: list[str] = []
    total_blocking_delta = 0
    total_fv_delta = 0.0

    if current_summary.empty:
        return PromotionVerdict(
            status="reject",
            blocking_rows_delta=0,
            blocking_fv_delta=0.0,
            reasons=["no_oracle_data"],
            improvements=[],
            per_quarter=pd.DataFrame(columns=PROMOTION_GATE_COLUMNS),
        )

    # --- Absolute checks from current oracle summary ---
    for _, row in current_summary.iterrows():
        status = str(row.get("oracle_status", ""))
        reasons_set = _split_reason_string(row.get("oracle_fail_reasons", ""))
        rd = str(row.get("report_date", ""))
        cik_val = normalize_cik(row.get("cik", ""))
        wrapper_version = wrapper_versions.get(cik_val, "")

        if status == "fail":
            _waived, unwaived = _waiveable_reason_sets(
                reasons_set,
                cik=cik_val,
                report_date=rd,
                wrapper_version=wrapper_version,
                oracle_exceptions=oracle_exceptions,
            )
            for reason in sorted(unwaived & _PROMOTION_REJECT_REASONS):
                reject_reasons.append(f"{rd}: {reason}")
            for reason in sorted(unwaived & _PROMOTION_REVIEW_REASONS):
                review_reasons.append(f"{rd}: {reason}")
            # Remaining mechanism reasons (not diagnostic)
            for reason in sorted(unwaived):
                if reason.startswith("remaining_") and reason not in {
                    "remaining_cash_or_money_market",
                    "remaining_aggregate",
                    "remaining_non_private_market",
                }:
                    review_reasons.append(f"{rd}: {reason}")

    # --- Relative checks from baseline comparison ---
    if baseline_comparison is not None and not baseline_comparison.empty:
        bc = baseline_comparison.copy()
        for col in [
            "blocking_rows_delta",
            "blocking_fair_value_delta",
            "documented_rollup_delta",
            "cleared_rollup_fair_value_delta",
        ]:
            if col in bc.columns:
                bc[col] = pd.to_numeric(bc[col], errors="coerce").fillna(0)

        if "blocking_rows_delta" in bc.columns:
            total_blocking_delta = int(bc["blocking_rows_delta"].sum())
        if "blocking_fair_value_delta" in bc.columns:
            total_fv_delta = float(bc["blocking_fair_value_delta"].sum())

        if total_blocking_delta > 0:
            reject_reasons.append(
                f"blocking_rows_increased: total_delta=+{total_blocking_delta}"
            )
        elif total_blocking_delta < 0:
            improvements.append(
                f"blocking_rows_reduced: total_delta={total_blocking_delta}"
            )

        if total_fv_delta > 0:
            reject_reasons.append(
                f"blocking_fv_increased: total_delta=+{total_fv_delta:.0f}"
            )
        elif total_fv_delta < 0:
            improvements.append(
                f"blocking_fv_reduced: total_delta={total_fv_delta:.0f}"
            )

        # Per-quarter regression check
        if "blocking_rows_delta" in bc.columns:
            regressed = bc[bc["blocking_rows_delta"] > 0]
            for _, rq in regressed.iterrows():
                review_reasons.append(
                    f"{rq.get('report_date', '')}: blocking_rows_regressed "
                    f"(delta=+{int(rq['blocking_rows_delta'])})"
                )

        # Cleared rollup improvements
        if "documented_rollup_delta" in bc.columns:
            total_rollup_delta = int(bc["documented_rollup_delta"].sum())
            if total_rollup_delta > 0:
                improvements.append(
                    f"cleared_rollups_increased: total_delta=+{total_rollup_delta}"
                )

    # --- Review-adjusted verdict effects ---
    if verdict_summary is not None and not verdict_summary.empty:
        summary_df = verdict_summary.copy()
        if "promotion_effect" not in summary_df.columns:
            reject_reasons.append("malformed_agent_verdict_summary")
        else:
            for _, vrow in summary_df.iterrows():
                effect = str(vrow.get("promotion_effect", "") or "")
                verdict = str(vrow.get("verdict", "") or "")
                owner = str(vrow.get("likely_owner", "") or "")
                tier = str(vrow.get("materiality_tier", "") or "")
                issue_count = _safe_int(vrow.get("issue_count", 0))
                affected_fv = _safe_float(vrow.get("affected_fair_value", 0))
                reason = (
                    f"agent_verdict_{effect}: {verdict}/{owner}/{tier} "
                    f"issues={issue_count} affected_fv={affected_fv:.0f}"
                )
                if effect == "reject":
                    reject_reasons.append(reason)
                elif effect == "review":
                    review_reasons.append(reason)

    # --- Build per-quarter comparison ---
    per_quarter_rows = []
    for _, row in current_summary.iterrows():
        rd = str(row.get("report_date", ""))
        cik_val = normalize_cik(row.get("cik", ""))
        wrapper_version = wrapper_versions.get(cik_val, "")
        raw_reasons = _split_reason_string(row.get("oracle_fail_reasons", ""))
        waived, unwaived = _waiveable_reason_sets(
            raw_reasons,
            cik=cik_val,
            report_date=rd,
            wrapper_version=wrapper_version,
            oracle_exceptions=oracle_exceptions,
        )
        raw_status = str(row.get("oracle_status", ""))
        effective_status = (
            "pass"
            if raw_status == "fail" and raw_reasons and not unwaived
            else raw_status
        )
        bc_row: dict[str, Any] = {}
        if baseline_comparison is not None and not baseline_comparison.empty:
            bc_match = baseline_comparison[
                baseline_comparison["report_date"].astype(str).eq(rd)
            ]
            if not bc_match.empty:
                bc_row = bc_match.iloc[0].to_dict()

        q_reasons: list[str] = []
        q_blocking_delta = int(_safe_float(bc_row.get("blocking_rows_delta", 0)))
        if q_blocking_delta > 0:
            q_reasons.append("blocking_rows_regressed")
        if effective_status == "fail":
            q_reasons.append("oracle_fail")

        per_quarter_rows.append({
            "cik": cik_val,
            "report_date": rd,
            "current_blocking_rows": int(
                _safe_float(row.get("remaining_blocking_rows", 0))
            ),
            "baseline_blocking_rows": int(
                _safe_float(bc_row.get("baseline_blocking_rows", 0))
            ),
            "blocking_rows_delta": q_blocking_delta,
            "current_blocking_fv": float(
                _safe_float(row.get("remaining_blocking_fair_value", 0))
            ),
            "baseline_blocking_fv": float(
                _safe_float(bc_row.get("baseline_blocking_fair_value", 0))
            ),
            "blocking_fv_delta": float(
                _safe_float(bc_row.get("blocking_fair_value_delta", 0))
            ),
            "current_cleared_rollup_rows": int(
                _safe_float(row.get("cleared_rollup_rows", 0))
            ),
            "baseline_cleared_rollup_rows": int(
                _safe_float(
                    bc_row.get(
                        "baseline_documented_source_rollup_exact_rows", 0
                    )
                )
            ),
            "cleared_rollup_delta": int(
                _safe_float(bc_row.get("documented_rollup_delta", 0))
            ),
            "current_unclassified_rate": _safe_float(
                row.get("unclassified_rate", "")
            ),
            "current_unclassified_fv_rate": _safe_float(
                row.get("unclassified_fv_rate", "")
            ),
            "current_oracle_status": str(row.get("oracle_status", "")),
            "waived_oracle_reasons": "|".join(sorted(waived)),
            "unwaived_oracle_reasons": "|".join(sorted(unwaived)),
            "effective_oracle_status": effective_status,
            "quarter_verdict": "reject" if q_reasons else "pass",
            "quarter_reasons": "|".join(q_reasons),
        })

    per_quarter = pd.DataFrame(per_quarter_rows, columns=PROMOTION_GATE_COLUMNS)

    # --- Overall verdict ---
    if reject_reasons:
        status = "reject"
    elif review_reasons:
        status = "review_required"
    else:
        status = "promote"

    return PromotionVerdict(
        status=status,
        blocking_rows_delta=total_blocking_delta,
        blocking_fv_delta=total_fv_delta,
        reasons=reject_reasons + review_reasons,
        improvements=improvements,
        per_quarter=per_quarter,
    )


def validate_wrapper_definition_structure(
    wrapper: WrapperDefinition,
) -> list[str]:
    """Validate structural correctness of a wrapper definition.

    Returns a list of issue descriptions.  Empty list means valid.
    """
    issues: list[str] = []
    if not wrapper.archetypes:
        issues.append("no_archetypes_defined")
        return issues

    # Keyword overlap detection
    all_keywords: dict[str, str] = {}
    for arch in wrapper.archetypes:
        if not arch.keywords:
            issues.append(f"archetype '{arch.name}' has no keywords")
        for kw in arch.keywords:
            kw_lower = kw.lower()
            if kw_lower in all_keywords and all_keywords[kw_lower] != arch.name:
                issues.append(
                    f"keyword '{kw}' shared by '{all_keywords[kw_lower]}' "
                    f"and '{arch.name}'"
                )
            all_keywords[kw_lower] = arch.name

        # Field signature checks
        for sig in arch.field_signatures:
            if sig.sig_type == "numeric_range":
                if (
                    sig.min_val is not None
                    and sig.max_val is not None
                    and sig.min_val > sig.max_val
                ):
                    issues.append(
                        f"archetype '{arch.name}' field '{sig.field_name}': "
                        f"min ({sig.min_val}) > max ({sig.max_val})"
                    )
            if sig.constraint not in ("required", "forbidden", "optional"):
                issues.append(
                    f"archetype '{arch.name}' field '{sig.field_name}': "
                    f"unknown constraint '{sig.constraint}'"
                )

    return issues


def validate_wrapper_json_coherence(raw: dict[str, Any]) -> list[str]:
    """Check cross-section invariants in a raw wrapper JSON dict.

    Complements ``validate_wrapper_definition_structure`` (which checks
    parsed archetype structure) by validating the raw JSON before parsing.
    Returns a list of issue descriptions; empty means valid.
    """
    issues: list[str] = []
    dispatch = raw.get("dispatch") or {}
    staging = raw.get("staging") or {}

    # --- 1. Family-marker alignment ---
    prefix_rules = dispatch.get("prefix_rules") or {}
    leaf_markers = dispatch.get("leaf_markers_by_family") or {}
    if prefix_rules and leaf_markers:
        families_used = set(prefix_rules.values())
        for family in sorted(families_used):
            if family not in leaf_markers:
                issues.append(
                    f"warning: family '{family}' in prefix_rules has no "
                    f"entry in leaf_markers_by_family"
                )

    # --- 2. Staging strategy prerequisites ---
    strategy = staging.get("strategy", "")
    if strategy == "prefix_strip":
        if not staging.get("hierarchy_prefix_re"):
            issues.append(
                "staging strategy 'prefix_strip' requires "
                "'hierarchy_prefix_re'"
            )
    elif strategy == "hierarchy_extract":
        if not staging.get("hierarchy_issuer_re"):
            issues.append(
                "staging strategy 'hierarchy_extract' requires "
                "'hierarchy_issuer_re'"
            )
        if not staging.get("hierarchy_instrument_re"):
            issues.append(
                "staging strategy 'hierarchy_extract' requires "
                "'hierarchy_instrument_re'"
            )
    elif strategy == "hierarchy_leaf_guard":
        leaf_guard = staging.get("leaf_guard") or {}
        if not leaf_guard.get("marker_re"):
            issues.append(
                "staging strategy 'hierarchy_leaf_guard' requires "
                "'leaf_guard.marker_re'"
            )
        if not leaf_guard.get("evidence_re"):
            issues.append(
                "staging strategy 'hierarchy_leaf_guard' requires "
                "'leaf_guard.evidence_re'"
            )
    elif strategy == "issuer_bridge":
        bridges = staging.get("issuer_bridges") or []
        if not bridges:
            issues.append(
                "staging strategy 'issuer_bridge' requires non-empty "
                "'issuer_bridges' array"
            )

    # --- 3. Regex compilation ---
    _REGEX_FIELDS_DISPATCH = [
        ("dispatch", "canonical_strip_re"),
        ("dispatch", "category_marker_re"),
    ]
    _REGEX_FIELDS_STAGING = [
        ("staging", "hierarchy_prefix_re"),
        ("staging", "hierarchy_issuer_re"),
        ("staging", "hierarchy_instrument_re"),
        ("staging", "hierarchy_trailing_re"),
    ]
    _REGEX_FIELDS_LEAF_GUARD = [
        "marker_re",
        "evidence_re",
        "issuer_re",
        "instrument_re",
        "type_industry_prefix_re",
    ]

    for section_key, field_key in _REGEX_FIELDS_DISPATCH + _REGEX_FIELDS_STAGING:
        section = raw.get(section_key) or {}
        value = section.get(field_key)
        if isinstance(value, str) and value:
            try:
                re.compile(value)
            except re.error as exc:
                issues.append(
                    f"{section_key}.{field_key} is not a valid regex: {exc}"
                )

    leaf_guard = (raw.get("staging") or {}).get("leaf_guard") or {}
    for field_key in _REGEX_FIELDS_LEAF_GUARD:
        value = leaf_guard.get(field_key)
        if isinstance(value, str) and value:
            try:
                re.compile(value)
            except re.error as exc:
                issues.append(
                    f"staging.leaf_guard.{field_key} is not a valid regex: "
                    f"{exc}"
                )

    # Fallback family patterns regexes
    for i, pat in enumerate(dispatch.get("fallback_family_patterns") or []):
        regex_val = pat.get("regex", "")
        if isinstance(regex_val, str) and regex_val:
            try:
                re.compile(regex_val)
            except re.error as exc:
                issues.append(
                    f"dispatch.fallback_family_patterns[{i}].regex is not "
                    f"a valid regex: {exc}"
                )

    # --- 4. Fallback family consistency ---
    # Fallback families often catch one-off patterns where leaf/rollup
    # classification may not apply, so missing leaf markers is a warning.
    if leaf_markers:
        for i, pat in enumerate(
            dispatch.get("fallback_family_patterns") or []
        ):
            family = pat.get("family", "")
            if family and family not in leaf_markers:
                issues.append(
                    f"warning: fallback_family_patterns[{i}] family "
                    f"'{family}' has no entry in leaf_markers_by_family"
                )

    # --- 5. Archetype-dispatch alignment warning ---
    archetypes = raw.get("archetypes") or {}
    if archetypes and dispatch:
        archetype_names = set(archetypes.keys())
        dispatch_families = set(prefix_rules.values())
        for pat in dispatch.get("fallback_family_patterns") or []:
            dispatch_families.add(pat.get("family", ""))
        dispatch_families.discard("")
        if dispatch_families and not (archetype_names & dispatch_families):
            issues.append(
                f"warning: archetype names {sorted(archetype_names)} "
                f"have no overlap with dispatch families "
                f"{sorted(dispatch_families)} -- classification systems "
                f"may be disconnected"
            )

    return issues


def _wrapper_version_by_cik(cik: str) -> dict[str, str]:
    wrapper = load_wrapper_definition(cik)
    if wrapper is None:
        return {}
    return {normalize_cik(cik): str(wrapper.version)}


def build_exception_proposals(
    current_summary: pd.DataFrame,
    *,
    wrapper_version_by_cik: dict[str, Any] | None = None,
    oracle_exceptions: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Build inactive proposal templates for waiveable soft oracle reasons."""
    wrapper_versions = _normalized_wrapper_versions(wrapper_version_by_cik)
    proposals: list[dict[str, Any]] = []
    if current_summary.empty:
        return proposals
    seen: set[tuple[str, str, str, str]] = set()
    for _, row in current_summary.iterrows():
        if str(row.get("oracle_status", "")) != "fail":
            continue
        cik_val = normalize_cik(row.get("cik", ""))
        report_date = str(row.get("report_date", ""))
        wrapper_version = wrapper_versions.get(cik_val, "")
        for reason in sorted(_split_reason_string(row.get("oracle_fail_reasons", ""))):
            if reason not in _PROMOTION_EXCEPTION_ELIGIBLE_REASONS:
                continue
            if reason_is_waived(
                oracle_exceptions,
                cik=cik_val,
                report_date=report_date,
                oracle_reason=reason,
                wrapper_version=wrapper_version,
            ):
                continue
            key = (cik_val, report_date, reason, wrapper_version)
            if key in seen:
                continue
            seen.add(key)
            proposals.append({
                "schema_version": ORACLE_EXCEPTION_SCHEMA_VERSION,
                "cik": cik_val,
                "report_date": report_date,
                "oracle_reason": reason,
                "wrapper_version": wrapper_version,
                "status": "proposed",
                "confidence": "",
                "reason": "",
                "evidence": "",
                "residual_risk": "",
                "created_by": "agent",
                "accepted_by": "",
                "updated_at": "",
            })
    return proposals


def run_promotion_trial(
    *,
    cik: str = TRINITY_CIK,
    output_dir: Path | None = None,
    fresh_bdc_staging: bool = False,
    holdings_file: Path | None = None,
) -> PromotionVerdict:
    """Run full promotion gate trial for one CIK.

    Runs the oracle with ``compare_baseline=True``, validates the wrapper
    definition structure, evaluates the promotion gate, and writes artifacts.
    """
    cik_norm = normalize_cik(cik)
    out_dir = output_dir or (OUTPUT_DIR / "bdc_xbrl_wrapper_trial" / cik_norm)

    _detail, summary, _cleared, _remaining, baseline = run_wrapper_oracle_trial(
        cik=cik_norm,
        output_dir=out_dir,
        compare_baseline=True,
        fresh_bdc_staging=fresh_bdc_staging,
        holdings_file=holdings_file,
    )

    # Structural validation
    wrapper = load_wrapper_definition(cik_norm)
    structural_issues = (
        validate_wrapper_definition_structure(wrapper)
        if wrapper is not None
        else ["no_wrapper_definition"]
    )

    wrapper_versions = _wrapper_version_by_cik(cik_norm)
    oracle_exceptions = load_bdc_xbrl_oracle_exceptions()
    verdict_summary = pd.DataFrame(columns=AGENT_VERDICT_SUMMARY_COLUMNS)
    verdict_summary_path = out_dir / "agent_verdict_summary.csv"
    if verdict_summary_path.exists():
        verdict_summary = pd.read_csv(verdict_summary_path, dtype=str)
    verdict = evaluate_promotion_gate(
        summary,
        baseline,
        oracle_exceptions=oracle_exceptions,
        wrapper_version_by_cik=wrapper_versions,
        verdict_summary=verdict_summary,
    )
    exception_proposals = build_exception_proposals(
        summary,
        wrapper_version_by_cik=wrapper_versions,
        oracle_exceptions=oracle_exceptions,
    )

    # Merge structural issues into verdict
    for issue in structural_issues:
        verdict.reasons.append(f"structural: {issue}")
        if verdict.status == "promote":
            verdict.status = "review_required"

    # Write promotion artifacts
    out_dir.mkdir(parents=True, exist_ok=True)
    verdict.per_quarter.to_csv(out_dir / "promotion_comparison.csv", index=False)
    verdict_dict = {
        "status": verdict.status,
        "blocking_rows_delta": verdict.blocking_rows_delta,
        "blocking_fv_delta": verdict.blocking_fv_delta,
        "reasons": verdict.reasons,
        "improvements": verdict.improvements,
        "structural_issues": structural_issues,
    }
    with open(out_dir / "promotion_verdict.json", "w", encoding="utf-8") as fh:
        json_mod.dump(verdict_dict, fh, indent=2)
    with open(out_dir / "exception_proposals.json", "w", encoding="utf-8") as fh:
        json_mod.dump(
            {
                "schema_version": ORACLE_EXCEPTION_SCHEMA_VERSION,
                "exceptions": exception_proposals,
            },
            fh,
            indent=2,
        )

    return verdict


def _bool_col(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _numeric_col(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def _sample_identifiers(value: Any) -> list[str]:
    raw = "" if value is None else str(value)
    return [normalize_wrapper_identifier(part) for part in raw.split(" | ") if part and part.strip()]


def _detect_prefix(identifier: str) -> str:
    raw = normalize_wrapper_identifier(identifier)
    if not raw:
        return ""
    raw = re.sub(
        r"^(?:Non[- ]?(?:Controlled?|Affiliated?|Affiliate)|Controlled?|Affiliated?|Affiliate)"
        r"(?:\s*/\s*Non[- ]?(?:Affiliated?|Affiliate))?\s+(?:Investments|Investment)\s*[-,]?\s*",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    if not raw:
        return ""
    for separator in [" - ", "-"]:
        if separator in raw:
            prefix = raw.split(separator, 1)[0].strip()
            if prefix and prefix.lower() not in {"non", "non controlled", "non affiliated", "non affiliate"}:
                return prefix[:120]
    lowered = raw.lower()
    marker_positions = [
        lowered.find(marker)
        for marker in [
            " type of investment",
            " investment date",
            " maturity date",
            " interest rate",
            " reference rate",
        ]
        if lowered.find(marker) > 0
    ]
    if marker_positions:
        return raw[: min(marker_positions)].strip()[:120]
    words = raw.split()
    return " ".join(words[:5])[:120]


def _candidate_from_identifier(identifier: str) -> tuple[str, str]:
    raw = normalize_wrapper_identifier(identifier)
    lowered = raw.lower()
    if is_non_private_market_identifier(raw):
        return "non_private_market", "likely_non_private_market"
    if any(
        token in lowered
        for token in [
            "sub-total",
            "subtotal",
            "total investments",
            "total debt investments",
            "total equity investments",
            "portfolio investments",
            "investment in securities",
            "control and affiliate investments",
        ]
    ):
        return "aggregate", "likely_aggregate"
    if lowered.startswith("total ") or " total " in f" {lowered} ":
        return "aggregate", "likely_aggregate"
    if pd.Series([raw]).str.match(r"^\d[\d.]*%\s+-\s+", na=False).iloc[0]:
        return "pct_prefix_signature", "needs_html_evidence"
    if any(
        token in lowered
        for token in [
            "type of investment",
            "investment type",
            "investment date",
            "initial acquisition date",
            "maturity date",
            "interest rate",
            "reference rate",
            "current coupon",
            "first lien",
            "1st lien",
            "second lien",
            "term loan",
            "revolving credit facility",
            "delayed draw",
            "common stock",
            "preferred stock",
            "preferred units",
            "warrant",
        ]
    ):
        return "position_leaf", "add_per_cik_wrapper"
    return "unclassified_signature", "unresolved"


def build_residual_wrapper_queue(
    clusters_df: pd.DataFrame,
    *,
    top: int = 25,
) -> pd.DataFrame:
    """Build a ranked CIK queue from source-only blocker clusters."""
    if clusters_df.empty:
        return pd.DataFrame(columns=QUEUE_COLUMNS)
    df = clusters_df.copy()
    for col in ["cik", "entity_name", "mechanism", "sample_identifiers"]:
        if col not in df.columns:
            df[col] = ""
    if "is_blocking" not in df.columns:
        df["is_blocking"] = False
    if "row_count" not in df.columns:
        df["row_count"] = 1
    if "source_fair_value" not in df.columns:
        df["source_fair_value"] = 0
    df["cik"] = df["cik"].map(normalize_cik)
    blocking = df[_bool_col(df["is_blocking"])].copy()
    if blocking.empty:
        return pd.DataFrame(columns=QUEUE_COLUMNS)
    blocking["row_count"] = _numeric_col(blocking["row_count"])
    blocking["source_fair_value"] = _numeric_col(blocking["source_fair_value"])
    rows: list[dict[str, Any]] = []
    for (cik, entity_name), group in blocking.groupby(["cik", "entity_name"], dropna=False):
        mechanisms = []
        for mechanism, mech_group in group.groupby("mechanism", dropna=False):
            mechanisms.append(
                f"{mechanism}:{int(_numeric_col(mech_group['row_count']).sum())}"
            )
        rows.append({
            "rank": 0,
            "cik": cik,
            "entity_name": entity_name,
            "blocking_packets": int(len(group)),
            "blocking_rows": int(group["row_count"].sum()),
            "source_fair_value": float(group["source_fair_value"].sum()),
            "supported_wrapper": cik in supported_wrapper_ciks(),
            "mechanisms": "; ".join(sorted(mechanisms)),
        })
    queue = pd.DataFrame(rows, columns=QUEUE_COLUMNS)
    queue = queue.sort_values(
        ["blocking_rows", "source_fair_value", "cik"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    if top and top > 0:
        queue = queue.head(top).copy()
    queue["rank"] = range(1, len(queue) + 1)
    return queue[QUEUE_COLUMNS]


def build_wrapper_profile_for_cik(clusters_df: pd.DataFrame, cik: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Profile blocker signatures for one CIK without adding runtime wrapper specs."""
    cik_norm = normalize_cik(cik)
    if clusters_df.empty:
        return (
            pd.DataFrame(columns=PROFILE_COLUMNS),
            pd.DataFrame(columns=CANDIDATE_RULE_COLUMNS),
        )
    df = clusters_df.copy()
    for col in [
        "cik",
        "entity_name",
        "report_date",
        "is_blocking",
        "row_count",
        "source_fair_value",
        "sample_identifiers",
    ]:
        if col not in df.columns:
            df[col] = ""
    df["cik"] = df["cik"].map(normalize_cik)
    df = df[df["cik"].eq(cik_norm) & _bool_col(df["is_blocking"])].copy()
    if df.empty:
        return (
            pd.DataFrame(columns=PROFILE_COLUMNS),
            pd.DataFrame(columns=CANDIDATE_RULE_COLUMNS),
        )
    df["row_count"] = _numeric_col(df["row_count"])
    df["source_fair_value"] = _numeric_col(df["source_fair_value"])
    profile_rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        samples = _sample_identifiers(row.get("sample_identifiers", ""))
        if not samples:
            samples = [""]
        dispositions = [_candidate_from_identifier(sample) for sample in samples]
        disposition, action = dispositions[0]
        prefix = _detect_prefix(samples[0])
        profile_rows.append({
            "cik": cik_norm,
            "entity_name": row.get("entity_name", ""),
            "report_date": row.get("report_date", ""),
            "detected_prefix": prefix,
            "candidate_disposition": disposition,
            "recommended_action": action,
            "packet_count": 1,
            "blocking_rows": int(row["row_count"]),
            "source_fair_value": float(row["source_fair_value"]),
            "sample_identifiers": " | ".join(samples[:5]),
        })
    profile = pd.DataFrame(profile_rows, columns=PROFILE_COLUMNS)
    grouped = profile.groupby(
        [
            "cik",
            "entity_name",
            "detected_prefix",
            "candidate_disposition",
            "recommended_action",
        ],
        dropna=False,
    )
    candidate_rows = []
    for keys, group in grouped:
        samples = []
        for value in group["sample_identifiers"].astype(str):
            samples.extend(_sample_identifiers(value))
        candidate_rows.append({
            "cik": keys[0],
            "entity_name": keys[1],
            "detected_prefix": keys[2],
            "candidate_disposition": keys[3],
            "recommended_action": keys[4],
            "packet_count": int(group["packet_count"].sum()),
            "blocking_rows": int(group["blocking_rows"].sum()),
            "source_fair_value": float(group["source_fair_value"].sum()),
            "sample_identifiers": " | ".join(samples[:5]),
        })
    candidates = pd.DataFrame(candidate_rows, columns=CANDIDATE_RULE_COLUMNS)
    candidates = candidates.sort_values(
        ["blocking_rows", "source_fair_value", "detected_prefix"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    profile = profile.sort_values(
        ["report_date", "blocking_rows", "detected_prefix"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    return profile[PROFILE_COLUMNS], candidates[CANDIDATE_RULE_COLUMNS]


def _ensure_detail_columns(detail_df: pd.DataFrame) -> pd.DataFrame:
    df = detail_df.copy()
    for col in DETAIL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["cik"] = df["cik"].map(normalize_cik)
    df["blocking_issue"] = _bool_col(df["blocking_issue"])
    for col in ["source_fair_value", "output_fair_value"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _is_rollup(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.endswith("_rollup")


def _is_leaf(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.endswith("_position_leaf")


def _presence_key(row: pd.Series, key_col: str) -> tuple[str, str, str, str]:
    return (
        normalize_cik(row.get("cik", "")),
        str(row.get("report_date", "") or ""),
        str(row.get("accession_number", "") or ""),
        str(row.get(key_col, "") or ""),
    )


def _wrapper_position_keys(
    df: pd.DataFrame,
    *,
    identifier_col: str,
    cik_col: str = "cik",
) -> set[tuple[str, str, str, str]]:
    if df.empty or identifier_col not in df.columns:
        return set()
    wrapped = add_bdc_xbrl_wrapper_columns(df, identifier_col=identifier_col, cik_col=cik_col)
    key_col = "wrapper_position_key"
    if key_col not in wrapped.columns:
        return set()
    leaf = wrapped[wrapped["wrapper_disposition"].fillna("").astype(str).str.endswith("_position_leaf")]
    leaf = leaf[leaf[key_col].fillna("").astype(str).ne("")]
    return {_presence_key(row, key_col) for _, row in leaf.iterrows()}


def _classify_remaining_mechanism(row: pd.Series) -> str:
    disposition = str(row.get("source_wrapper_disposition", "") or "")
    raw = str(row.get("raw_investment_identifier", "") or "")
    raw_lower = raw.lower()
    candidate_count = int(row.get("_candidate_output_count", 0) or 0)
    source_child_count = int(row.get("_candidate_source_child_count", 0) or 0)
    if disposition.endswith("_position_leaf"):
        if int(row.get("_raw_bdc_present_count", 0) or 0) and not int(row.get("_unified_present_count", 0) or 0):
            return "leaf_present_in_raw_missing_from_unified"
        return "leaf_output_candidate_unmatched" if candidate_count else "leaf_no_output_candidate"
    if "issuer_rollup" in disposition:
        return "issuer_rollup_source_child_fv_mismatch" if source_child_count >= 2 else "issuer_rollup_no_child_tie"
    if "category_rollup" in disposition:
        return "category_rollup_source_child_fv_mismatch" if source_child_count >= 2 else "category_rollup_no_child_tie"
    if "total_rollup" in disposition:
        return "total_rollup_source_child_fv_mismatch" if source_child_count >= 2 else "total_rollup_no_child_tie"
    if any(token in raw_lower for token in ["cash", "money market", "financial square", "government institutional"]):
        return "cash_or_money_market"
    if disposition == "aggregate":
        return "aggregate"
    if disposition == "non_private_market":
        return "non_private_market"
    if any(
        token in raw_lower
        for token in [
            "investment in securities",
            "portfolio investments",
            "total investments",
            "control and affiliate investments",
            "sub-total",
            "subtotal",
        ]
    ):
        return "aggregate"
    if " total " in f" {raw_lower} " or raw_lower.startswith("total "):
        return "aggregate"
    if disposition.endswith("_unclassified"):
        return "unclassified_signature"
    return "unclassified_signature"


def build_remaining_mechanism_summary(
    detail_df: pd.DataFrame,
    remaining_df: pd.DataFrame,
    *,
    raw_bdc_position_keys: set[tuple[str, str, str, str]] | None = None,
    unified_position_keys: set[tuple[str, str, str, str]] | None = None,
) -> pd.DataFrame:
    if remaining_df.empty:
        return pd.DataFrame(columns=REMAINING_MECHANISM_COLUMNS)

    detail = _ensure_detail_columns(detail_df)
    remaining = _ensure_detail_columns(remaining_df)
    raw_bdc_position_keys = raw_bdc_position_keys or set()
    unified_position_keys = unified_position_keys or set()
    output_rows = detail[detail["output_row_id"].astype(str).ne("")].copy()
    source_leaf_rows = detail[
        detail["source_row_id"].astype(str).ne("")
        & _is_leaf(detail["source_wrapper_disposition"])
        & detail["source_wrapper_parent_key"].astype(str).ne("")
        & detail["source_fair_value"].notna()
    ].copy()

    parent_counts = {}
    parent_fv = {}
    position_counts = {}
    position_fv = {}
    if not output_rows.empty:
        parent_group = output_rows.groupby(
            ["cik", "report_date", "accession_number", "output_wrapper_parent_key"],
            dropna=False,
        )
        parent_counts = parent_group["output_row_id"].nunique().to_dict()
        parent_fv = parent_group["output_fair_value"].sum(min_count=1).fillna(0).to_dict()
        position_group = output_rows.groupby(
            ["cik", "report_date", "accession_number", "output_wrapper_position_key"],
            dropna=False,
        )
        position_counts = position_group["output_row_id"].nunique().to_dict()
        position_fv = position_group["output_fair_value"].sum(min_count=1).fillna(0).to_dict()

    candidate_counts: list[int] = []
    candidate_fvs: list[float] = []
    source_child_counts: list[int] = []
    source_child_fvs: list[float] = []
    raw_present_counts: list[int] = []
    unified_present_counts: list[int] = []
    for _, row in remaining.iterrows():
        parent_key = str(row.get("source_wrapper_parent_key", "") or "")
        position_key = str(row.get("source_wrapper_position_key", "") or "")
        base_key = (row["cik"], row["report_date"], row["accession_number"])
        candidates = 0
        candidate_fv = 0.0
        if position_key:
            key = (*base_key, position_key)
            candidates = int(position_counts.get(key, 0))
            candidate_fv = float(position_fv.get(key, 0.0) or 0.0)
        if not candidates and parent_key:
            key = (*base_key, parent_key)
            candidates = int(parent_counts.get(key, 0))
            candidate_fv = float(parent_fv.get(key, 0.0) or 0.0)
        candidate_counts.append(candidates)
        candidate_fvs.append(candidate_fv)
        child_count = 0
        child_fv = 0.0
        if parent_key and str(row.get("source_wrapper_disposition", "") or "").endswith("_rollup"):
            child_rows = source_leaf_rows[
                source_leaf_rows["cik"].eq(row["cik"])
                & source_leaf_rows["report_date"].eq(row["report_date"])
                & source_leaf_rows["accession_number"].eq(row["accession_number"])
                & source_leaf_rows["source_wrapper_family"].eq(row.get("source_wrapper_family", ""))
                & source_leaf_rows["source_wrapper_parent_key"].astype(str).apply(
                    lambda value: f" {parent_key} " in f" {value} "
                )
            ]
            child_count = int(child_rows["source_row_id"].nunique())
            child_fv = float(child_rows["source_fair_value"].fillna(0).sum()) if child_count else 0.0
        source_child_counts.append(child_count)
        source_child_fvs.append(child_fv)
        presence_key = (*base_key, position_key)
        raw_present_counts.append(1 if position_key and presence_key in raw_bdc_position_keys else 0)
        unified_present_counts.append(1 if position_key and presence_key in unified_position_keys else 0)

    remaining["_candidate_output_count"] = candidate_counts
    remaining["_candidate_output_fair_value"] = candidate_fvs
    remaining["_candidate_source_child_count"] = source_child_counts
    remaining["_candidate_source_child_fair_value"] = source_child_fvs
    remaining["_raw_bdc_present_count"] = raw_present_counts
    remaining["_unified_present_count"] = unified_present_counts
    remaining["mechanism"] = remaining.apply(_classify_remaining_mechanism, axis=1)

    grouped = remaining.groupby(["cik", "entity_name", "report_date", "mechanism"], dropna=False)
    rows = []
    for keys, group in grouped:
        sample = " | ".join(group["raw_investment_identifier"].dropna().astype(str).head(5).tolist())
        rows.append({
            "cik": keys[0],
            "entity_name": keys[1],
            "report_date": keys[2],
            "mechanism": keys[3],
            "row_count": len(group),
            "source_fair_value": float(group["source_fair_value"].fillna(0).sum()),
            "candidate_output_count": int(group["_candidate_output_count"].fillna(0).sum()),
            "candidate_output_fair_value": float(group["_candidate_output_fair_value"].fillna(0).sum()),
            "candidate_source_child_count": int(group["_candidate_source_child_count"].fillna(0).sum()),
            "candidate_source_child_fair_value": float(group["_candidate_source_child_fair_value"].fillna(0).sum()),
            "raw_bdc_present_count": int(group["_raw_bdc_present_count"].fillna(0).sum()),
            "unified_present_count": int(group["_unified_present_count"].fillna(0).sum()),
            "sample_identifiers": sample,
        })
    return pd.DataFrame(rows, columns=REMAINING_MECHANISM_COLUMNS)


def _check_content_signatures(
    cik: str,
    holdings_df: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Run v2 content signature checks for a CIK if a wrapper definition exists.

    Returns a dict mapping report_date to per-quarter metrics including
    pass_rate, violation_count, unclassified rates, and FV coverage.
    """
    wrapper = load_wrapper_definition(cik)
    if wrapper is None or holdings_df.empty:
        return {}
    sig_summary, violations = validate_content_signatures(wrapper, holdings_df)
    if sig_summary.empty:
        return {}
    result = {}
    for _, row in sig_summary.iterrows():
        rd = str(row.get("report_date", ""))
        result[rd] = {
            "pass_rate": float(row.get("pass_rate", 0.0)),
            "violation_count": int(row.get("fail_rows", 0)),
            "unclassified_rate": float(row.get("unclassified_rate", 0.0)),
            "unclassified_rate_status": str(row.get("unclassified_rate_status", "")),
            "unclassified_fv_rate": float(row.get("unclassified_fv_rate", 0.0)),
            "unclassified_fv_rate_status": str(row.get("unclassified_fv_rate_status", "")),
        }
    return result


def _check_fv_reconciliation(
    cik: str,
    holdings_df: pd.DataFrame,
    fund_financials_df: pd.DataFrame | None = None,
) -> dict[str, dict[str, Any]]:
    """Run v2 FV reconciliation for a CIK if a wrapper definition exists.

    Returns a dict mapping report_date to {status, pct_diff}.
    """
    wrapper = load_wrapper_definition(cik)
    if wrapper is None or holdings_df.empty or fund_financials_df is None or fund_financials_df.empty:
        return {}
    fv_recon = validate_fv_reconciliation(wrapper, holdings_df, fund_financials_df)
    if fv_recon.empty:
        return {}
    result = {}
    for _, row in fv_recon.iterrows():
        rd = str(row.get("report_date", ""))
        result[rd] = {
            "status": str(row.get("status", "")),
            "pct_diff": float(row.get("pct_diff", 0.0) or 0.0),
        }
    return result


# ---------------------------------------------------------------------------
# Gap #7: Exclusion false-positive risk detection
# ---------------------------------------------------------------------------


def _check_exclusion_risk(group: pd.DataFrame) -> tuple[int, float]:
    """Check excluded rows for position-evidence keywords (Gap #7).

    Returns (risky_row_count, risky_fair_value).
    """
    src_disp = group["source_wrapper_disposition"].fillna("").astype(str)
    out_disp = group["output_wrapper_disposition"].fillna("").astype(str)
    excluded_mask = (
        src_disp.isin(["aggregate", "non_private_market"])
        | out_disp.isin(["aggregate", "non_private_market"])
    )
    excluded = group[excluded_mask]
    if excluded.empty:
        return 0, 0.0
    raw_lower = (
        excluded["raw_investment_identifier"].fillna("").astype(str).str.lower()
    )
    risk_mask = raw_lower.str.contains(
        _EXCLUSION_EVIDENCE_PATTERN, regex=True, na=False
    )
    risky = excluded[risk_mask]
    if risky.empty:
        return 0, 0.0
    risky_fv = float(
        pd.to_numeric(risky["source_fair_value"], errors="coerce")
        .fillna(0)
        .abs()
        .sum()
    )
    return len(risky), risky_fv


# ---------------------------------------------------------------------------
# Gap #8: Position key continuity
# ---------------------------------------------------------------------------


def _compute_position_continuity(detail_df: pd.DataFrame) -> dict[str, float]:
    """Compute position-key continuation rate between adjacent quarters (Gap #8).

    Returns dict mapping report_date -> continuation_rate (0.0-1.0).
    Only populated for the second quarter onward.
    """
    pos_col = "source_wrapper_position_key"
    if detail_df.empty or pos_col not in detail_df.columns:
        return {}
    leaf_mask = (
        detail_df["source_wrapper_disposition"]
        .fillna("")
        .astype(str)
        .str.endswith("_position_leaf")
    )
    leaves = detail_df[leaf_mask]
    if leaves.empty:
        return {}
    keys_by_quarter: dict[str, set[str]] = {}
    for rd, grp in leaves.groupby("report_date", dropna=False):
        keys = set(
            grp[pos_col].fillna("").astype(str).str.strip()
        ) - {""}
        if keys:
            keys_by_quarter[str(rd)] = keys
    if len(keys_by_quarter) < 2:
        return {}
    sorted_quarters = sorted(keys_by_quarter.keys())
    result: dict[str, float] = {}
    for i in range(1, len(sorted_quarters)):
        prev_keys = keys_by_quarter[sorted_quarters[i - 1]]
        curr_keys = keys_by_quarter[sorted_quarters[i]]
        continuing = prev_keys & curr_keys
        rate = len(continuing) / len(prev_keys) if prev_keys else 1.0
        result[sorted_quarters[i]] = round(rate, 4)
    return result


# ---------------------------------------------------------------------------
# Gap #4: Rate and scale outlier detection
# ---------------------------------------------------------------------------


def _check_rate_outliers(
    holdings_df: pd.DataFrame | None,
    wrapper: WrapperDefinition | None,
    report_date: str,
) -> int:
    """Count holdings rows with interest_rate outside rate_sanity bounds (Gap #4)."""
    if (
        wrapper is None
        or wrapper.rate_sanity is None
        or holdings_df is None
        or holdings_df.empty
        or "interest_rate" not in holdings_df.columns
        or "report_date" not in holdings_df.columns
    ):
        return 0
    h = holdings_df[holdings_df["report_date"].astype(str).eq(report_date)]
    if h.empty:
        return 0
    rates = pd.to_numeric(h["interest_rate"], errors="coerce").dropna()
    if rates.empty:
        return 0
    outliers = rates[
        (rates < wrapper.rate_sanity.min_pct) | (rates > wrapper.rate_sanity.max_pct)
    ]
    return int(len(outliers))


def _check_cost_fv_outliers(
    holdings_df: pd.DataFrame | None,
    report_date: str,
) -> int:
    """Count holdings rows with extreme cost/FV ratio (Gap #4)."""
    if (
        holdings_df is None
        or holdings_df.empty
        or "cost" not in holdings_df.columns
        or "fair_value" not in holdings_df.columns
        or "report_date" not in holdings_df.columns
    ):
        return 0
    h = holdings_df[holdings_df["report_date"].astype(str).eq(report_date)]
    if h.empty:
        return 0
    cost = pd.to_numeric(h["cost"], errors="coerce")
    fv = pd.to_numeric(h["fair_value"], errors="coerce")
    # Skip nominal-value positions (unfunded commitments, warrants at
    # minimal mark) where |FV| <= $1,000 -- the ratio is meaningless.
    valid = cost.notna() & fv.notna() & fv.ne(0) & cost.ne(0) & (fv.abs() > 1000)
    if not valid.any():
        return 0
    ratio = (cost[valid] / fv[valid]).abs()
    return int(((ratio > 100) | (ratio < 0.01)).sum())


def _cost_fv_outlier_rows(
    holdings_df: pd.DataFrame | None,
    *,
    cik: str = TRINITY_CIK,
    report_date: str | None = None,
) -> pd.DataFrame:
    if (
        holdings_df is None
        or holdings_df.empty
        or "cost" not in holdings_df.columns
        or "fair_value" not in holdings_df.columns
    ):
        return pd.DataFrame()
    cik_norm = normalize_cik(cik)
    h = holdings_df.copy()
    if "cik" in h.columns:
        h["cik"] = h["cik"].map(normalize_cik)
        h = h[h["cik"].eq(cik_norm)].copy()
    else:
        h["cik"] = cik_norm
    if report_date is not None and "report_date" in h.columns:
        h = h[h["report_date"].astype(str).eq(str(report_date))].copy()
    if h.empty:
        return pd.DataFrame()
    h["_cost_num"] = pd.to_numeric(h["cost"], errors="coerce")
    h["_fv_num"] = pd.to_numeric(h["fair_value"], errors="coerce")
    valid = (
        h["_cost_num"].notna()
        & h["_fv_num"].notna()
        & h["_fv_num"].ne(0)
        & h["_cost_num"].ne(0)
        & (h["_fv_num"].abs() > 1000)
    )
    if not valid.any():
        return pd.DataFrame()
    h["_cost_fv_ratio_abs"] = (h["_cost_num"] / h["_fv_num"]).abs()
    return h[valid & ((h["_cost_fv_ratio_abs"] > 100) | (h["_cost_fv_ratio_abs"] < 0.01))].copy()


def _build_cost_fv_outlier_packets(
    holdings_df: pd.DataFrame | None,
    *,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    rows = _cost_fv_outlier_rows(holdings_df, cik=cik)
    if rows.empty:
        return pd.DataFrame(columns=AGENT_ISSUE_PACKET_COLUMNS)
    cik_norm = normalize_cik(cik)
    quarter_totals = _quarter_totals(holdings_df, cik=cik_norm)
    records: list[dict[str, Any]] = []
    for idx, row in rows.iterrows():
        report_date = str(row.get("report_date", "") or "")
        total_fv, total_rows = _totals_for_report(
            quarter_totals,
            cik=cik_norm,
            report_date=report_date,
        )
        materiality = _materiality_metrics(
            affected_fair_value=row.get("fair_value", 0),
            total_fair_value=total_fv,
            affected_rows=1,
            total_rows=total_rows,
        )
        ratio = _safe_float(row.get("_cost_fv_ratio_abs", 0))
        records.append({
            "issue_id": _packet_issue_id(
                cik=cik_norm,
                report_date=report_date,
                rule_id="WRAP.COST_FV_RATIO_OUTLIER",
                unique=f"{row.get('bdc_investment_identifier', '')}-{idx}",
            ),
            "rule_id": "WRAP.COST_FV_RATIO_OUTLIER",
            "source_rule_id": "cost_fv_ratio_outliers",
            "packet_type": "row",
            "severity": "review" if materiality["materiality_tier"] in {"P0", "P1"} else "warn",
            "materiality_tier": materiality["materiality_tier"],
            "likely_owner": "validation_rule",
            "review_status": "review",
            "cik": cik_norm,
            "entity_name": str(row.get("entity_name", "") or ""),
            "report_date": report_date,
            "accession_number": str(row.get("accession_number", "") or ""),
            "source_row_id": "",
            "output_row_id": "",
            "production_column": "cost|fair_value",
            "source_value": str(row.get("bdc_investment_identifier", "") or ""),
            "output_value": f"cost={row.get('cost', '')}; fair_value={row.get('fair_value', '')}; ratio={ratio:.6g}",
            **materiality,
            "evidence": "cost/fair-value ratio is outside 0.01x to 100x after excluding nominal FV positions",
            "recommended_action": (
                "Review whether this is a real position economics issue, filing scale issue, "
                "or wrapper parse error before changing output."
            ),
        })
    return pd.DataFrame(records, columns=AGENT_ISSUE_PACKET_COLUMNS)


# ---------------------------------------------------------------------------
# Gap #3: Concept/dimension drift detection
# ---------------------------------------------------------------------------


def _detect_concept_drift(detail_df: pd.DataFrame) -> dict[str, str]:
    """Detect significant XBRL concept churn between adjacent quarters (Gap #3).

    Computes churn_rate = |symmetric_difference| / |union| for adjacent quarters.
    Only flags "yes" when churn exceeds ``_CONCEPT_DRIFT_CHURN_THRESHOLD`` (30%).
    Normal BDC portfolio turnover (adding/removing a few positions) changes a small
    fraction of concepts; a structural taxonomy change affects many.

    Returns dict mapping report_date -> "yes"/"no".
    Only populated for the second quarter onward.
    """
    if detail_df.empty or "concept_names" not in detail_df.columns:
        return {}
    concepts_by_quarter: dict[str, set[str]] = {}
    for rd, grp in detail_df.groupby("report_date", dropna=False):
        concepts: set[str] = set()
        for val in grp["concept_names"].fillna("").astype(str):
            for c in val.split("|"):
                c = c.strip()
                if c:
                    concepts.add(c)
        if concepts:
            concepts_by_quarter[str(rd)] = concepts
    if len(concepts_by_quarter) < 2:
        return {}
    sorted_quarters = sorted(concepts_by_quarter.keys())
    result: dict[str, str] = {}
    for i in range(1, len(sorted_quarters)):
        prev = concepts_by_quarter[sorted_quarters[i - 1]]
        curr = concepts_by_quarter[sorted_quarters[i]]
        union = prev | curr
        if not union:
            result[sorted_quarters[i]] = "no"
            continue
        churn_rate = len(prev.symmetric_difference(curr)) / len(union)
        result[sorted_quarters[i]] = (
            "yes" if churn_rate >= _CONCEPT_DRIFT_CHURN_THRESHOLD else "no"
        )
    return result


def _detect_magnitude_shifts(
    detail_df: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """Detect per-field QoQ magnitude shifts (Gap #4 extension).

    For each field in ``_MAGNITUDE_SHIFT_FIELDS``, groups by ``report_date``,
    computes the median of ``abs(values)`` excluding nulls and zeros, and
    compares adjacent quarter medians.  Flags when the ratio is >=10x or
    <=0.1x (one order of magnitude).

    Returns ``{field_name: {report_date: shift_ratio}}`` where shift_ratio
    is ``current_median / prev_median``.  Only quarters where the shift
    exceeds the threshold are included.
    """
    if detail_df.empty:
        return {}
    result: dict[str, dict[str, float]] = {}
    for field in _MAGNITUDE_SHIFT_FIELDS:
        if field not in detail_df.columns:
            continue
        vals = detail_df[["report_date", field]].copy()
        vals[field] = pd.to_numeric(vals[field], errors="coerce")
        vals = vals[vals[field].notna() & vals[field].ne(0)].copy()
        vals[field] = vals[field].abs()
        if vals.empty:
            continue
        medians_by_quarter: dict[str, float] = {}
        for rd, grp in vals.groupby("report_date", dropna=False):
            if len(grp) < _MAGNITUDE_SHIFT_MIN_VALUES:
                continue
            medians_by_quarter[str(rd)] = float(grp[field].median())
        if len(medians_by_quarter) < 2:
            continue
        sorted_quarters = sorted(medians_by_quarter.keys())
        field_shifts: dict[str, float] = {}
        for i in range(1, len(sorted_quarters)):
            prev_median = medians_by_quarter[sorted_quarters[i - 1]]
            curr_median = medians_by_quarter[sorted_quarters[i]]
            if prev_median == 0:
                continue
            ratio = curr_median / prev_median
            if ratio >= _MAGNITUDE_SHIFT_RATIO_THRESHOLD or ratio <= (1.0 / _MAGNITUDE_SHIFT_RATIO_THRESHOLD):
                field_shifts[sorted_quarters[i]] = round(ratio, 4)
        if field_shifts:
            result[field] = field_shifts
    return result


def build_wrapper_oracle_outputs(
    detail_df: pd.DataFrame,
    *,
    cik: str = TRINITY_CIK,
    raw_bdc_position_keys: set[tuple[str, str, str, str]] | None = None,
    unified_position_keys: set[tuple[str, str, str, str]] | None = None,
    holdings_df: pd.DataFrame | None = None,
    fund_financials_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build oracle summary, cleared rollups, remaining blockers, and mechanism summary."""
    cik_norm = normalize_cik(cik)
    if detail_df.empty:
        empty_summary = pd.DataFrame(columns=ORACLE_SUMMARY_COLUMNS)
        return (
            empty_summary,
            pd.DataFrame(columns=DETAIL_COLUMNS),
            pd.DataFrame(columns=DETAIL_COLUMNS),
            pd.DataFrame(columns=REMAINING_MECHANISM_COLUMNS),
        )

    df = _ensure_detail_columns(detail_df)
    df = df[df["cik"].eq(cik_norm)].copy()
    if df.empty:
        empty_summary = pd.DataFrame(columns=ORACLE_SUMMARY_COLUMNS)
        return (
            empty_summary,
            pd.DataFrame(columns=DETAIL_COLUMNS),
            pd.DataFrame(columns=DETAIL_COLUMNS),
            pd.DataFrame(columns=REMAINING_MECHANISM_COLUMNS),
        )

    source_wrapper = df["source_wrapper_disposition"].fillna("").astype(str).ne("")
    output_wrapper = df["output_wrapper_disposition"].fillna("").astype(str).ne("")
    cleared = df[
        df["status"].astype(str).eq("documented_source_rollup_exact")
        & _is_rollup(df["source_wrapper_disposition"])
    ].copy()
    remaining = df[df["blocking_issue"]].copy()

    prefixes = supported_prefixes_for_cik(cik_norm)
    if prefixes:
        source_prefix = (
            df["source_row_id"].astype(str).ne("")
            & df["raw_investment_identifier"].fillna("").astype(str).str.startswith(prefixes)
        )
        output_prefix = (
            df["source_row_id"].astype(str).eq("")
            & df["output_row_id"].astype(str).ne("")
            & df["raw_investment_identifier"].fillna("").astype(str).str.startswith(prefixes)
        )
    else:
        source_prefix = pd.Series(False, index=df.index)
        output_prefix = pd.Series(False, index=df.index)
    unclassified_prefix = (
        (source_prefix & ~source_wrapper)
        | (output_prefix & ~output_wrapper)
        | df["source_wrapper_disposition"].astype(str).str.endswith("_unclassified")
        | df["output_wrapper_disposition"].astype(str).str.endswith("_unclassified")
    )
    signature_fail = (
        df["source_wrapper_signature_status"].astype(str).eq("fail")
        | df["output_wrapper_signature_status"].astype(str).eq("fail")
    )
    unparsed_remainder = (
        df["source_wrapper_unparsed_remainder"].fillna("").astype(str).str.strip().ne("")
        | df["output_wrapper_unparsed_remainder"].fillna("").astype(str).str.strip().ne("")
    )
    source_blocking_disposition = remaining["source_wrapper_disposition"].fillna("").astype(str)
    output_blocking_disposition = remaining["output_wrapper_disposition"].fillna("").astype(str)
    diagnostic_dispositions = {"aggregate", "non_private_market"}
    source_diagnostic = (
        source_blocking_disposition.isin(diagnostic_dispositions)
        | source_blocking_disposition.str.endswith("_rollup")
    )
    output_diagnostic = (
        output_blocking_disposition.isin(diagnostic_dispositions)
        | output_blocking_disposition.str.endswith("_rollup")
    )
    wrapper_blocking = remaining[
        (
            source_blocking_disposition.ne("")
            & ~source_diagnostic
        )
        | (
            output_blocking_disposition.ne("")
            & ~output_diagnostic
        )
    ]
    mechanisms = build_remaining_mechanism_summary(
        df,
        remaining,
        raw_bdc_position_keys=raw_bdc_position_keys,
        unified_position_keys=unified_position_keys,
    )
    mechanisms_by_report = {
        report_date: set(group["mechanism"].astype(str))
        for report_date, group in mechanisms.groupby("report_date", dropna=False)
    }

    # Content signature and FV reconciliation checks (v2 wrapper)
    cs_by_report = _check_content_signatures(
        cik_norm,
        holdings_df if holdings_df is not None else pd.DataFrame(),
    )
    fv_by_report = _check_fv_reconciliation(
        cik_norm,
        holdings_df if holdings_df is not None else pd.DataFrame(),
        fund_financials_df,
    )

    # Structural check: wrapper definition exists but has no archetypes
    wrapper_def = load_wrapper_definition(cik_norm)
    wrapper_json_exists = (OVERRIDES_DIR / "bdc_xbrl_wrappers" / f"{cik_norm}.json").exists()
    has_wrapper_definition = wrapper_def is not None or wrapper_json_exists
    wrapper_no_archetypes = (
        wrapper_def is not None and len(wrapper_def.archetypes) == 0
    )

    # Gap 3: Concept drift detection (cross-quarter)
    concept_drift_by_quarter = _detect_concept_drift(df)

    # Gap 8: Position continuity (cross-quarter)
    continuity_by_quarter = _compute_position_continuity(df)

    # Gap 4 extension: per-field magnitude shift detection (cross-quarter)
    magnitude_shifts = _detect_magnitude_shifts(df)

    rows: list[dict[str, Any]] = []
    for report_date, group in df.groupby("report_date", dropna=False):
        group_index = group.index
        reasons: list[str] = []
        signature_fail_rows = int(signature_fail.loc[group_index].sum())
        unclassified_rows = int(unclassified_prefix.loc[group_index].sum())
        unparsed_rows = int(unparsed_remainder.loc[group_index].sum())
        wrapper_blocking_rows = int(wrapper_blocking[wrapper_blocking["report_date"].eq(report_date)].shape[0])
        if signature_fail_rows:
            reasons.append("content_signatures_fail")
        if unclassified_rows:
            reasons.append("unclassified_prefix_rows")
        if unparsed_rows:
            reasons.append("unparsed_remainder_rows")
        if wrapper_blocking_rows:
            reasons.append("wrapper_blockers_remaining")
        for mechanism in sorted(mechanisms_by_report.get(report_date, set())):
            if mechanism not in {"cash_or_money_market", "aggregate", "non_private_market"}:
                reasons.append(f"remaining_{mechanism}")
        has_wrapper_rows = bool(
            source_wrapper.loc[group_index].any()
            or output_wrapper.loc[group_index].any()
            or unclassified_prefix.loc[group_index].any()
        )
        if not has_wrapper_rows:
            reasons.append("no_wrapper_rows" if has_wrapper_definition else "unsupported_wrapper_cik")

        # Coverage gate: no-archetype structural check
        if wrapper_no_archetypes:
            reasons.append("wrapper_no_archetypes")

        # Coverage gates from content signature results
        cs_data = cs_by_report.get(str(report_date), {})
        cs_unclass_rate = cs_data.get("unclassified_rate", 0.0)
        cs_unclass_rate_status = cs_data.get("unclassified_rate_status", "")
        cs_unclass_fv_rate = cs_data.get("unclassified_fv_rate", 0.0)
        cs_unclass_fv_status = cs_data.get("unclassified_fv_rate_status", "")
        if cs_unclass_rate_status == "fail":
            reasons.append("unclassified_rate_exceeded")
        if cs_unclass_fv_status == "fail":
            reasons.append("unclassified_fv_rate_exceeded")

        # Gap 7: Exclusion false-positive risk
        exclusion_count, exclusion_fv = _check_exclusion_risk(group)
        if exclusion_count > 0:
            reasons.append("exclusion_risk_detected")

        # Gap 4: Rate and scale outliers
        rate_outlier_count = _check_rate_outliers(
            holdings_df, wrapper_def, str(report_date)
        )
        if rate_outlier_count > 0:
            reasons.append("rate_outliers_detected")
        cost_fv_outlier_count = _check_cost_fv_outliers(
            holdings_df, str(report_date)
        )

        # Gap 4 extension: per-field magnitude shifts
        rd_str = str(report_date)
        fv_mag_shift = magnitude_shifts.get("source_fair_value", {}).get(rd_str, "")
        rate_mag_shift = magnitude_shifts.get("source_interest_rate", {}).get(rd_str, "")
        cost_mag_shift = magnitude_shifts.get("source_cost", {}).get(rd_str, "")
        spread_mag_shift = magnitude_shifts.get("source_basis_spread", {}).get(rd_str, "")
        if fv_mag_shift:
            reasons.append("fv_magnitude_shift_detected")
        if rate_mag_shift:
            reasons.append("rate_magnitude_shift_detected")
        if cost_mag_shift:
            reasons.append("cost_magnitude_shift_detected")
        if spread_mag_shift:
            reasons.append("spread_magnitude_shift_detected")

        # Gap 3: Concept drift
        concept_drift = concept_drift_by_quarter.get(str(report_date), "")
        if concept_drift == "yes":
            reasons.append("concept_drift_detected")

        # Gap 8: Position continuity
        pos_cont_rate = continuity_by_quarter.get(str(report_date), "")
        if isinstance(pos_cont_rate, float) and pos_cont_rate < _POSITION_CONTINUITY_MIN_RATE:
            reasons.append("low_position_continuity")

        # Gap 5: Unparsed remainder rate
        wrapper_total_rows = int(source_wrapper.loc[group_index].sum())
        unparsed_rate = unparsed_rows / wrapper_total_rows if wrapper_total_rows > 0 else 0.0

        cleared_group = cleared[cleared["report_date"].eq(report_date)]
        remaining_group = remaining[remaining["report_date"].eq(report_date)]
        rows.append({
            "cik": cik_norm,
            "entity_name": str(group["entity_name"].dropna().astype(str).iloc[0]) if not group.empty else "",
            "report_date": str(report_date),
            "wrapper_source_rows": int(source_wrapper.loc[group_index].sum()),
            "wrapper_output_rows": int(output_wrapper.loc[group_index].sum()),
            "wrapper_rollup_candidates": int(
                _is_rollup(group["source_wrapper_disposition"]).sum()
            ),
            "wrapper_leaf_outputs": int(
                _is_leaf(group["output_wrapper_disposition"]).sum()
            ),
            "wrapper_leaf_source_rows": int(
                _is_leaf(group["source_wrapper_disposition"]).sum()
            ),
            "cleared_rollup_rows": len(cleared_group),
            "cleared_rollup_fair_value": float(cleared_group["source_fair_value"].fillna(0).sum()),
            "remaining_blocking_rows": len(remaining_group),
            "remaining_blocking_fair_value": float(remaining_group["source_fair_value"].fillna(0).sum()),
            "remaining_wrapper_blocking_rows": wrapper_blocking_rows,
            "signature_fail_rows": signature_fail_rows,
            "unclassified_prefix_rows": unclassified_rows,
            "unparsed_remainder_rows": unparsed_rows,
            "content_signature_pass_rate": cs_data.get("pass_rate", ""),
            "content_signature_violations": cs_data.get("violation_count", ""),
            "unclassified_rate": cs_unclass_rate if cs_data else "",
            "unclassified_rate_status": cs_unclass_rate_status,
            "unclassified_fv_rate": cs_unclass_fv_rate if cs_data else "",
            "unclassified_fv_rate_status": cs_unclass_fv_status,
            "fv_reconciliation_status": fv_by_report.get(str(report_date), {}).get("status", ""),
            "fv_reconciliation_pct_diff": fv_by_report.get(str(report_date), {}).get("pct_diff", ""),
            "exclusion_risk_count": exclusion_count,
            "exclusion_risk_fv": round(exclusion_fv, 2) if exclusion_fv else 0,
            "position_continuation_rate": pos_cont_rate,
            "rate_outlier_count": rate_outlier_count,
            "cost_fv_ratio_outlier_count": cost_fv_outlier_count,
            "parsed_field_quality_issue_count": 0,
            "parsed_field_quality_fair_value": 0,
            "fv_magnitude_shift": fv_mag_shift,
            "rate_magnitude_shift": rate_mag_shift,
            "concept_drift_flag": concept_drift,
            "unparsed_remainder_rate": round(unparsed_rate, 6) if wrapper_total_rows > 0 else "",
            "oracle_status": (
                "not_applicable"
                if not has_wrapper_rows
                else ("pass" if not reasons else "fail")
            ),
            "oracle_fail_reasons": "|".join(reasons),
        })

    # Sort chronologically for QoQ checks
    if len(rows) > 1:
        rows.sort(key=lambda r: r["report_date"])

    # QoQ unclassified rate jump detection (post-processing)
    if len(rows) > 1 and cs_by_report:
        for i in range(1, len(rows)):
            prev_rate = rows[i - 1].get("unclassified_rate", 0.0)
            curr_rate = rows[i].get("unclassified_rate", 0.0)
            try:
                prev_rate = float(prev_rate) if prev_rate != "" else 0.0
                curr_rate = float(curr_rate) if curr_rate != "" else 0.0
            except (ValueError, TypeError):
                continue
            jump = curr_rate - prev_rate
            if jump > _UNCLASSIFIED_RATE_QOQ_JUMP_THRESHOLD:
                existing_reasons = rows[i]["oracle_fail_reasons"]
                new_reason = "unclassified_rate_qoq_jump"
                if existing_reasons:
                    rows[i]["oracle_fail_reasons"] = existing_reasons + "|" + new_reason
                else:
                    rows[i]["oracle_fail_reasons"] = new_reason
                if rows[i]["oracle_status"] == "pass":
                    rows[i]["oracle_status"] = "fail"

    # QoQ unparsed remainder rate spike detection (Gap #5)
    if len(rows) > 1:
        for i in range(1, len(rows)):
            prev_rate = _safe_float(rows[i - 1].get("unparsed_remainder_rate", 0))
            curr_rate = _safe_float(rows[i].get("unparsed_remainder_rate", 0))
            spike = curr_rate - prev_rate
            if spike > _UNPARSED_REMAINDER_QOQ_SPIKE_THRESHOLD:
                existing_reasons = rows[i]["oracle_fail_reasons"]
                new_reason = "unparsed_remainder_spike"
                if existing_reasons:
                    rows[i]["oracle_fail_reasons"] = (
                        existing_reasons + "|" + new_reason
                    )
                else:
                    rows[i]["oracle_fail_reasons"] = new_reason
                if rows[i]["oracle_status"] == "pass":
                    rows[i]["oracle_status"] = "fail"

    summary = pd.DataFrame(rows, columns=ORACLE_SUMMARY_COLUMNS)
    return summary, cleared[DETAIL_COLUMNS], remaining[DETAIL_COLUMNS], mechanisms


def build_baseline_comparison(
    current_detail: pd.DataFrame,
    baseline_detail: pd.DataFrame,
    *,
    cik: str = TRINITY_CIK,
) -> pd.DataFrame:
    current = _ensure_detail_columns(current_detail)
    baseline = _ensure_detail_columns(baseline_detail)
    cik_norm = normalize_cik(cik)
    current = current[current["cik"].eq(cik_norm)].copy()
    baseline = baseline[baseline["cik"].eq(cik_norm)].copy()

    def summarize(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["cik", "report_date"])
        blocking = df[df["blocking_issue"]].copy()
        cleared = df[
            df["status"].astype(str).eq("documented_source_rollup_exact")
            & _is_rollup(df["source_wrapper_disposition"])
        ].copy()
        blocking_summary = blocking.groupby(["cik", "report_date"], dropna=False).agg(
            **{
                f"{prefix}_blocking_rows": ("status", "size"),
                f"{prefix}_blocking_fair_value": ("source_fair_value", "sum"),
            }
        ).reset_index()
        cleared_summary = cleared.groupby(["cik", "report_date"], dropna=False).agg(
            **{
                f"{prefix}_documented_source_rollup_exact_rows": ("status", "size"),
                f"{prefix}_cleared_rollup_fair_value": ("source_fair_value", "sum"),
            }
        ).reset_index()
        quarters = df[["cik", "report_date"]].drop_duplicates()
        return (
            quarters.merge(blocking_summary, on=["cik", "report_date"], how="left")
            .merge(cleared_summary, on=["cik", "report_date"], how="left")
            .fillna(0)
        )

    current_summary = summarize(current, "current")
    baseline_summary = summarize(baseline, "baseline")
    combined = current_summary.merge(baseline_summary, on=["cik", "report_date"], how="outer").fillna(0)
    for col in [
        "current_blocking_rows",
        "baseline_blocking_rows",
        "current_documented_source_rollup_exact_rows",
        "baseline_documented_source_rollup_exact_rows",
    ]:
        combined[col] = combined.get(col, 0).astype(int)
    combined["blocking_rows_delta"] = combined["current_blocking_rows"] - combined["baseline_blocking_rows"]
    combined["documented_rollup_delta"] = (
        combined["current_documented_source_rollup_exact_rows"]
        - combined["baseline_documented_source_rollup_exact_rows"]
    )
    combined["blocking_fair_value_delta"] = combined["current_blocking_fair_value"] - combined["baseline_blocking_fair_value"]
    combined["cleared_rollup_fair_value_delta"] = (
        combined["current_cleared_rollup_fair_value"]
        - combined["baseline_cleared_rollup_fair_value"]
    )
    return combined[BASELINE_COMPARISON_COLUMNS].sort_values(["cik", "report_date"]).reset_index(drop=True)


def _load_cached_source_facts_for_cik(cik: str) -> pd.DataFrame:
    cik_norm = normalize_cik(cik)
    if not BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE.exists():
        logger.warning("Source facts manifest not found: %s", BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE)
        return pd.DataFrame(columns=SOURCE_FACT_COLUMNS)
    manifest = pd.read_csv(BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE, dtype=str)
    if manifest.empty:
        return pd.DataFrame(columns=SOURCE_FACT_COLUMNS)
    manifest["cik_norm"] = manifest["cik"].map(normalize_cik)
    paths = [
        Path(path)
        for path in manifest.loc[manifest["cik_norm"].eq(cik_norm), "artifact_path"].fillna("").astype(str)
        if path
    ]
    return _read_parquet_glob(paths, SOURCE_FACT_COLUMNS)


def _load_fresh_bdc_staged_holdings_for_cik(cik: str) -> pd.DataFrame:
    """Rebuild one CIK's BDC rows through current staging rules."""
    cik_norm = normalize_cik(cik)
    if not BDC_HOLDINGS_FILE.exists():
        raise FileNotFoundError(f"BDC holdings file not found: {BDC_HOLDINGS_FILE}")
    raw_df = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
    if "cik" not in raw_df.columns:
        return pd.DataFrame()
    raw_df = raw_df[raw_df["cik"].map(normalize_cik).eq(cik_norm)].copy()
    if raw_df.empty:
        return pd.DataFrame()
    from pipeline.staging_bdc import _prepare_bdc

    staged = _prepare_bdc(raw_df)
    if not staged.empty and "cik" in staged.columns:
        staged = staged[staged["cik"].map(normalize_cik).eq(cik_norm)].copy()
    return staged


def _load_current_production_bdc_holdings_for_cik(cik: str) -> pd.DataFrame:
    """Load current production BDC holdings for one CIK, if available."""
    cik_norm = normalize_cik(cik)
    if not UNIFIED_HOLDINGS_FILE.exists():
        return pd.DataFrame()
    unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    return unified_df[
        unified_df.get("cik", pd.Series(dtype=str)).map(normalize_cik).eq(cik_norm)
        & unified_df.get("source", pd.Series(dtype=str)).astype(str).str.lower().eq("bdc")
    ].copy()


def run_wrapper_oracle_trial(
    *,
    cik: str = TRINITY_CIK,
    output_dir: Path | None = None,
    compare_baseline: bool = False,
    fresh_bdc_staging: bool = False,
    holdings_file: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    """Run the wrapper oracle for one CIK and write trial artifacts.

    Parameters
    ----------
    holdings_file : Path, optional
        Read holdings from this CSV instead of the canonical
        ``UNIFIED_HOLDINGS_FILE``.  Mutually exclusive with
        *fresh_bdc_staging*.  Intended for one-CIK trial rebuilds.
    """
    if fresh_bdc_staging and holdings_file is not None:
        raise ValueError("--fresh-bdc-staging and --holdings-file are mutually exclusive")
    cik_norm = normalize_cik(cik)
    out_dir = output_dir or (OUTPUT_DIR / "bdc_xbrl_wrapper_trial" / cik_norm)

    # Fail fast on wrapper JSON coherence issues
    wrapper_path = OVERRIDES_DIR / "bdc_xbrl_wrappers" / f"{cik_norm}.json"
    if wrapper_path.exists():
        with open(wrapper_path, encoding="utf-8") as _wf:
            _raw_wrapper = json_mod.load(_wf)
        coherence_issues = validate_wrapper_json_coherence(_raw_wrapper)
        if coherence_issues:
            for issue in coherence_issues:
                logger.warning("Wrapper coherence: %s", issue)

    source_df = _load_cached_source_facts_for_cik(cik_norm)
    if fresh_bdc_staging:
        holdings_df = _load_fresh_bdc_staged_holdings_for_cik(cik_norm)
    elif holdings_file is not None:
        if not holdings_file.exists():
            raise FileNotFoundError(f"Holdings file not found: {holdings_file}")
        unified_df = pd.read_csv(holdings_file, dtype=str)
        holdings_df = unified_df[
            unified_df.get("cik", pd.Series(dtype=str)).map(normalize_cik).eq(cik_norm)
            & unified_df.get("source", pd.Series(dtype=str)).astype(str).str.lower().eq("bdc")
        ].copy()
    else:
        if not UNIFIED_HOLDINGS_FILE.exists():
            raise FileNotFoundError(f"Unified holdings file not found: {UNIFIED_HOLDINGS_FILE}")
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
        holdings_df = unified_df[
            unified_df.get("cik", pd.Series(dtype=str)).map(normalize_cik).eq(cik_norm)
            & unified_df.get("source", pd.Series(dtype=str)).astype(str).str.lower().eq("bdc")
        ].copy()
    production_holdings_df = _load_current_production_bdc_holdings_for_cik(cik_norm)
    raw_bdc_position_keys: set[tuple[str, str, str, str]] = set()
    if BDC_HOLDINGS_FILE.exists():
        bdc_raw = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        bdc_raw = bdc_raw[bdc_raw.get("cik", pd.Series(dtype=str)).map(normalize_cik).eq(cik_norm)].copy()
        raw_bdc_position_keys = _wrapper_position_keys(bdc_raw, identifier_col="investment_identifier")
    unified_position_keys = _wrapper_position_keys(
        holdings_df,
        identifier_col="bdc_investment_identifier" if "bdc_investment_identifier" in holdings_df.columns else "investment_identifier",
    )
    detail, _metrics = reconcile_bdc_source_to_holdings(source_df, holdings_df)

    # Load fund financials for v2 FV reconciliation (best-effort)
    from pipeline.config import FUND_FINANCIALS_FILE
    trial_fund_financials = None
    if FUND_FINANCIALS_FILE.exists():
        try:
            trial_fund_financials = pd.read_csv(FUND_FINANCIALS_FILE, dtype=str)
        except Exception:
            pass

    summary, cleared, remaining, mechanisms = build_wrapper_oracle_outputs(
        detail,
        cik=cik_norm,
        raw_bdc_position_keys=raw_bdc_position_keys,
        unified_position_keys=unified_position_keys,
        holdings_df=holdings_df,
        fund_financials_df=trial_fund_financials,
    )
    parsed_field_quality = _build_parsed_field_quality_packets(
        detail,
        holdings_df,
        cik=cik_norm,
    )
    source_verbose_identifiers = _build_source_verbose_identifier_packets(
        detail,
        holdings_df,
        parsed_field_quality=parsed_field_quality,
        cik=cik_norm,
    )
    cost_fv_outliers = _build_cost_fv_outlier_packets(
        holdings_df,
        cik=cik_norm,
    )
    column_validation_issues, _column_validation_metrics = validate_column_contracts(
        holdings_df if holdings_df is not None else pd.DataFrame()
    )
    row_delta_attribution = _build_row_delta_attribution(
        holdings_df,
        production_holdings_df,
        cik=cik_norm,
    )
    high_fv_unclassified_clusters = _build_high_fv_unclassified_clusters(
        holdings_df,
        load_wrapper_definition(cik_norm),
        cik=cik_norm,
    )
    column_drift_summary, column_drift_examples = _build_column_drift_packets(
        holdings_df,
        cik=cik_norm,
    )
    agent_issue_packets = _build_agent_issue_packets(
        parsed_field_quality=parsed_field_quality,
        source_verbose_identifiers=source_verbose_identifiers,
        cost_fv_outliers=cost_fv_outliers,
        column_validation_issues=column_validation_issues,
        holdings_df=holdings_df,
        cik=cik_norm,
    )
    agent_cluster_packets = _build_agent_cluster_packets(
        row_delta_attribution=row_delta_attribution,
        high_fv_unclassified_clusters=high_fv_unclassified_clusters,
        column_drift_summary=column_drift_summary,
        oracle_summary=summary,
        holdings_df=holdings_df,
        cik=cik_norm,
    )
    summary = _append_parsed_field_quality_summary(summary, parsed_field_quality)
    baseline_comparison = None
    if compare_baseline:
        baseline_detail, _baseline_metrics = reconcile_bdc_source_to_holdings(
            source_df,
            holdings_df,
            enable_bdc_xbrl_wrappers=False,
        )
        baseline_comparison = build_baseline_comparison(detail, baseline_detail, cik=cik_norm)

    out_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(out_dir / "reconciliation_detail.csv", index=False)
    parsed_field_quality.to_csv(out_dir / "parsed_field_quality.csv", index=False)
    source_verbose_identifiers.to_csv(out_dir / "source_verbose_identifiers.csv", index=False)
    source_verbose_identifiers.to_csv(out_dir / "source_corrupted_identifiers.csv", index=False)
    cost_fv_outliers.to_csv(out_dir / "cost_fv_ratio_outliers.csv", index=False)
    column_validation_issues.to_csv(out_dir / "column_validation_issues.csv", index=False)
    row_delta_attribution.to_csv(out_dir / "row_delta_attribution.csv", index=False)
    high_fv_unclassified_clusters.to_csv(
        out_dir / "high_fv_unclassified_clusters.csv",
        index=False,
    )
    column_drift_summary.to_csv(out_dir / "column_drift_summary.csv", index=False)
    column_drift_examples.to_csv(out_dir / "column_drift_examples.csv", index=False)
    agent_issue_packets.to_csv(out_dir / "agent_issue_packets.csv", index=False)
    _write_jsonl_from_df(agent_issue_packets, out_dir / "agent_issue_packets.jsonl")
    agent_cluster_packets.to_csv(out_dir / "agent_cluster_packets.csv", index=False)
    _write_jsonl_from_df(agent_cluster_packets, out_dir / "agent_cluster_packets.jsonl")
    try:
        agent_verdict_summary = _load_agent_verdict_summary(out_dir)
    except ValueError as exc:
        agent_verdict_summary = pd.DataFrame([{
            "verdict": "malformed_agent_verdicts",
            "likely_owner": "unknown",
            "materiality_tier": "P0",
            "issue_count": 1,
            "affected_fair_value": 0.0,
            "max_confidence": 0.0,
            "promotion_effect": "reject",
        }], columns=AGENT_VERDICT_SUMMARY_COLUMNS)
        logger.error("Agent verdict validation failed: %s", exc)
    agent_verdict_summary.to_csv(out_dir / "agent_verdict_summary.csv", index=False)
    summary.to_csv(out_dir / "oracle_summary.csv", index=False)
    cleared.to_csv(out_dir / "cleared_rollups.csv", index=False)
    remaining.to_csv(out_dir / "remaining_blockers.csv", index=False)
    mechanisms.to_csv(out_dir / "remaining_blocker_mechanisms.csv", index=False)
    if baseline_comparison is not None:
        baseline_comparison.to_csv(out_dir / "baseline_comparison.csv", index=False)
    return detail, summary, cleared, remaining, baseline_comparison


def run_wrapper_queue(
    *,
    residual_clusters_file: Path = SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE,
    output_dir: Path | None = None,
    top: int = 25,
    compare_baseline: bool = False,
    fresh_bdc_staging: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Profile top blocker CIKs and run trials only for supported wrappers."""
    out_dir = output_dir or (OUTPUT_DIR / "bdc_xbrl_wrapper_queue")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not residual_clusters_file.exists():
        raise FileNotFoundError(f"Residual clusters file not found: {residual_clusters_file}")
    clusters = pd.read_csv(residual_clusters_file, dtype=str)
    queue = build_residual_wrapper_queue(clusters, top=top)
    queue.to_csv(out_dir / "queue.csv", index=False)

    summary_rows: list[dict[str, Any]] = []
    for _, queue_row in queue.iterrows():
        cik = normalize_cik(queue_row["cik"])
        cik_dir = out_dir / cik
        cik_dir.mkdir(parents=True, exist_ok=True)
        profile, candidates = build_wrapper_profile_for_cik(clusters, cik)
        profile.to_csv(cik_dir / "profile.csv", index=False)
        candidates.to_csv(cik_dir / "candidate_rules.csv", index=False)

        oracle_summary_rows = 0
        oracle_remaining = 0
        status = "profiled"
        if bool(queue_row["supported_wrapper"]):
            trial_dir = cik_dir / "oracle"
            _detail, oracle_summary, _cleared, remaining, _baseline = run_wrapper_oracle_trial(
                cik=cik,
                output_dir=trial_dir,
                compare_baseline=compare_baseline,
                fresh_bdc_staging=fresh_bdc_staging,
            )
            oracle_summary_rows = len(oracle_summary)
            oracle_remaining = len(remaining)
            status = "oracle_ran"

        summary_rows.append({
            "cik": cik,
            "entity_name": queue_row["entity_name"],
            "supported_wrapper": bool(queue_row["supported_wrapper"]),
            "blocking_rows": int(queue_row["blocking_rows"]),
            "profile_rows": len(profile),
            "candidate_rule_rows": len(candidates),
            "oracle_summary_rows": oracle_summary_rows,
            "oracle_remaining_blocking_rows": oracle_remaining,
            "status": status,
        })
    summary = pd.DataFrame(summary_rows, columns=QUEUE_SUMMARY_COLUMNS)
    summary.to_csv(out_dir / "summary.csv", index=False)
    return queue, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a CIK-scoped BDC XBRL wrapper oracle trial.")
    parser.add_argument("--cik", default=TRINITY_CIK)
    parser.add_argument("--all-supported", action="store_true")
    parser.add_argument("--queue-from-residuals", action="store_true")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument(
        "--residual-clusters-file",
        type=Path,
        default=SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE,
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--compare-baseline", action="store_true")
    parser.add_argument(
        "--fresh-bdc-staging",
        action="store_true",
        help="Rebuild only the requested CIK's BDC rows through current staging before reconciling.",
    )
    parser.add_argument(
        "--holdings-file",
        type=Path,
        default=None,
        help="Read holdings from this CSV instead of canonical private_markets_holdings.csv. "
             "Mutually exclusive with --fresh-bdc-staging. Use with trial rebuild output.",
    )
    parser.add_argument("--fail-on-oracle-fail", action="store_true")
    parser.add_argument(
        "--promotion-gate",
        action="store_true",
        help="Run full promotion gate: oracle trial + baseline comparison + structural validation + verdict.",
    )
    parser.add_argument(
        "--oracle-v2",
        action="store_true",
        help="Run comprehensive oracle v2 checks (arithmetic, structural, content, etc.).",
    )
    parser.add_argument(
        "--oracle-v2-checks",
        default=None,
        help="Comma-separated oracle v2 check IDs (e.g. A01,A04,F01).",
    )
    parser.add_argument(
        "--oracle-v2-category",
        default=None,
        help="Run all oracle v2 checks in one category (e.g. A, B, F).",
    )
    args = parser.parse_args(argv)

    if args.fresh_bdc_staging and args.holdings_file is not None:
        parser.error("--fresh-bdc-staging and --holdings-file are mutually exclusive")
    if args.all_supported and args.holdings_file is not None:
        parser.error("--all-supported and --holdings-file are mutually exclusive")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Oracle v2: comprehensive arithmetic/structural/content checks
    if args.oracle_v2:
        from pipeline.oracle_runner import run_oracle
        checks = args.oracle_v2_checks.split(",") if args.oracle_v2_checks else None
        cik_arg = None if args.all_supported else normalize_cik(args.cik)
        report = run_oracle(
            cik=cik_arg,
            checks=checks,
            category=args.oracle_v2_category,
            output_dir=args.output_dir,
        )
        print(report.summary_text())
        if args.fail_on_oracle_fail and report.fail_count > 0:
            return 1
        return 0

    if args.promotion_gate:
        ciks = (
            supported_wrapper_ciks()
            if args.all_supported
            else (normalize_cik(args.cik),)
        )
        any_failing = False
        for cik_val in ciks:
            out = args.output_dir
            if out is not None and args.all_supported:
                out = out / cik_val
            verdict = run_promotion_trial(
                cik=cik_val,
                output_dir=out,
                fresh_bdc_staging=args.fresh_bdc_staging,
                holdings_file=args.holdings_file,
            )
            print(f"cik={cik_val}")
            print(f"promotion_status={verdict.status}")
            print(f"blocking_rows_delta={verdict.blocking_rows_delta}")
            print(f"blocking_fv_delta={verdict.blocking_fv_delta:.0f}")
            if verdict.reasons:
                print(f"reasons={'; '.join(verdict.reasons)}")
            if verdict.improvements:
                print(f"improvements={'; '.join(verdict.improvements)}")
            if verdict.status == "reject":
                any_failing = True
        if args.fail_on_oracle_fail and any_failing:
            return 1
        return 0

    if args.queue_from_residuals:
        queue, summary = run_wrapper_queue(
            residual_clusters_file=args.residual_clusters_file,
            output_dir=args.output_dir,
            top=args.top,
            compare_baseline=args.compare_baseline,
            fresh_bdc_staging=args.fresh_bdc_staging,
        )
        print(f"queue_rows={len(queue)}")
        print(f"queue_summary_rows={len(summary)}")
        if not summary.empty:
            print("queue_status_counts=" + str(summary["status"].value_counts().to_dict()))
        return 0

    ciks = supported_wrapper_ciks() if args.all_supported else (normalize_cik(args.cik),)
    any_failing = False
    for cik in ciks:
        output_dir = args.output_dir
        if output_dir is not None and args.all_supported:
            output_dir = output_dir / cik
        _detail, summary, cleared, remaining, baseline_comparison = run_wrapper_oracle_trial(
            cik=cik,
            output_dir=output_dir,
            compare_baseline=args.compare_baseline,
            fresh_bdc_staging=args.fresh_bdc_staging,
            holdings_file=args.holdings_file,
        )
        print(f"cik={cik}")
        print(f"oracle_summary_rows={len(summary)}")
        print(f"cleared_rollup_rows={len(cleared)}")
        print(f"remaining_blocking_rows={len(remaining)}")
        if not summary.empty:
            print("oracle_status_counts=" + str(summary["oracle_status"].value_counts().to_dict()))
        if baseline_comparison is not None:
            print(f"baseline_comparison_rows={len(baseline_comparison)}")
        failing = summary["oracle_status"].astype(str).eq("fail") if not summary.empty else pd.Series([True])
        any_failing = any_failing or bool(failing.any())
    if args.fail_on_oracle_fail and any_failing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
