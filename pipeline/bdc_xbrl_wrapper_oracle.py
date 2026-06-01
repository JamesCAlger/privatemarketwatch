"""CIK-scoped oracle harness for BDC XBRL wrapper trials."""

from __future__ import annotations

import argparse
import json as json_mod
import logging
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
    load_wrapper_definition,
    validate_content_signatures,
    validate_fv_reconciliation,
)
from pipeline.config import (
    BDC_HOLDINGS_FILE,
    BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE,
    OUTPUT_DIR,
    SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE,
    UNIFIED_HOLDINGS_FILE,
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


def evaluate_promotion_gate(
    current_summary: pd.DataFrame,
    baseline_comparison: pd.DataFrame | None = None,
) -> PromotionVerdict:
    """Evaluate whether a wrapper change should be promoted.

    Checks absolute oracle thresholds from ``current_summary`` and relative
    improvements from ``baseline_comparison`` (before/after blocking metrics
    produced by ``build_baseline_comparison``).

    Returns a ``PromotionVerdict`` with status ``"promote"``, ``"reject"``,
    or ``"review_required"``.
    """
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
        fail_reasons = str(row.get("oracle_fail_reasons", ""))
        rd = str(row.get("report_date", ""))

        if status == "fail":
            reasons_set = set(fail_reasons.split("|")) if fail_reasons else set()
            for reason in sorted(reasons_set & _PROMOTION_REJECT_REASONS):
                reject_reasons.append(f"{rd}: {reason}")
            for reason in sorted(reasons_set & _PROMOTION_REVIEW_REASONS):
                review_reasons.append(f"{rd}: {reason}")
            # Remaining mechanism reasons (not diagnostic)
            for reason in sorted(reasons_set):
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

    # --- Build per-quarter comparison ---
    per_quarter_rows = []
    for _, row in current_summary.iterrows():
        rd = str(row.get("report_date", ""))
        cik_val = str(row.get("cik", ""))
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
        if str(row.get("oracle_status", "")) == "fail":
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


def run_promotion_trial(
    *,
    cik: str = TRINITY_CIK,
    output_dir: Path | None = None,
    fresh_bdc_staging: bool = False,
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
    )

    # Structural validation
    wrapper = load_wrapper_definition(cik_norm)
    structural_issues = (
        validate_wrapper_definition_structure(wrapper)
        if wrapper is not None
        else ["no_wrapper_definition"]
    )

    verdict = evaluate_promotion_gate(summary, baseline)

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
    valid = cost.notna() & fv.notna() & fv.ne(0) & cost.ne(0)
    if not valid.any():
        return 0
    ratio = (cost[valid] / fv[valid]).abs()
    return int(((ratio > 100) | (ratio < 0.01)).sum())


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
        concepts = set(
            grp["concept_names"].fillna("").astype(str).str.strip()
        ) - {""}
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
    wrapper_blocking = remaining[
        remaining["source_wrapper_disposition"].fillna("").astype(str).ne("")
        | remaining["output_wrapper_disposition"].fillna("").astype(str).ne("")
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
    wrapper_no_archetypes = (
        wrapper_def is not None and len(wrapper_def.archetypes) == 0
    )

    # Gap 3: Concept drift detection (cross-quarter)
    concept_drift_by_quarter = _detect_concept_drift(df)

    # Gap 8: Position continuity (cross-quarter)
    continuity_by_quarter = _compute_position_continuity(df)

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
            reasons.append("unsupported_wrapper_cik" if not prefixes else "no_wrapper_rows")

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
        if cost_fv_outlier_count > 0:
            reasons.append("cost_fv_ratio_outliers")

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


def run_wrapper_oracle_trial(
    *,
    cik: str = TRINITY_CIK,
    output_dir: Path | None = None,
    compare_baseline: bool = False,
    fresh_bdc_staging: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    """Run the wrapper oracle for one CIK and write trial artifacts."""
    cik_norm = normalize_cik(cik)
    out_dir = output_dir or (OUTPUT_DIR / "bdc_xbrl_wrapper_trial" / cik_norm)
    if not UNIFIED_HOLDINGS_FILE.exists():
        raise FileNotFoundError(f"Unified holdings file not found: {UNIFIED_HOLDINGS_FILE}")

    source_df = _load_cached_source_facts_for_cik(cik_norm)
    if fresh_bdc_staging:
        holdings_df = _load_fresh_bdc_staged_holdings_for_cik(cik_norm)
    else:
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
        holdings_df = unified_df[
            unified_df.get("cik", pd.Series(dtype=str)).map(normalize_cik).eq(cik_norm)
            & unified_df.get("source", pd.Series(dtype=str)).astype(str).str.lower().eq("bdc")
        ].copy()
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
