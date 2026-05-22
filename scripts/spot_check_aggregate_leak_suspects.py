"""Create and summarize a stratified spot-check for aggregate-leak suspects.

This is an investigation utility. It reads cached pipeline outputs only and
writes a manual-review sample for estimating the false-positive rate of the
aggregate-suspect audit.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import sys
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from pipeline.validate_holdings import _sql_audit_keyword_check, _sql_audit_keyword_reason

logger = logging.getLogger("aggregate_leak_spot_check")

SEED = 20260520
TARGET_SAMPLE_SIZE = 385
OUTPUT_FILE = config.OUTPUT_DIR / "aggregate_leak_spot_check_sample.csv"
REVIEWED_OUTPUT_FILE = config.OUTPUT_DIR / "aggregate_leak_spot_check_reviewed.csv"
REVIEW_SUMMARY_FILE = config.OUTPUT_DIR / "aggregate_leak_spot_check_review_summary.md"

RARE_STRATA = frozenset(
    {
        "investment unsecured",
        "cash and cash equivalents",
        "unfunded commitments",
        "total investments",
    }
)

PLANNED_COMMON_ALLOCATION = {
    "non-control": 186,
    "investment debt investments": 87,
    "net assets": 34,
    "affiliate investments": 26,
    "investment equity securities": 22,
}

REVIEW_LABELS = (
    "confirmed_aggregate_leak",
    "false_positive_valid_position",
    "non_private_or_cash_scope_issue",
    "ambiguous_needs_filing_context",
)

FALSE_POSITIVE_LABELS = frozenset(
    {
        "false_positive_valid_position",
        "non_private_or_cash_scope_issue",
    }
)

SAMPLE_COLUMNS = [
    "sample_row_key",
    "sample_seed",
    "stratum_size",
    "stratum_sample_size",
    "inclusion_weight",
    "audit_keyword",
    "audit_reason",
    "cik",
    "entity_name",
    "report_date",
    "period",
    "accession_number",
    "filing_date",
    "bdc_form_type",
    "issuer_name",
    "instrument_description",
    "bdc_investment_identifier",
    "fair_value",
    "cost",
    "pct_of_net_assets",
    "shares_held",
    "principal_amount",
    "asset_category",
    "issuer_category",
    "index_classification",
    "asset_class",
    "exposure_type",
    "interest_rate",
    "basis_spread",
    "reference_rate_type",
    "coupon_type",
    "pik_rate",
    "maturity_date",
    "bdc_dimensions_raw",
    "source_reconciliation_status",
    "source_match_tier",
    "source_issue_severity",
    "source_residual_class",
    "source_blocking_issue",
    "source_calibrated_status",
    "source_raw_identifier",
    "source_normalized_identifier",
    "source_context_id",
    "source_concept_names",
    "source_fair_value",
    "source_cost",
    "source_evidence",
    "source_mismatched_fields",
    "review_label",
    "review_confidence",
    "evidence_summary",
    "recommended_action",
]


def _csv_rel(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def build_audit_frame(
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
    reconciliation_path: Path = config.SOURCE_RECONCILIATION_DETAIL_FILE,
) -> pd.DataFrame:
    """Reproduce aggregate-leak audit rows and attach cached evidence."""
    if not holdings_path.exists():
        raise FileNotFoundError(f"Missing unified holdings CSV: {holdings_path}")

    con = duckdb.connect()
    kw_check = _sql_audit_keyword_check()
    kw_reason = _sql_audit_keyword_reason()
    holdings_csv = _csv_rel(holdings_path)

    evidence_cte = ""
    evidence_join = ""
    evidence_qualify = ""
    evidence_cols = """
        CAST(NULL AS VARCHAR) AS source_reconciliation_status,
        CAST(NULL AS VARCHAR) AS source_match_tier,
        CAST(NULL AS VARCHAR) AS source_issue_severity,
        CAST(NULL AS VARCHAR) AS source_residual_class,
        CAST(NULL AS BOOLEAN) AS source_blocking_issue,
        CAST(NULL AS VARCHAR) AS source_calibrated_status,
        CAST(NULL AS VARCHAR) AS source_raw_identifier,
        CAST(NULL AS VARCHAR) AS source_normalized_identifier,
        CAST(NULL AS VARCHAR) AS source_context_id,
        CAST(NULL AS VARCHAR) AS source_concept_names,
        CAST(NULL AS DOUBLE) AS source_fair_value,
        CAST(NULL AS DOUBLE) AS source_cost,
        CAST(NULL AS VARCHAR) AS source_evidence,
        CAST(NULL AS VARCHAR) AS source_mismatched_fields
    """

    if reconciliation_path.exists():
        recon_csv = _csv_rel(reconciliation_path)
        evidence_cte = f"""
        , source_evidence_ranked AS (
            SELECT
                lpad(regexp_replace(CAST(cik AS VARCHAR), '^0+', ''), 10, '0') AS cik_norm,
                CAST(report_date AS DATE) AS report_date,
                COALESCE(CAST(accession_number AS VARCHAR), '') AS accession_number,
                COALESCE(CAST(normalized_investment_identifier AS VARCHAR), '') AS normalized_identifier,
                COALESCE(CAST(raw_investment_identifier AS VARCHAR), '') AS raw_identifier,
                ROUND(TRY_CAST(source_fair_value AS DOUBLE), 2) AS source_fv_round,
                ROUND(TRY_CAST(output_fair_value AS DOUBLE), 2) AS output_fv_round,
                status,
                match_tier,
                issue_severity,
                residual_class,
                blocking_issue,
                calibrated_status,
                context_id,
                concept_names,
                source_fair_value,
                source_cost,
                evidence,
                mismatched_fields,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        lpad(regexp_replace(CAST(cik AS VARCHAR), '^0+', ''), 10, '0'),
                        CAST(report_date AS DATE),
                        COALESCE(CAST(accession_number AS VARCHAR), ''),
                        COALESCE(CAST(normalized_investment_identifier AS VARCHAR), ''),
                        ROUND(TRY_CAST(output_fair_value AS DOUBLE), 2)
                    ORDER BY
                        CASE status
                            WHEN 'matched' THEN 0
                            WHEN 'diagnostic_issue' THEN 1
                            ELSE 2
                        END,
                        source_row_id NULLS LAST
                ) AS rn
            FROM read_csv_auto('{recon_csv}', all_varchar=false)
        )
        """
        evidence_join = """
        LEFT JOIN source_evidence_ranked e
          ON e.rn = 1
         AND e.cik_norm = k.cik_norm
         AND e.report_date = k.report_date
         AND e.accession_number = COALESCE(CAST(k.accession_number AS VARCHAR), '')
         AND (
             e.normalized_identifier = COALESCE(CAST(k.bdc_investment_identifier AS VARCHAR), '')
             OR e.raw_identifier = COALESCE(CAST(k.bdc_investment_identifier AS VARCHAR), '')
         )
         AND (
             e.output_fv_round = ROUND(TRY_CAST(k.fair_value AS DOUBLE), 2)
             OR e.source_fv_round = ROUND(TRY_CAST(k.fair_value AS DOUBLE), 2)
         )
        """
        evidence_qualify = """
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY k.sample_row_key
            ORDER BY
                CASE e.status
                    WHEN 'matched' THEN 0
                    WHEN 'diagnostic_issue' THEN 1
                    ELSE 2
                END,
                e.context_id NULLS LAST
        ) = 1
        """
        evidence_cols = """
            e.status AS source_reconciliation_status,
            e.match_tier AS source_match_tier,
            e.issue_severity AS source_issue_severity,
            e.residual_class AS source_residual_class,
            e.blocking_issue AS source_blocking_issue,
            e.calibrated_status AS source_calibrated_status,
            e.raw_identifier AS source_raw_identifier,
            e.normalized_identifier AS source_normalized_identifier,
            e.context_id AS source_context_id,
            e.concept_names AS source_concept_names,
            e.source_fair_value AS source_fair_value,
            e.source_cost AS source_cost,
            e.evidence AS source_evidence,
            e.mismatched_fields AS source_mismatched_fields
        """

    sql = f"""
    WITH audited AS (
        SELECT
            ROW_NUMBER() OVER () AS source_row_number,
            lpad(regexp_replace(CAST(cik AS VARCHAR), '^0+', ''), 10, '0') AS cik_norm,
            replace(({kw_reason}), 'keyword:', '') AS audit_keyword,
            ({kw_reason}) AS audit_reason,
            *
        FROM read_csv_auto('{holdings_csv}', all_varchar=false)
        WHERE source = 'bdc'
          AND ({kw_check})
    ),
    keyed AS (
        SELECT
            *,
            md5(concat_ws('|',
                COALESCE(CAST(cik AS VARCHAR), ''),
                COALESCE(CAST(entity_name AS VARCHAR), ''),
                COALESCE(CAST(report_date AS VARCHAR), ''),
                COALESCE(CAST(accession_number AS VARCHAR), ''),
                COALESCE(CAST(issuer_name AS VARCHAR), ''),
                COALESCE(CAST(instrument_description AS VARCHAR), ''),
                COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                COALESCE(CAST(fair_value AS VARCHAR), ''),
                CAST(source_row_number AS VARCHAR)
            )) AS sample_row_key
        FROM audited
    )
    {evidence_cte}
    SELECT
        k.sample_row_key,
        {SEED} AS sample_seed,
        k.audit_keyword,
        k.audit_reason,
        k.cik,
        k.entity_name,
        k.report_date,
        k.report_date AS period,
        k.accession_number,
        k.filing_date,
        k.bdc_form_type,
        k.issuer_name,
        k.instrument_description,
        k.bdc_investment_identifier,
        k.fair_value,
        k.cost,
        k.pct_of_net_assets,
        k.shares_held,
        k.principal_amount,
        k.asset_category,
        k.issuer_category,
        k.index_classification,
        k.asset_class,
        k.exposure_type,
        k.interest_rate,
        k.basis_spread,
        k.reference_rate_type,
        k.coupon_type,
        k.pik_rate,
        k.maturity_date,
        k.bdc_dimensions_raw,
        {evidence_cols}
    FROM keyed k
    {evidence_join}
    {evidence_qualify}
    """

    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


def allocate_sample(
    stratum_sizes: dict[str, int],
    target_total: int = TARGET_SAMPLE_SIZE,
    rare_strata: frozenset[str] = RARE_STRATA,
    planned_common: dict[str, int] = PLANNED_COMMON_ALLOCATION,
) -> dict[str, int]:
    """Return deterministic stratum sample counts for the audit frame."""
    allocation: dict[str, int] = {}

    for stratum, size in sorted(stratum_sizes.items()):
        if stratum in rare_strata:
            allocation[stratum] = size

    rare_total = sum(allocation.values())
    remaining = target_total - rare_total
    if remaining < 0:
        raise ValueError(
            f"Rare-stratum census has {rare_total} rows, above target sample {target_total}"
        )

    planned_total = sum(planned_common.values())
    if planned_total == remaining:
        for stratum, planned_n in planned_common.items():
            if stratum in stratum_sizes:
                allocation[stratum] = min(planned_n, stratum_sizes[stratum])
    else:
        common = {
            stratum: size
            for stratum, size in stratum_sizes.items()
            if stratum not in rare_strata
        }
        common_total = sum(common.values())
        if common_total:
            floors: dict[str, int] = {}
            remainders: list[tuple[float, str]] = []
            for stratum, size in common.items():
                exact = remaining * size / common_total
                floors[stratum] = min(size, math.floor(exact))
                remainders.append((exact - math.floor(exact), stratum))
            allocation.update(floors)
            shortfall = target_total - sum(allocation.values())
            for _, stratum in sorted(remainders, reverse=True):
                if shortfall <= 0:
                    break
                if allocation[stratum] < stratum_sizes[stratum]:
                    allocation[stratum] += 1
                    shortfall -= 1

    shortfall = target_total - sum(allocation.values())
    if shortfall > 0:
        for stratum, size in sorted(stratum_sizes.items(), key=lambda item: item[1], reverse=True):
            if shortfall <= 0:
                break
            add_n = min(shortfall, size - allocation.get(stratum, 0))
            if add_n > 0:
                allocation[stratum] = allocation.get(stratum, 0) + add_n
                shortfall -= add_n

    return {stratum: n for stratum, n in allocation.items() if n > 0}


def stratified_sample(audit_df: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """Build the deterministic stratified review sample."""
    if audit_df.empty:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    if audit_df["sample_row_key"].duplicated().any():
        raise ValueError("sample_row_key must be unique before sampling")

    stratum_sizes = audit_df.groupby("audit_keyword", dropna=False).size().to_dict()
    allocation = allocate_sample(stratum_sizes)

    parts = []
    for stratum, sample_n in allocation.items():
        group = audit_df[audit_df["audit_keyword"] == stratum].copy()
        if group.empty:
            continue
        group["_sort_key"] = group["sample_row_key"].map(
            lambda value: hashlib.sha256(f"{seed}|{value}".encode("utf-8")).hexdigest()
        )
        parts.append(group.sort_values("_sort_key", kind="mergesort").head(sample_n))

    if not parts:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)

    sample = pd.concat(parts, ignore_index=True)
    observed_sizes = sample.groupby("audit_keyword", dropna=False).size().to_dict()
    sample["stratum_size"] = sample["audit_keyword"].map(stratum_sizes).astype("int64")
    sample["stratum_sample_size"] = sample["audit_keyword"].map(observed_sizes).astype("int64")
    sample["inclusion_weight"] = sample["stratum_size"] / sample["stratum_sample_size"]
    for col in ("review_label", "review_confidence", "evidence_summary", "recommended_action"):
        sample[col] = ""

    sample = sample.drop(columns=[c for c in sample.columns if c.startswith("_")], errors="ignore")
    for col in SAMPLE_COLUMNS:
        if col not in sample.columns:
            sample[col] = pd.NA
    return sample[SAMPLE_COLUMNS].sort_values(["audit_keyword", "sample_row_key"]).reset_index(drop=True)


def compute_weighted_false_positive_estimate(review_df: pd.DataFrame) -> dict[str, float | int]:
    """Compute weighted false-positive estimate from reviewed non-ambiguous rows."""
    required = {"audit_keyword", "stratum_size", "review_label"}
    missing = required - set(review_df.columns)
    if missing:
        raise ValueError(f"Review data missing required columns: {sorted(missing)}")

    reviewed = review_df[review_df["review_label"].astype(str).str.len() > 0].copy()
    invalid = set(reviewed["review_label"]) - set(REVIEW_LABELS)
    if invalid:
        raise ValueError(f"Invalid review_label values: {sorted(invalid)}")
    if reviewed.empty:
        return {
            "reviewed_rows": 0,
            "weighted_false_positive_rate": math.nan,
            "ci95_low": math.nan,
            "ci95_high": math.nan,
        }

    ambiguous_rows = int((reviewed["review_label"] == "ambiguous_needs_filing_context").sum())
    estimate_base = reviewed[reviewed["review_label"] != "ambiguous_needs_filing_context"].copy()
    if estimate_base.empty:
        return {
            "reviewed_rows": int(len(reviewed)),
            "estimate_rows": 0,
            "ambiguous_rows": ambiguous_rows,
            "weighted_false_positive_rate": math.nan,
            "ci95_low": math.nan,
            "ci95_high": math.nan,
            "sensitivity_low": math.nan,
            "sensitivity_high": math.nan,
        }

    estimate_base["is_false_positive"] = estimate_base["review_label"].isin(FALSE_POSITIVE_LABELS).astype(float)
    strata = []
    for _, group in estimate_base.groupby("audit_keyword", dropna=False):
        n_h = len(group)
        n_population = float(group["stratum_size"].iloc[0])
        p_h = float(group["is_false_positive"].mean())
        if n_h > 1:
            s2_h = float(group["is_false_positive"].var(ddof=1))
            finite_correction = max(0.0, 1.0 - (n_h / n_population)) if n_population else 0.0
            var_h = finite_correction * s2_h / n_h
        else:
            var_h = 0.0
        strata.append((n_population, p_h, var_h))

    total_population = sum(item[0] for item in strata)
    if total_population == 0:
        return {
            "reviewed_rows": int(len(reviewed)),
            "estimate_rows": int(len(estimate_base)),
            "ambiguous_rows": ambiguous_rows,
            "weighted_false_positive_rate": math.nan,
            "ci95_low": math.nan,
            "ci95_high": math.nan,
            "sensitivity_low": math.nan,
            "sensitivity_high": math.nan,
        }

    estimate = sum(n_h * p_h for n_h, p_h, _ in strata) / total_population
    variance = sum(((n_h / total_population) ** 2) * var_h for n_h, _, var_h in strata)
    half_width = 1.96 * math.sqrt(max(variance, 0.0))
    sensitivity = _weighted_ambiguous_sensitivity(reviewed)
    return {
        "reviewed_rows": int(len(reviewed)),
        "estimate_rows": int(len(estimate_base)),
        "ambiguous_rows": ambiguous_rows,
        "weighted_false_positive_rate": estimate,
        "ci95_low": max(0.0, estimate - half_width),
        "ci95_high": min(1.0, estimate + half_width),
        "sensitivity_low": sensitivity["ambiguous_as_confirmed"],
        "sensitivity_high": sensitivity["ambiguous_as_false_positive"],
    }


def _weighted_ambiguous_sensitivity(reviewed: pd.DataFrame) -> dict[str, float]:
    """Return weighted bounds treating ambiguous rows as either outcome."""
    if reviewed.empty:
        return {"ambiguous_as_confirmed": math.nan, "ambiguous_as_false_positive": math.nan}

    def _estimate(false_positive_labels: frozenset[str]) -> float:
        strata = []
        for _, group in reviewed.groupby("audit_keyword", dropna=False):
            n_population = float(group["stratum_size"].iloc[0])
            p_h = float(group["review_label"].isin(false_positive_labels).mean())
            strata.append((n_population, p_h))
        total_population = sum(item[0] for item in strata)
        if total_population == 0:
            return math.nan
        return sum(n_h * p_h for n_h, p_h in strata) / total_population

    return {
        "ambiguous_as_confirmed": _estimate(FALSE_POSITIVE_LABELS),
        "ambiguous_as_false_positive": _estimate(
            FALSE_POSITIVE_LABELS | frozenset({"ambiguous_needs_filing_context"})
        ),
    }


def false_positive_rate_by_keyword(review_df: pd.DataFrame) -> pd.DataFrame:
    reviewed = review_df[review_df["review_label"].astype(str).str.len() > 0].copy()
    if reviewed.empty:
        return pd.DataFrame(
            columns=[
                "audit_keyword",
                "reviewed_rows",
                "estimate_rows",
                "ambiguous_rows",
                "false_positive_rows",
                "false_positive_rate",
            ]
        )
    reviewed["is_ambiguous"] = (reviewed["review_label"] == "ambiguous_needs_filing_context").astype(int)
    reviewed["is_estimate_row"] = 1 - reviewed["is_ambiguous"]
    reviewed["is_false_positive"] = reviewed["review_label"].isin(FALSE_POSITIVE_LABELS).astype(int)
    grouped = (
        reviewed.groupby("audit_keyword", dropna=False)
        .agg(
            reviewed_rows=("review_label", "size"),
            estimate_rows=("is_estimate_row", "sum"),
            ambiguous_rows=("is_ambiguous", "sum"),
            false_positive_rows=("is_false_positive", "sum"),
        )
        .reset_index()
    )
    grouped["false_positive_rate"] = grouped["false_positive_rows"] / grouped["estimate_rows"]
    grouped.loc[grouped["estimate_rows"] == 0, "false_positive_rate"] = math.nan
    return grouped


def confirmed_leak_fair_value_summary(review_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    confirmed = review_df[review_df["review_label"] == "confirmed_aggregate_leak"].copy()
    if confirmed.empty:
        empty = pd.DataFrame()
        return empty, empty
    confirmed["fair_value_num"] = pd.to_numeric(confirmed["fair_value"], errors="coerce").fillna(0)
    by_keyword = (
        confirmed.groupby("audit_keyword", dropna=False)
        .agg(confirmed_rows=("review_label", "size"), confirmed_fair_value=("fair_value_num", "sum"))
        .reset_index()
        .sort_values("confirmed_fair_value", ascending=False)
    )
    by_cik_quarter = (
        confirmed.groupby(["cik", "entity_name", "report_date"], dropna=False)
        .agg(confirmed_rows=("review_label", "size"), confirmed_fair_value=("fair_value_num", "sum"))
        .reset_index()
        .sort_values("confirmed_fair_value", ascending=False)
    )
    return by_keyword, by_cik_quarter


def recurring_false_positive_patterns(review_df: pd.DataFrame) -> pd.DataFrame:
    """Summarize recurring reviewed false-positive patterns."""
    reviewed = review_df[review_df["review_label"].isin(FALSE_POSITIVE_LABELS)].copy()
    if reviewed.empty:
        return pd.DataFrame(columns=["pattern", "rows", "audit_keywords", "recommended_rule_narrowing"])

    def pattern_for(row: pd.Series) -> str:
        keyword = str(row.get("audit_keyword", ""))
        label = str(row.get("review_label", ""))
        text = " ".join(
            str(row.get(col, ""))
            for col in ("issuer_name", "instrument_description", "bdc_investment_identifier")
        ).lower()
        classification = str(row.get("index_classification", "")).upper()
        if (
            label == "non_private_or_cash_scope_issue"
            or keyword == "cash and cash equivalents"
            or classification == "CASH"
        ):
            return "cash, money-market, or JV liquidity rows are scope issues, not aggregate leaks"
        if keyword in {
            "affiliate investments",
            "investment debt investments",
            "investment equity securities",
            "net assets",
            "non-control",
        }:
            return "hierarchy/affiliation wording prefixes otherwise position-like identifiers"
        if keyword in {"investment unsecured", "unfunded commitments"}:
            return "instrument or commitment wording is embedded in real debt position descriptions"
        return "audit keyword appears in position-level filing text"

    reviewed["pattern"] = reviewed.apply(pattern_for, axis=1)
    summary = (
        reviewed.groupby("pattern", dropna=False)
        .agg(
            rows=("review_label", "size"),
            audit_keywords=("audit_keyword", lambda values: ", ".join(sorted(set(map(str, values))))),
        )
        .reset_index()
        .sort_values(["rows", "pattern"], ascending=[False, True])
    )
    action_map = {
        "cash, money-market, or JV liquidity rows are scope issues, not aggregate leaks": (
            "route cash/money-market/private-liquidity rows to scope review instead of aggregate-leak audit"
        ),
        "hierarchy/affiliation wording prefixes otherwise position-like identifiers": (
            "require missing issuer/instrument evidence before flagging hierarchy prefixes as leaks"
        ),
        "instrument or commitment wording is embedded in real debt position descriptions": (
            "avoid treating unsecured/commitment text as aggregate unless the row lacks a portfolio-company name"
        ),
        "audit keyword appears in position-level filing text": (
            "narrow the keyword rule with position-evidence exceptions"
        ),
    }
    summary["recommended_rule_narrowing"] = summary["pattern"].map(action_map).fillna(
        "narrow the keyword rule with position-evidence exceptions"
    )
    return summary


def render_review_summary(review_df: pd.DataFrame) -> str:
    """Render a completed aggregate-leak spot-check review as markdown."""
    estimate = compute_weighted_false_positive_estimate(review_df)
    by_keyword = false_positive_rate_by_keyword(review_df)
    confirmed_by_keyword, confirmed_by_cik = confirmed_leak_fair_value_summary(review_df)
    patterns = recurring_false_positive_patterns(review_df)
    labels = review_df["review_label"].fillna("").replace("", "unreviewed").value_counts().reset_index()
    labels.columns = ["review_label", "rows"]

    def pct(value: float) -> str:
        if pd.isna(value):
            return "n/a"
        return f"{value:.1%}"

    def table(frame: pd.DataFrame) -> str:
        if frame.empty:
            return ""
        safe = frame.copy()
        for col in safe.columns:
            safe[col] = safe[col].map(lambda value: "" if pd.isna(value) else str(value))
        header = "| " + " | ".join(map(str, safe.columns)) + " |"
        separator = "| " + " | ".join("---" for _ in safe.columns) + " |"
        body = ["| " + " | ".join(row) + " |" for row in safe.astype(str).values.tolist()]
        return "\n".join([header, separator, *body])

    lines = [
        "# Aggregate leak spot-check review",
        "",
        "Manual review of `data/output/aggregate_leak_spot_check_sample.csv` using cached pipeline/source artifacts only.",
        "",
        "## Overall estimate",
        "",
        f"- Reviewed rows: {estimate['reviewed_rows']}",
        f"- Rows in point estimate: {estimate['estimate_rows']}",
        f"- Ambiguous rows excluded from point estimate: {estimate['ambiguous_rows']}",
        f"- Weighted false-positive rate: {pct(float(estimate['weighted_false_positive_rate']))}",
        f"- 95% CI: {pct(float(estimate['ci95_low']))} to {pct(float(estimate['ci95_high']))}",
        f"- Sensitivity range if ambiguous rows are treated as confirmed leaks vs false positives: {pct(float(estimate['sensitivity_low']))} to {pct(float(estimate['sensitivity_high']))}",
        "",
        "False positives include `false_positive_valid_position` and `non_private_or_cash_scope_issue`.",
        "",
        "## Label counts",
        "",
        table(labels),
        "",
        "## False-positive rate by audit keyword",
        "",
        table(by_keyword),
        "",
        "## Confirmed-leak fair value by keyword",
        "",
        table(confirmed_by_keyword.head(20)) if not confirmed_by_keyword.empty else "No confirmed aggregate leaks.",
        "",
        "## Top CIK-quarter confirmed-leak fair value",
        "",
        table(confirmed_by_cik.head(20)) if not confirmed_by_cik.empty else "No confirmed aggregate leaks.",
        "",
        "## Recurring false-positive patterns",
        "",
        table(patterns) if not patterns.empty else "No false-positive patterns identified.",
        "",
    ]
    return "\n".join(lines)


def write_review_summary(
    review_df: pd.DataFrame,
    output_path: Path = REVIEW_SUMMARY_FILE,
) -> str:
    """Write markdown summary for a completed manual review."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = render_review_summary(review_df)
    output_path.write_text(text, encoding="utf-8")
    return text


def write_sample(
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
    reconciliation_path: Path = config.SOURCE_RECONCILIATION_DETAIL_FILE,
    output_path: Path = OUTPUT_FILE,
) -> pd.DataFrame:
    audit_df = build_audit_frame(holdings_path, reconciliation_path)
    sample = stratified_sample(audit_df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(output_path, index=False)
    logger.info("Wrote %d sampled rows to %s", len(sample), output_path)
    logger.info("Audit strata: %s", audit_df.groupby("audit_keyword").size().to_dict())
    logger.info("Sample strata: %s", sample.groupby("audit_keyword").size().to_dict())
    return sample


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", type=Path, default=config.UNIFIED_HOLDINGS_FILE)
    parser.add_argument("--reconciliation", type=Path, default=config.SOURCE_RECONCILIATION_DETAIL_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    write_sample(args.holdings, args.reconciliation, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
