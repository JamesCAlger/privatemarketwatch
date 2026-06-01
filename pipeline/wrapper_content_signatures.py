"""Content signature engine for BDC XBRL wrapper definitions.

Loads per-CIK wrapper definitions (v2 or v3 schema), classifies holdings rows
into archetypes, validates field-level content signatures, and runs fund-level
FV reconciliation and QoQ drift detection.

This module is a diagnostic layer: it does not mutate holdings data.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.bdc_xbrl_wrapper import normalize_cik
from pipeline.config import (
    BDC_HOLDINGS_FILE,
    FUND_FINANCIALS_FILE,
    OUTPUT_DIR,
    OVERRIDES_DIR,
)

logger = logging.getLogger(__name__)

WRAPPER_DEFINITIONS_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSignature:
    """One field-level check within an archetype."""
    field_name: str
    sig_type: str  # numeric_range, regex, enum, presence
    constraint: str  # required, forbidden, optional
    min_val: float | None = None
    max_val: float | None = None
    pattern: str | None = None
    values: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Archetype:
    """An instrument family with detection rules and field signatures."""
    name: str
    description: str
    keywords: tuple[str, ...]
    keyword_mode: str  # any, all
    field_signatures: tuple[FieldSignature, ...]


@dataclass(frozen=True)
class FVReconciliation:
    source_field: str
    tolerance_pct: float
    tolerance_abs: float


@dataclass(frozen=True)
class PositionCountQoQ:
    max_increase_pct: float
    max_decrease_pct: float


@dataclass(frozen=True)
class RateSanity:
    min_pct: float
    max_pct: float


@dataclass(frozen=True)
class EdgeCase:
    id: str
    description: str
    first_seen_quarter: str
    detection_pattern: str
    disposition: str  # expected, warn, fail


@dataclass(frozen=True)
class UnclassifiedRate:
    """Maximum allowed fraction of unclassified rows per quarter."""
    max_pct: float
    max_fv_pct: float = 0.05  # FV-weighted threshold (default 5%)


@dataclass(frozen=True)
class WrapperDefinition:
    """Parsed wrapper definition for one CIK (v2 or v3)."""
    cik: str
    entity_name: str
    version: int
    archetypes: tuple[Archetype, ...]
    fv_reconciliation: FVReconciliation | None = None
    position_count_qoq: PositionCountQoQ | None = None
    rate_sanity: RateSanity | None = None
    unclassified_rate: UnclassifiedRate | None = None
    edge_cases: tuple[EdgeCase, ...] = ()
    identifier_delimiter: str = ", "
    alternate_delimiters: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_wrapper_definition(cik: str | int) -> WrapperDefinition | None:
    """Load and parse a v2 or v3 wrapper JSON for the given CIK.

    Returns None if no definition file exists or lacks archetype/invariant
    sections relevant to content signature validation.
    """
    cik_norm = normalize_cik(cik)
    path = WRAPPER_DEFINITIONS_DIR / f"{cik_norm}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    schema_version = raw.get("schema_version", "")
    if schema_version not in ("bdc-xbrl-wrapper.v2", "bdc-xbrl-wrapper.v3"):
        return None
    # v3 files without archetypes or invariants are dispatch/staging only
    if schema_version == "bdc-xbrl-wrapper.v3":
        if not raw.get("archetypes") and not raw.get("invariants"):
            return None
    return _parse_definition(raw)


def _parse_definition(raw: dict[str, Any]) -> WrapperDefinition:
    archetypes = []
    for name, spec in (raw.get("archetypes") or {}).items():
        detection = spec.get("detection_rules") or {}
        keywords = tuple(detection.get("keywords") or [])
        keyword_mode = detection.get("keyword_mode", "any")
        sigs = []
        for field_name, sig_spec in (spec.get("field_signatures") or {}).items():
            sigs.append(FieldSignature(
                field_name=field_name,
                sig_type=sig_spec["type"],
                constraint=sig_spec.get("constraint", "optional"),
                min_val=sig_spec.get("min"),
                max_val=sig_spec.get("max"),
                pattern=sig_spec.get("pattern"),
                values=tuple(sig_spec["values"]) if "values" in sig_spec else None,
            ))
        archetypes.append(Archetype(
            name=name,
            description=spec.get("description", ""),
            keywords=keywords,
            keyword_mode=keyword_mode,
            field_signatures=tuple(sigs),
        ))

    invariants = raw.get("invariants") or {}
    fv_recon = None
    if "fv_reconciliation" in invariants:
        fv = invariants["fv_reconciliation"]
        fv_recon = FVReconciliation(
            source_field=fv.get("source_field", "investments_at_fair_value"),
            tolerance_pct=fv.get("tolerance_pct", 0.05),
            tolerance_abs=fv.get("tolerance_abs", 5000000),
        )
    pos_qoq = None
    if "position_count_qoq" in invariants:
        pq = invariants["position_count_qoq"]
        pos_qoq = PositionCountQoQ(
            max_increase_pct=pq.get("max_increase_pct", 2.0),
            max_decrease_pct=pq.get("max_decrease_pct", 0.5),
        )
    rate_san = None
    if "rate_sanity" in invariants:
        rs = invariants["rate_sanity"]
        rate_san = RateSanity(
            min_pct=rs.get("min_pct", 0.01),
            max_pct=rs.get("max_pct", 0.25),
        )

    unclass_rate = None
    if "unclassified_rate" in invariants:
        ur = invariants["unclassified_rate"]
        unclass_rate = UnclassifiedRate(
            max_pct=ur.get("max_pct", 0.05),
            max_fv_pct=ur.get("max_fv_pct", 0.05),
        )

    edge_cases = []
    for ec in raw.get("known_edge_cases") or []:
        edge_cases.append(EdgeCase(
            id=ec["id"],
            description=ec["description"],
            first_seen_quarter=ec.get("first_seen_quarter", ""),
            detection_pattern=ec.get("detection_pattern", ""),
            disposition=ec.get("disposition", "warn"),
        ))

    idf = raw.get("identifier_format") or {}
    return WrapperDefinition(
        cik=raw["cik"],
        entity_name=raw["entity_name"],
        version=raw["version"],
        archetypes=tuple(archetypes),
        fv_reconciliation=fv_recon,
        position_count_qoq=pos_qoq,
        rate_sanity=rate_san,
        unclassified_rate=unclass_rate,
        edge_cases=tuple(edge_cases),
        identifier_delimiter=idf.get("delimiter", ", "),
        alternate_delimiters=tuple(idf.get("alternate_delimiters") or []),
    )


# ---------------------------------------------------------------------------
# Archetype classification
# ---------------------------------------------------------------------------

# Column names that map to field signature field_name values
_FIELD_COLUMN_MAP = {
    "interest_rate": "interest_rate",
    "basis_spread": "basis_spread",
    "fair_value": "fair_value",
    "shares_held": "shares_held",
    "cost": "cost",
    "principal_amount": "principal_amount",
}


def classify_archetype(wrapper: WrapperDefinition, text: str) -> str | None:
    """Return the archetype name matching the given text, or None.

    Checks archetypes in definition order; first match wins.
    """
    if not text:
        return None
    text_lower = text.lower()
    for arch in wrapper.archetypes:
        if not arch.keywords:
            continue
        if arch.keyword_mode == "all":
            if all(kw.lower() in text_lower for kw in arch.keywords):
                return arch.name
        else:  # "any"
            if any(kw.lower() in text_lower for kw in arch.keywords):
                return arch.name
    return None


# ---------------------------------------------------------------------------
# Content signature validation
# ---------------------------------------------------------------------------


@dataclass
class SignatureViolation:
    """One field-level violation."""
    row_index: int
    report_date: str
    archetype: str
    field_name: str
    constraint: str
    sig_type: str
    actual_value: Any
    reason: str


def _field_is_present(value: Any) -> bool:
    """Return True if the field has a non-null, non-empty value."""
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    s = str(value).strip()
    return s != "" and s.lower() not in ("nan", "none")


def _check_one_signature(
    sig: FieldSignature,
    value: Any,
    row_idx: int,
    report_date: str,
    archetype_name: str,
) -> SignatureViolation | None:
    """Check one field signature against a value. Returns a violation or None."""
    present = _field_is_present(value)

    # Constraint checks
    if sig.constraint == "forbidden" and present:
        return SignatureViolation(
            row_index=row_idx,
            report_date=report_date,
            archetype=archetype_name,
            field_name=sig.field_name,
            constraint=sig.constraint,
            sig_type=sig.sig_type,
            actual_value=value,
            reason=f"Field '{sig.field_name}' is forbidden but has value",
        )
    if sig.constraint == "required" and not present:
        return SignatureViolation(
            row_index=row_idx,
            report_date=report_date,
            archetype=archetype_name,
            field_name=sig.field_name,
            constraint=sig.constraint,
            sig_type=sig.sig_type,
            actual_value=value,
            reason=f"Field '{sig.field_name}' is required but missing",
        )

    # If forbidden and not present, or optional and not present, pass
    if not present:
        return None

    # Type-specific checks (only when value is present)
    if sig.sig_type == "numeric_range":
        try:
            num = float(value)
        except (ValueError, TypeError):
            return SignatureViolation(
                row_index=row_idx,
                report_date=report_date,
                archetype=archetype_name,
                field_name=sig.field_name,
                constraint=sig.constraint,
                sig_type=sig.sig_type,
                actual_value=value,
                reason=f"Field '{sig.field_name}' is not numeric",
            )
        if sig.min_val is not None and num < sig.min_val:
            return SignatureViolation(
                row_index=row_idx,
                report_date=report_date,
                archetype=archetype_name,
                field_name=sig.field_name,
                constraint=sig.constraint,
                sig_type=sig.sig_type,
                actual_value=value,
                reason=f"Field '{sig.field_name}' value {num} below min {sig.min_val}",
            )
        if sig.max_val is not None and num > sig.max_val:
            return SignatureViolation(
                row_index=row_idx,
                report_date=report_date,
                archetype=archetype_name,
                field_name=sig.field_name,
                constraint=sig.constraint,
                sig_type=sig.sig_type,
                actual_value=value,
                reason=f"Field '{sig.field_name}' value {num} above max {sig.max_val}",
            )
    elif sig.sig_type == "regex":
        if sig.pattern and not re.search(sig.pattern, str(value)):
            return SignatureViolation(
                row_index=row_idx,
                report_date=report_date,
                archetype=archetype_name,
                field_name=sig.field_name,
                constraint=sig.constraint,
                sig_type=sig.sig_type,
                actual_value=value,
                reason=f"Field '{sig.field_name}' does not match pattern '{sig.pattern}'",
            )
    elif sig.sig_type == "enum":
        if sig.values and str(value) not in sig.values:
            return SignatureViolation(
                row_index=row_idx,
                report_date=report_date,
                archetype=archetype_name,
                field_name=sig.field_name,
                constraint=sig.constraint,
                sig_type=sig.sig_type,
                actual_value=value,
                reason=f"Field '{sig.field_name}' value not in allowed set",
            )
    # presence type: already handled by constraint checks above
    return None


def validate_content_signatures(
    wrapper: WrapperDefinition,
    holdings_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[SignatureViolation]]:
    """Validate per-row field signatures against archetype definitions.

    Returns (summary_df, violations_list).
    summary_df has one row per quarter with pass/fail counts.
    """
    summary_columns = [
        "report_date", "total_rows", "classified_rows", "unclassified_rows",
        "pass_rows", "fail_rows", "pass_rate",
        "unclassified_rate", "unclassified_rate_status",
        "total_fv", "classified_fv", "unclassified_fv",
        "unclassified_fv_rate", "unclassified_fv_rate_status",
    ]
    if holdings_df.empty:
        return pd.DataFrame(columns=summary_columns), []

    violations: list[SignatureViolation] = []
    # Determine the text column to classify on
    text_col = _resolve_text_column(holdings_df)
    report_date_col = "report_date" if "report_date" in holdings_df.columns else None
    has_fv = "fair_value" in holdings_df.columns

    per_row_pass = []
    per_row_archetype = []
    per_row_report_date = []
    per_row_fv: list[float] = []

    for idx, row in holdings_df.iterrows():
        text = str(row.get(text_col, "") or "")
        report_date = str(row.get(report_date_col, "") or "") if report_date_col else ""
        archetype_name = classify_archetype(wrapper, text)
        per_row_archetype.append(archetype_name or "")
        per_row_report_date.append(report_date)

        # Collect absolute fair value for FV-weighted coverage
        fv_val = 0.0
        if has_fv:
            raw_fv = row.get("fair_value")
            if _field_is_present(raw_fv):
                try:
                    fv_val = abs(float(raw_fv))
                except (ValueError, TypeError):
                    fv_val = 0.0
        per_row_fv.append(fv_val)

        if archetype_name is None:
            per_row_pass.append(True)  # Unclassified rows are not signature failures
            continue

        archetype = next((a for a in wrapper.archetypes if a.name == archetype_name), None)
        if archetype is None:
            per_row_pass.append(True)
            continue

        row_pass = True
        for sig in archetype.field_signatures:
            col_name = _FIELD_COLUMN_MAP.get(sig.field_name, sig.field_name)
            value = row.get(col_name)
            violation = _check_one_signature(sig, value, int(idx), report_date, archetype_name)
            if violation is not None:
                violations.append(violation)
                row_pass = False
        per_row_pass.append(row_pass)

    # Build summary by quarter
    result_df = pd.DataFrame({
        "report_date": per_row_report_date,
        "archetype": per_row_archetype,
        "row_pass": per_row_pass,
        "fair_value": per_row_fv,
    })
    # Determine thresholds from wrapper if available
    unclass_threshold = wrapper.unclassified_rate.max_pct if wrapper.unclassified_rate else None
    unclass_fv_threshold = wrapper.unclassified_rate.max_fv_pct if wrapper.unclassified_rate else None

    summary_rows = []
    for report_date, group in result_df.groupby("report_date", dropna=False):
        classified = group[group["archetype"].ne("")]
        unclassified = group[group["archetype"].eq("")]
        pass_rows = int(group["row_pass"].sum())
        fail_rows = int((~group["row_pass"]).sum())
        total = len(group)
        unclass_frac = len(unclassified) / total if total else 0.0
        unclass_status = ""
        if unclass_threshold is not None:
            unclass_status = "pass" if unclass_frac <= unclass_threshold else "fail"

        # FV-weighted coverage
        total_fv = float(group["fair_value"].sum())
        classified_fv = float(classified["fair_value"].sum()) if not classified.empty else 0.0
        unclassified_fv = float(unclassified["fair_value"].sum()) if not unclassified.empty else 0.0
        unclass_fv_frac = unclassified_fv / total_fv if total_fv > 0 else 0.0
        unclass_fv_status = ""
        if unclass_fv_threshold is not None:
            unclass_fv_status = "pass" if unclass_fv_frac <= unclass_fv_threshold else "fail"

        summary_rows.append({
            "report_date": report_date,
            "total_rows": total,
            "classified_rows": len(classified),
            "unclassified_rows": len(unclassified),
            "pass_rows": pass_rows,
            "fail_rows": fail_rows,
            "pass_rate": pass_rows / total if total else 0.0,
            "unclassified_rate": round(unclass_frac, 6),
            "unclassified_rate_status": unclass_status,
            "total_fv": round(total_fv, 2),
            "classified_fv": round(classified_fv, 2),
            "unclassified_fv": round(unclassified_fv, 2),
            "unclassified_fv_rate": round(unclass_fv_frac, 6),
            "unclassified_fv_rate_status": unclass_fv_status,
        })
    summary = pd.DataFrame(summary_rows)
    return summary, violations


def _resolve_text_column(df: pd.DataFrame) -> str:
    """Find the best text column for archetype classification.

    Prefers the column with the highest non-empty fill rate, checked in
    priority order.  This avoids selecting a column that exists but is
    mostly null (e.g. instrument_description with 38/8894 rows).
    """
    candidates = [
        "instrument_description",
        "bdc_investment_identifier",
        "investment_identifier",
        "issuer_name",
    ]
    best_col = ""
    best_fill = -1.0
    for candidate in candidates:
        if candidate not in df.columns:
            continue
        fill = df[candidate].fillna("").astype(str).str.strip().ne("").mean()
        if fill > best_fill:
            best_fill = fill
            best_col = candidate
    return best_col if best_col else (df.columns[0] if len(df.columns) > 0 else "")


# ---------------------------------------------------------------------------
# FV reconciliation
# ---------------------------------------------------------------------------


def validate_fv_reconciliation(
    wrapper: WrapperDefinition,
    holdings_df: pd.DataFrame,
    fund_financials_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compare sum of position fair values against fund-level anchor per quarter.

    Returns a DataFrame with one row per quarter showing the comparison.
    """
    result_cols = [
        "report_date", "position_fv_sum", "fund_fv", "abs_diff", "pct_diff",
        "tolerance_pct", "tolerance_abs", "status",
    ]
    if wrapper.fv_reconciliation is None:
        return pd.DataFrame(columns=result_cols)

    recon = wrapper.fv_reconciliation
    cik_norm = normalize_cik(wrapper.cik)

    # Get position-level FV sums by quarter
    if holdings_df.empty or "fair_value" not in holdings_df.columns:
        return pd.DataFrame(columns=result_cols)
    h = holdings_df.copy()
    h["fair_value"] = pd.to_numeric(h["fair_value"], errors="coerce")
    if "report_date" not in h.columns:
        return pd.DataFrame(columns=result_cols)
    pos_fv = h.groupby("report_date")["fair_value"].sum().reset_index()
    pos_fv.columns = ["report_date", "position_fv_sum"]

    # Get fund-level anchor values
    if fund_financials_df.empty:
        return pd.DataFrame(columns=result_cols)
    ff = fund_financials_df.copy()
    if "cik" in ff.columns:
        ff["cik"] = ff["cik"].map(normalize_cik)
        ff = ff[ff["cik"].eq(cik_norm)].copy()
    source_col = recon.source_field
    if source_col not in ff.columns:
        return pd.DataFrame(columns=result_cols)
    ff[source_col] = pd.to_numeric(ff[source_col], errors="coerce")
    if "report_date" not in ff.columns:
        return pd.DataFrame(columns=result_cols)
    fund_fv = ff[["report_date", source_col]].dropna(subset=[source_col]).copy()
    fund_fv.columns = ["report_date", "fund_fv"]

    merged = pos_fv.merge(fund_fv, on="report_date", how="inner")
    if merged.empty:
        return pd.DataFrame(columns=result_cols)

    merged["abs_diff"] = (merged["position_fv_sum"] - merged["fund_fv"]).abs()
    merged["pct_diff"] = merged["abs_diff"] / merged["fund_fv"].abs().replace(0, float("nan"))
    merged["tolerance_pct"] = recon.tolerance_pct
    merged["tolerance_abs"] = recon.tolerance_abs
    merged["status"] = "pass"
    fail_mask = (
        (merged["pct_diff"] > recon.tolerance_pct)
        & (merged["abs_diff"] > recon.tolerance_abs)
    )
    merged.loc[fail_mask, "status"] = "fail"
    return merged[result_cols].sort_values("report_date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# QoQ drift detection
# ---------------------------------------------------------------------------


def _detect_edge_cases(
    wrapper: WrapperDefinition,
    holdings_df: pd.DataFrame,
) -> pd.DataFrame:
    """Detect known edge cases in holdings data."""
    if holdings_df.empty or not wrapper.edge_cases:
        return pd.DataFrame(columns=[
            "report_date", "edge_case_id", "description", "disposition",
            "match_count", "first_seen_quarter",
        ])

    text_col = _resolve_text_column(holdings_df)
    report_date_col = "report_date" if "report_date" in holdings_df.columns else None

    rows = []
    for ec in wrapper.edge_cases:
        if not ec.detection_pattern:
            continue
        try:
            pat = re.compile(ec.detection_pattern, re.IGNORECASE)
        except re.error:
            continue
        matches = holdings_df[
            holdings_df[text_col].fillna("").astype(str).str.contains(pat, na=False)
        ]
        if matches.empty:
            continue
        if report_date_col:
            for rd, group in matches.groupby(report_date_col, dropna=False):
                rows.append({
                    "report_date": str(rd),
                    "edge_case_id": ec.id,
                    "description": ec.description,
                    "disposition": ec.disposition,
                    "match_count": len(group),
                    "first_seen_quarter": ec.first_seen_quarter,
                })
        else:
            rows.append({
                "report_date": "",
                "edge_case_id": ec.id,
                "description": ec.description,
                "disposition": ec.disposition,
                "match_count": len(matches),
                "first_seen_quarter": ec.first_seen_quarter,
            })
    return pd.DataFrame(rows)


def run_qoq_drift(
    wrapper: WrapperDefinition,
    all_quarters_df: pd.DataFrame,
    fund_financials_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the frozen wrapper across all quarters.

    Returns (drift_summary, drift_violations, fv_reconciliation, edge_cases).
    """
    # Content signatures
    sig_summary, violations = validate_content_signatures(wrapper, all_quarters_df)

    # FV reconciliation
    fv_recon = pd.DataFrame()
    if fund_financials_df is not None:
        fv_recon = validate_fv_reconciliation(wrapper, all_quarters_df, fund_financials_df)

    # Edge cases
    edge_cases = _detect_edge_cases(wrapper, all_quarters_df)

    # QoQ position count drift
    if not sig_summary.empty and wrapper.position_count_qoq is not None:
        sorted_summary = sig_summary.sort_values("report_date").copy()
        prev_count = None
        drift_flags = []
        for _, row in sorted_summary.iterrows():
            flag = ""
            count = row["total_rows"]
            if prev_count is not None and prev_count > 0:
                ratio = count / prev_count
                if ratio > wrapper.position_count_qoq.max_increase_pct:
                    flag = f"position_count_spike: {prev_count} -> {count} (ratio={ratio:.2f})"
                elif ratio < wrapper.position_count_qoq.max_decrease_pct:
                    flag = f"position_count_drop: {prev_count} -> {count} (ratio={ratio:.2f})"
            drift_flags.append(flag)
            prev_count = count
        sig_summary = sorted_summary.copy()
        sig_summary["qoq_drift_flag"] = drift_flags

    # Unclassified rate drift (already computed per-quarter in validate_content_signatures)
    if not sig_summary.empty and wrapper.unclassified_rate is not None:
        threshold = wrapper.unclassified_rate.max_pct
        if "unclassified_rate" in sig_summary.columns:
            exceeding = sig_summary[
                sig_summary["unclassified_rate_status"].fillna("").eq("fail")
            ]
            if not exceeding.empty:
                logger.warning(
                    "Unclassified rate exceeds %.1f%% threshold in %d/%d quarters for %s",
                    threshold * 100,
                    len(exceeding),
                    len(sig_summary),
                    wrapper.entity_name,
                )

    # Violations DataFrame
    violations_df = pd.DataFrame([
        {
            "row_index": v.row_index,
            "report_date": v.report_date,
            "archetype": v.archetype,
            "field_name": v.field_name,
            "constraint": v.constraint,
            "sig_type": v.sig_type,
            "actual_value": v.actual_value,
            "reason": v.reason,
        }
        for v in violations
    ])

    return sig_summary, violations_df, fv_recon, edge_cases


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _load_holdings_for_cik(cik: str) -> pd.DataFrame:
    """Load BDC holdings for one CIK from the BDC or unified holdings file.

    Prefers raw BDC holdings because unified holdings may have staging
    transformations (e.g. prefix_strip) that remove hierarchy labels
    needed for archetype classification.
    """
    cik_norm = normalize_cik(cik)
    numeric_cols = ["fair_value", "cost", "interest_rate", "basis_spread", "shares_held", "principal_amount"]

    # Prefer raw BDC holdings -- preserves full identifiers for classification
    if BDC_HOLDINGS_FILE.exists():
        df = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        if "cik" in df.columns:
            df["cik"] = df["cik"].map(normalize_cik)
            result = df[df["cik"].eq(cik_norm)].copy()
            if not result.empty:
                for col in numeric_cols:
                    if col in result.columns:
                        result[col] = pd.to_numeric(result[col], errors="coerce")
                return result

    # Fall back to unified holdings
    unified_path = OUTPUT_DIR / "private_markets_holdings.csv"
    if unified_path.exists():
        df = pd.read_csv(unified_path, dtype=str)
        if "cik" in df.columns and "source" in df.columns:
            df["cik"] = df["cik"].map(normalize_cik)
            result = df[
                df["cik"].eq(cik_norm)
                & df["source"].astype(str).str.lower().eq("bdc")
            ].copy()
            if not result.empty:
                for col in numeric_cols:
                    if col in result.columns:
                        result[col] = pd.to_numeric(result[col], errors="coerce")
                return result

    return pd.DataFrame()


def _load_fund_financials_for_cik(cik: str) -> pd.DataFrame:
    """Load fund financials for one CIK."""
    cik_norm = normalize_cik(cik)
    if not FUND_FINANCIALS_FILE.exists():
        return pd.DataFrame()
    df = pd.read_csv(FUND_FINANCIALS_FILE, dtype=str)
    if "cik" not in df.columns:
        return pd.DataFrame()
    df["cik"] = df["cik"].map(normalize_cik)
    result = df[df["cik"].eq(cik_norm)].copy()
    for col in ["investments_at_fair_value", "total_assets", "net_assets"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run content signature validation and QoQ drift check for a wrapper-supported CIK.",
    )
    parser.add_argument("--cik", required=True, help="CIK to validate (e.g. 0001918712)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: data/output/wrapper_drift/<cik>/)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cik_norm = normalize_cik(args.cik)
    wrapper = load_wrapper_definition(cik_norm)
    if wrapper is None:
        logger.error("No wrapper definition found for CIK %s", cik_norm)
        return 1

    logger.info("Loaded wrapper for %s (%s) version %d", wrapper.entity_name, cik_norm, wrapper.version)

    holdings_df = _load_holdings_for_cik(cik_norm)
    if holdings_df.empty:
        logger.error("No holdings data found for CIK %s", cik_norm)
        return 1
    logger.info("Loaded %d holdings rows for %s", len(holdings_df), cik_norm)

    fund_financials_df = _load_fund_financials_for_cik(cik_norm)
    logger.info("Loaded %d fund financials rows", len(fund_financials_df))

    drift_summary, violations_df, fv_recon, edge_cases = run_qoq_drift(
        wrapper, holdings_df, fund_financials_df if not fund_financials_df.empty else None
    )

    # Write outputs
    out_dir = args.output_dir or (OUTPUT_DIR / "wrapper_drift" / cik_norm)
    out_dir.mkdir(parents=True, exist_ok=True)

    drift_summary.to_csv(out_dir / "drift_summary.csv", index=False)
    violations_df.to_csv(out_dir / "drift_violations.csv", index=False)
    if not fv_recon.empty:
        fv_recon.to_csv(out_dir / "fv_reconciliation.csv", index=False)
    if not edge_cases.empty:
        edge_cases.to_csv(out_dir / "edge_cases.csv", index=False)

    # Print summary
    if not drift_summary.empty:
        total_rows = int(drift_summary["total_rows"].sum())
        pass_rows = int(drift_summary["pass_rows"].sum())
        fail_rows = int(drift_summary["fail_rows"].sum())
        avg_pass_rate = pass_rows / total_rows if total_rows else 0
        quarters = len(drift_summary)
        print(f"cik={cik_norm}")
        print(f"entity_name={wrapper.entity_name}")
        print(f"quarters={quarters}")
        print(f"total_rows={total_rows}")
        print(f"pass_rows={pass_rows}")
        print(f"fail_rows={fail_rows}")
        print(f"overall_pass_rate={avg_pass_rate:.4f}")
        print(f"violations={len(violations_df)}")
        if "qoq_drift_flag" in drift_summary.columns:
            drift_flags = drift_summary[drift_summary["qoq_drift_flag"].fillna("").ne("")]
            print(f"qoq_drift_flags={len(drift_flags)}")
    if not fv_recon.empty:
        fv_pass = int((fv_recon["status"] == "pass").sum())
        fv_fail = int((fv_recon["status"] == "fail").sum())
        print(f"fv_recon_quarters={len(fv_recon)}")
        print(f"fv_recon_pass={fv_pass}")
        print(f"fv_recon_fail={fv_fail}")
    if not edge_cases.empty:
        print(f"edge_cases_detected={len(edge_cases)}")
        for _, ec_row in edge_cases.iterrows():
            print(f"  {ec_row['edge_case_id']}: {ec_row['report_date']} ({ec_row['match_count']} matches)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
