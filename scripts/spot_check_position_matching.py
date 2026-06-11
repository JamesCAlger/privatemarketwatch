"""Stratified spot-check audit for position matching quality.

Generates a stratified random sample of position matches, applies heuristic
error flags, and provides automated pre-review estimates.  After human review,
computes weighted error rates with 95% CIs.

Subcommands:
    (default)    Generate the sample + auto flags + print pre-review summary
    --dry-run    Show strata sizes only, no output written
    --summarize  Compute weighted error rates from reviewed sample
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
from pipeline.bdc_xbrl_wrapper import supported_wrapper_ciks

logger = logging.getLogger("position_match_spot_check")

SEED = 20260609
TARGET_SAMPLE_SIZE = 500
FLOOR_PER_STRATUM = 30

OUTPUT_FILE = config.OUTPUT_DIR / "position_match_spot_check_sample.csv"
REVIEW_SUMMARY_FILE = config.OUTPUT_DIR / "position_match_spot_check_review_summary.md"

REVIEW_LABELS = (
    "correct_match",
    "wrong_instrument",
    "wrong_entity",
    "wrong_tranche",
    "ambiguous",
)

ERROR_LABELS = frozenset({"wrong_instrument", "wrong_entity", "wrong_tranche"})

# Match-method tiers in display order
TIER_ORDER = [
    "A_within_filing",
    "B1b_position_key",
    "B2_exact_name",
    "C_normalized_name",
    "D_fuzzy",
    "E_entity_fingerprint",
]

SAMPLE_COLUMNS = [
    # Sample metadata
    "sample_row_key",
    "sample_seed",
    "match_method",
    "stratum_size",
    "stratum_sample_size",
    "inclusion_weight",
    # Match columns
    "cik",
    "entity_name",
    "position_id",
    "match_key",
    "match_score",
    "span_months",
    # Begin-side
    "begin_report_date",
    "begin_issuer_name",
    "begin_fair_value",
    "begin_bdc_investment_identifier",
    "begin_instrument_description",
    "begin_index_classification",
    "begin_interest_rate",
    "begin_maturity_date",
    "begin_position_key",
    "begin_cusip",
    "begin_principal_amount",
    # End-side
    "end_report_date",
    "end_issuer_name",
    "end_fair_value",
    "end_bdc_investment_identifier",
    "end_instrument_description",
    "end_index_classification",
    "end_interest_rate",
    "end_maturity_date",
    "end_position_key",
    "end_cusip",
    "end_principal_amount",
    # Heuristic flags
    "flag_fv_ratio_extreme",
    "flag_name_divergence",
    "flag_classification_flip",
    "flag_rate_discontinuity",
    "flag_maturity_mismatch",
    "flag_principal_ratio_extreme",
    "flag_count",
    "programmatic_verdict",
    # Review columns (blank for human fill-in)
    "review_label",
    "review_confidence",
    "evidence_summary",
]


def _csv_rel(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _jaro_winkler_sql(s1: str, s2: str) -> str:
    """Return DuckDB SQL expression for Jaro-Winkler similarity."""
    return f"jaro_winkler_similarity({s1}, {s2}) / 100.0"


def build_audit_frame(
    matches_path: Path = config.POSITION_MATCHES_FILE,
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
) -> pd.DataFrame:
    """Build the audit frame by joining matches to unified holdings for both sides."""
    if not matches_path.exists():
        raise FileNotFoundError(f"Missing position matches CSV: {matches_path}")
    if not holdings_path.exists():
        raise FileNotFoundError(f"Missing unified holdings CSV: {holdings_path}")

    wrapper_ciks = supported_wrapper_ciks()
    if not wrapper_ciks:
        raise ValueError("No supported wrapper CIKs found")

    cik_list = ", ".join(f"'{c}'" for c in wrapper_ciks)
    matches_csv = _csv_rel(matches_path)
    holdings_csv = _csv_rel(holdings_path)

    # The join strategy mirrors assign_position_ids() in position_matching.py:1549-1633
    # Tier A: match side issuer_name = unified bdc_investment_identifier
    # Tier B1b: match match_key = unified position_key
    # Others (B2, C, D, E): match side issuer_name = unified issuer_name
    # All tiers: cik + source + report_date + FV-proximity tiebreaker

    def _side_join_sql(side: str) -> str:
        date_col = f"{side}_report_date"
        name_col = f"{side}_issuer_name"
        fv_col = f"{side}_fair_value"
        return f"""
        WITH
        tier_a_cand AS (
            SELECT
                m._midx,
                u._uid,
                ABS(COALESCE(TRY_CAST(m.{fv_col} AS DOUBLE), 0)
                    - COALESCE(TRY_CAST(u.fair_value AS DOUBLE), 0)) AS _fv_diff
            FROM matches m
            JOIN holdings u
              ON CAST(m.cik AS VARCHAR) = CAST(u.cik AS VARCHAR)
             AND CAST(m.source AS VARCHAR) = CAST(u.source AS VARCHAR)
             AND CAST(m.{date_col} AS VARCHAR) = CAST(u.report_date AS VARCHAR)
             AND CAST(m.{name_col} AS VARCHAR) = CAST(u.bdc_investment_identifier AS VARCHAR)
            WHERE CAST(m.match_method AS VARCHAR) LIKE 'A%'
        ),
        poskey_cand AS (
            SELECT
                m._midx,
                u._uid,
                ABS(COALESCE(TRY_CAST(m.{fv_col} AS DOUBLE), 0)
                    - COALESCE(TRY_CAST(u.fair_value AS DOUBLE), 0)) AS _fv_diff
            FROM matches m
            JOIN holdings u
              ON CAST(m.cik AS VARCHAR) = CAST(u.cik AS VARCHAR)
             AND CAST(m.source AS VARCHAR) = CAST(u.source AS VARCHAR)
             AND CAST(m.{date_col} AS VARCHAR) = CAST(u.report_date AS VARCHAR)
             AND CAST(m.match_key AS VARCHAR) = CAST(u.position_key AS VARCHAR)
            WHERE CAST(m.match_method AS VARCHAR) = 'B1b_position_key'
        ),
        other_cand AS (
            SELECT
                m._midx,
                u._uid,
                ABS(COALESCE(TRY_CAST(m.{fv_col} AS DOUBLE), 0)
                    - COALESCE(TRY_CAST(u.fair_value AS DOUBLE), 0)) AS _fv_diff
            FROM matches m
            JOIN holdings u
              ON CAST(m.cik AS VARCHAR) = CAST(u.cik AS VARCHAR)
             AND CAST(m.source AS VARCHAR) = CAST(u.source AS VARCHAR)
             AND CAST(m.{date_col} AS VARCHAR) = CAST(u.report_date AS VARCHAR)
             AND CAST(m.{name_col} AS VARCHAR) = CAST(u.issuer_name AS VARCHAR)
            WHERE CAST(m.match_method AS VARCHAR) NOT LIKE 'A%'
              AND CAST(m.match_method AS VARCHAR) != 'B1b_position_key'
        ),
        all_cand AS (
            SELECT * FROM tier_a_cand
            UNION ALL
            SELECT * FROM poskey_cand
            UNION ALL
            SELECT * FROM other_cand
        ),
        ranked_match AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY _midx ORDER BY _fv_diff ASC, _uid ASC
                ) AS _rn_m
            FROM all_cand
        ),
        ranked_uid AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY _uid ORDER BY _fv_diff ASC, _midx ASC
                ) AS _rn_u
            FROM ranked_match WHERE _rn_m = 1
        )
        SELECT _midx, _uid FROM ranked_uid WHERE _rn_u = 1
        """

    con = duckdb.connect()

    # Load matches filtered to BDC source and wrapped CIKs
    matches_sql = f"""
    SELECT
        ROW_NUMBER() OVER () - 1 AS _midx,
        *
    FROM read_csv_auto('{matches_csv}', all_varchar=false)
    WHERE CAST(source AS VARCHAR) = 'bdc'
      AND lpad(regexp_replace(CAST(cik AS VARCHAR), '^0+', ''), 10, '0')
          IN ({', '.join(f"lpad('{c}', 10, '0')" for c in wrapper_ciks)})
    """
    con.execute(f"CREATE TEMP TABLE matches AS {matches_sql}")

    # Load unified holdings (BDC only) with a row ID
    holdings_sql = f"""
    SELECT
        ROW_NUMBER() OVER () - 1 AS _uid,
        *
    FROM read_csv_auto('{holdings_csv}', all_varchar=false)
    WHERE CAST(source AS VARCHAR) = 'bdc'
    """
    con.execute(f"CREATE TEMP TABLE holdings AS {holdings_sql}")

    match_count = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    logger.info("Loaded %d BDC matches for wrapped CIKs", match_count)

    # Map begin side
    begin_sql = _side_join_sql("begin")
    con.execute(f"CREATE TEMP TABLE begin_map AS {begin_sql}")

    # Map end side
    end_sql = _side_join_sql("end")
    con.execute(f"CREATE TEMP TABLE end_map AS {end_sql}")

    begin_mapped = con.execute("SELECT COUNT(*) FROM begin_map").fetchone()[0]
    end_mapped = con.execute("SELECT COUNT(*) FROM end_map").fetchone()[0]
    logger.info(
        "Side mapping: begin %d/%d (%.1f%%), end %d/%d (%.1f%%)",
        begin_mapped, match_count, 100 * begin_mapped / max(match_count, 1),
        end_mapped, match_count, 100 * end_mapped / max(match_count, 1),
    )

    # Build the final audit frame with both sides enriched
    audit_sql = """
    SELECT
        md5(concat_ws('|',
            COALESCE(CAST(m.cik AS VARCHAR), ''),
            COALESCE(CAST(m.position_id AS VARCHAR), ''),
            COALESCE(CAST(m.match_method AS VARCHAR), ''),
            COALESCE(CAST(m.begin_report_date AS VARCHAR), ''),
            COALESCE(CAST(m.end_report_date AS VARCHAR), ''),
            COALESCE(CAST(m.begin_issuer_name AS VARCHAR), ''),
            COALESCE(CAST(m.end_issuer_name AS VARCHAR), ''),
            COALESCE(CAST(m.begin_fair_value AS VARCHAR), ''),
            COALESCE(CAST(m.end_fair_value AS VARCHAR), '')
        )) AS sample_row_key,
        CAST(m.match_method AS VARCHAR) AS match_method,
        -- Match columns
        m.cik,
        m.entity_name,
        m.position_id,
        m.match_key,
        m.match_score,
        m.span_months,
        -- Begin-side from match
        m.begin_report_date,
        m.begin_issuer_name,
        m.begin_fair_value,
        m.begin_interest_rate,
        m.begin_principal_amount,
        -- Begin-side from unified holdings
        ub.bdc_investment_identifier AS begin_bdc_investment_identifier,
        ub.instrument_description AS begin_instrument_description,
        ub.index_classification AS begin_index_classification,
        ub.maturity_date AS begin_maturity_date,
        ub.position_key AS begin_position_key,
        ub.cusip AS begin_cusip,
        -- End-side from match
        m.end_report_date,
        m.end_issuer_name,
        m.end_fair_value,
        m.end_interest_rate,
        m.end_principal_amount,
        -- End-side from unified holdings
        ue.bdc_investment_identifier AS end_bdc_investment_identifier,
        ue.instrument_description AS end_instrument_description,
        ue.index_classification AS end_index_classification,
        ue.maturity_date AS end_maturity_date,
        ue.position_key AS end_position_key,
        ue.cusip AS end_cusip
    FROM matches m
    LEFT JOIN begin_map bm ON m._midx = bm._midx
    LEFT JOIN holdings ub ON bm._uid = ub._uid
    LEFT JOIN end_map em ON m._midx = em._midx
    LEFT JOIN holdings ue ON em._uid = ue._uid
    """

    result = con.execute(audit_sql).fetchdf()
    con.close()

    logger.info(
        "Audit frame: %d rows, begin-side enriched: %d, end-side enriched: %d",
        len(result),
        int(result["begin_bdc_investment_identifier"].notna().sum()),
        int(result["end_bdc_investment_identifier"].notna().sum()),
    )
    return result


def allocate_sample(
    stratum_sizes: dict[str, int],
    target_total: int = TARGET_SAMPLE_SIZE,
    floor_per_stratum: int = FLOOR_PER_STRATUM,
) -> dict[str, int]:
    """Allocate sample sizes with a floor per stratum + proportional remainder."""
    allocation: dict[str, int] = {}

    # Census for strata smaller than floor
    for stratum, size in sorted(stratum_sizes.items()):
        if size <= floor_per_stratum:
            allocation[stratum] = size
        else:
            allocation[stratum] = floor_per_stratum

    floor_total = sum(allocation.values())
    remaining = target_total - floor_total

    if remaining <= 0:
        return {s: n for s, n in allocation.items() if n > 0}

    # Proportional allocation of the remaining budget to non-census strata
    eligible = {
        s: stratum_sizes[s] - allocation[s]
        for s in stratum_sizes
        if stratum_sizes[s] > floor_per_stratum
    }
    eligible_total = sum(eligible.values())

    if eligible_total > 0:
        remainders: list[tuple[float, str]] = []
        for stratum, headroom in eligible.items():
            exact = remaining * headroom / eligible_total
            add = min(headroom, math.floor(exact))
            allocation[stratum] += add
            remainders.append((exact - math.floor(exact), stratum))

        # Distribute leftover from rounding
        shortfall = target_total - sum(allocation.values())
        for _, stratum in sorted(remainders, reverse=True):
            if shortfall <= 0:
                break
            headroom = stratum_sizes[stratum] - allocation[stratum]
            if headroom > 0:
                allocation[stratum] += 1
                shortfall -= 1

    return {s: n for s, n in allocation.items() if n > 0}


def stratified_sample(audit_df: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """Build a deterministic stratified review sample."""
    if audit_df.empty:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    if audit_df["sample_row_key"].duplicated().any():
        dupes = int(audit_df["sample_row_key"].duplicated().sum())
        logger.warning("Deduplicating %d duplicate sample_row_key values", dupes)
        audit_df = audit_df.drop_duplicates(subset=["sample_row_key"])

    stratum_sizes = audit_df.groupby("match_method", dropna=False).size().to_dict()
    allocation = allocate_sample(stratum_sizes)

    parts = []
    for stratum, sample_n in allocation.items():
        group = audit_df[audit_df["match_method"] == stratum].copy()
        if group.empty:
            continue
        group["_sort_key"] = group["sample_row_key"].map(
            lambda value, s=seed: hashlib.sha256(
                f"{s}|{value}".encode("utf-8")
            ).hexdigest()
        )
        parts.append(group.sort_values("_sort_key", kind="mergesort").head(sample_n))

    if not parts:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)

    sample = pd.concat(parts, ignore_index=True)
    observed_sizes = sample.groupby("match_method", dropna=False).size().to_dict()
    sample["sample_seed"] = seed
    sample["stratum_size"] = sample["match_method"].map(stratum_sizes).astype("int64")
    sample["stratum_sample_size"] = (
        sample["match_method"].map(observed_sizes).astype("int64")
    )
    sample["inclusion_weight"] = sample["stratum_size"] / sample["stratum_sample_size"]

    # Apply heuristic flags
    sample = _apply_heuristic_flags(sample)

    # Add blank review columns
    for col in ("review_label", "review_confidence", "evidence_summary"):
        sample[col] = ""

    sample = sample.drop(
        columns=[c for c in sample.columns if c.startswith("_")], errors="ignore"
    )
    for col in SAMPLE_COLUMNS:
        if col not in sample.columns:
            sample[col] = pd.NA
    return (
        sample[SAMPLE_COLUMNS]
        .sort_values(["match_method", "sample_row_key"])
        .reset_index(drop=True)
    )


def _apply_heuristic_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Compute automated error-detection flags for each sampled match."""
    df = df.copy()

    # Flag 1: Extreme FV ratio
    begin_fv = pd.to_numeric(df["begin_fair_value"], errors="coerce").abs()
    end_fv = pd.to_numeric(df["end_fair_value"], errors="coerce").abs()
    max_fv = pd.concat([begin_fv, end_fv], axis=1).max(axis=1)
    min_fv = pd.concat([begin_fv, end_fv], axis=1).min(axis=1)
    # Avoid division by zero; treat zero-min as flagged only if max > 0
    fv_ratio = max_fv / min_fv.replace(0, float("nan"))
    df["flag_fv_ratio_extreme"] = (fv_ratio > 10).fillna(False).astype(bool)

    # Flag 2: Name divergence (JW similarity of raw XBRL identifiers)
    def _jw_sim(row: pd.Series) -> float:
        a = str(row.get("begin_bdc_investment_identifier") or "").strip().lower()
        b = str(row.get("end_bdc_investment_identifier") or "").strip().lower()
        if not a or not b or a == "nan" or b == "nan":
            return float("nan")
        return _jaro_winkler_py(a, b)

    df["_jw_score"] = df.apply(_jw_sim, axis=1)
    df["flag_name_divergence"] = (df["_jw_score"] < 0.5).fillna(False).astype(bool)

    # Flag 3: Classification flip
    begin_cls = df["begin_index_classification"].fillna("").astype(str).str.strip().str.upper()
    end_cls = df["end_index_classification"].fillna("").astype(str).str.strip().str.upper()
    both_present = (begin_cls != "") & (end_cls != "")
    df["flag_classification_flip"] = (both_present & (begin_cls != end_cls)).astype(bool)

    # Flag 4: Rate discontinuity (>500 bps)
    # Rates are stored as percentages (e.g. 10.5 = 10.5%), so 500 bps = 5.0
    begin_rate = pd.to_numeric(df["begin_interest_rate"], errors="coerce")
    end_rate = pd.to_numeric(df["end_interest_rate"], errors="coerce")
    rate_diff = (begin_rate - end_rate).abs()
    df["flag_rate_discontinuity"] = (rate_diff > 5.0).fillna(False).astype(bool)

    # Flag 5: Maturity mismatch (>90 days)
    begin_mat = pd.to_datetime(df["begin_maturity_date"], errors="coerce")
    end_mat = pd.to_datetime(df["end_maturity_date"], errors="coerce")
    mat_diff = (begin_mat - end_mat).abs()
    df["flag_maturity_mismatch"] = (
        mat_diff > pd.Timedelta(days=90)
    ).fillna(False).astype(bool)

    # Flag 6: Principal ratio extreme
    begin_princ = pd.to_numeric(df["begin_principal_amount"], errors="coerce").abs()
    end_princ = pd.to_numeric(df["end_principal_amount"], errors="coerce").abs()
    max_princ = pd.concat([begin_princ, end_princ], axis=1).max(axis=1)
    min_princ = pd.concat([begin_princ, end_princ], axis=1).min(axis=1)
    princ_ratio = max_princ / min_princ.replace(0, float("nan"))
    df["flag_principal_ratio_extreme"] = (princ_ratio > 5).fillna(False).astype(bool)

    # Composite
    flag_cols = [c for c in df.columns if c.startswith("flag_") and c != "flag_count"]
    df["flag_count"] = df[flag_cols].astype(int).sum(axis=1)
    df["programmatic_verdict"] = df["flag_count"].map(
        lambda n: "likely_correct" if n == 0 else ("suspect" if n == 1 else "likely_error")
    )

    return df


def _jaro_winkler_py(s1: str, s2: str) -> float:
    """Pure-Python Jaro-Winkler similarity (0-1 scale)."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3

    # Winkler adjustment
    prefix = 0
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * 0.1 * (1 - jaro)


def compute_weighted_error_estimate(review_df: pd.DataFrame) -> dict[str, float | int]:
    """Compute weighted stratified error rate with 95% CI from reviewed rows."""
    required = {"match_method", "stratum_size", "review_label"}
    missing = required - set(review_df.columns)
    if missing:
        raise ValueError(f"Review data missing required columns: {sorted(missing)}")

    labels = review_df["review_label"].fillna("").astype(str).str.strip()
    reviewed = review_df[labels.str.len() > 0].copy()
    if reviewed.empty:
        return {
            "reviewed_rows": 0,
            "weighted_error_rate": math.nan,
            "ci95_low": math.nan,
            "ci95_high": math.nan,
        }
    reviewed["review_label"] = reviewed["review_label"].fillna("").astype(str).str.strip()
    invalid = set(reviewed["review_label"]) - set(REVIEW_LABELS)
    if invalid:
        raise ValueError(f"Invalid review_label values: {sorted(invalid)}")

    ambiguous_rows = int((reviewed["review_label"] == "ambiguous").sum())
    estimate_base = reviewed[reviewed["review_label"] != "ambiguous"].copy()
    if estimate_base.empty:
        return {
            "reviewed_rows": int(len(reviewed)),
            "estimate_rows": 0,
            "ambiguous_rows": ambiguous_rows,
            "weighted_error_rate": math.nan,
            "ci95_low": math.nan,
            "ci95_high": math.nan,
        }

    estimate_base["is_error"] = (
        estimate_base["review_label"].isin(ERROR_LABELS).astype(float)
    )
    strata = []
    for _, group in estimate_base.groupby("match_method", dropna=False):
        n_h = len(group)
        n_population = float(group["stratum_size"].iloc[0])
        p_h = float(group["is_error"].mean())
        if n_h > 1:
            s2_h = float(group["is_error"].var(ddof=1))
            finite_correction = (
                max(0.0, 1.0 - (n_h / n_population)) if n_population else 0.0
            )
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
            "weighted_error_rate": math.nan,
            "ci95_low": math.nan,
            "ci95_high": math.nan,
        }

    estimate = sum(n_h * p_h for n_h, p_h, _ in strata) / total_population
    variance = sum(((n_h / total_population) ** 2) * var_h for n_h, _, var_h in strata)
    half_width = 1.96 * math.sqrt(max(variance, 0.0))

    return {
        "reviewed_rows": int(len(reviewed)),
        "estimate_rows": int(len(estimate_base)),
        "ambiguous_rows": ambiguous_rows,
        "weighted_error_rate": estimate,
        "ci95_low": max(0.0, estimate - half_width),
        "ci95_high": min(1.0, estimate + half_width),
    }


def error_rate_by_tier(review_df: pd.DataFrame) -> pd.DataFrame:
    """Compute error rate by match_method tier from reviewed rows."""
    labels = review_df["review_label"].fillna("").astype(str).str.strip()
    reviewed = review_df[labels.str.len() > 0].copy()
    reviewed["review_label"] = reviewed["review_label"].fillna("").astype(str).str.strip()
    if reviewed.empty:
        return pd.DataFrame(
            columns=[
                "match_method",
                "reviewed_rows",
                "estimate_rows",
                "ambiguous_rows",
                "error_rows",
                "error_rate",
            ]
        )
    reviewed["is_ambiguous"] = (reviewed["review_label"] == "ambiguous").astype(int)
    reviewed["is_estimate_row"] = 1 - reviewed["is_ambiguous"]
    reviewed["is_error"] = reviewed["review_label"].isin(ERROR_LABELS).astype(int)
    grouped = (
        reviewed.groupby("match_method", dropna=False)
        .agg(
            reviewed_rows=("review_label", "size"),
            estimate_rows=("is_estimate_row", "sum"),
            ambiguous_rows=("is_ambiguous", "sum"),
            error_rows=("is_error", "sum"),
        )
        .reset_index()
    )
    grouped["error_rate"] = grouped["error_rows"] / grouped["estimate_rows"]
    grouped.loc[grouped["estimate_rows"] == 0, "error_rate"] = math.nan
    return grouped


def flag_vs_actual_correlation(review_df: pd.DataFrame) -> pd.DataFrame:
    """Compute correlation between heuristic flags and actual review labels."""
    labels = review_df["review_label"].fillna("").astype(str).str.strip()
    reviewed = review_df[
        (labels.str.len() > 0) & (labels != "ambiguous")
    ].copy()
    reviewed["review_label"] = reviewed["review_label"].fillna("").astype(str).str.strip()
    if reviewed.empty:
        return pd.DataFrame(
            columns=["flag", "flag_true_count", "flag_true_error_count",
                      "flag_true_error_rate", "flag_false_count",
                      "flag_false_error_count", "flag_false_error_rate"]
        )

    reviewed["is_error"] = reviewed["review_label"].isin(ERROR_LABELS).astype(int)
    flag_cols = [c for c in reviewed.columns if c.startswith("flag_") and c != "flag_count"]

    rows = []
    for flag in flag_cols:
        flagged = reviewed[reviewed[flag].astype(bool)]
        unflagged = reviewed[~reviewed[flag].astype(bool)]
        rows.append({
            "flag": flag,
            "flag_true_count": len(flagged),
            "flag_true_error_count": int(flagged["is_error"].sum()) if len(flagged) else 0,
            "flag_true_error_rate": (
                float(flagged["is_error"].mean()) if len(flagged) else math.nan
            ),
            "flag_false_count": len(unflagged),
            "flag_false_error_count": int(unflagged["is_error"].sum()) if len(unflagged) else 0,
            "flag_false_error_rate": (
                float(unflagged["is_error"].mean()) if len(unflagged) else math.nan
            ),
        })
    return pd.DataFrame(rows)


def render_review_summary(review_df: pd.DataFrame) -> str:
    """Render a completed position-match spot-check review as markdown."""
    estimate = compute_weighted_error_estimate(review_df)
    by_tier = error_rate_by_tier(review_df)
    flag_corr = flag_vs_actual_correlation(review_df)
    labels = (
        review_df["review_label"]
        .fillna("")
        .replace("", "unreviewed")
        .value_counts()
        .reset_index()
    )
    labels.columns = ["review_label", "rows"]

    def pct(value: float) -> str:
        if pd.isna(value):
            return "n/a"
        return f"{value:.1%}"

    def table(frame: pd.DataFrame) -> str:
        if frame.empty:
            return "(no data)"
        safe = frame.copy()
        for col in safe.columns:
            safe[col] = safe[col].map(lambda v: "" if pd.isna(v) else str(v))
        header = "| " + " | ".join(map(str, safe.columns)) + " |"
        separator = "| " + " | ".join("---" for _ in safe.columns) + " |"
        body = [
            "| " + " | ".join(row) + " |"
            for row in safe.astype(str).values.tolist()
        ]
        return "\n".join([header, separator, *body])

    lines = [
        "# Position matching spot-check review",
        "",
        "Manual review of `data/output/position_match_spot_check_sample.csv`.",
        "",
        "## Overall estimate",
        "",
        f"- Reviewed rows: {estimate['reviewed_rows']}",
        f"- Rows in point estimate: {estimate.get('estimate_rows', 'n/a')}",
        f"- Ambiguous rows excluded: {estimate.get('ambiguous_rows', 'n/a')}",
        f"- Weighted error rate: {pct(float(estimate['weighted_error_rate']))}",
        f"- 95% CI: {pct(float(estimate['ci95_low']))} to {pct(float(estimate['ci95_high']))}",
        "",
        f"Error labels: {', '.join(sorted(ERROR_LABELS))}",
        "",
        "## Label counts",
        "",
        table(labels),
        "",
        "## Error rate by tier",
        "",
        table(by_tier),
        "",
        "## Flag vs actual error correlation",
        "",
        table(flag_corr),
        "",
    ]
    return "\n".join(lines)


def print_pre_review_summary(sample: pd.DataFrame) -> None:
    """Print automated pre-review summary to stdout."""
    n = len(sample)
    print(f"\n{'='*60}")
    print(f"POSITION MATCH SPOT-CHECK: PRE-REVIEW SUMMARY")
    print(f"{'='*60}")
    print(f"\nTotal sampled matches: {n}")

    # Verdict distribution
    if "programmatic_verdict" in sample.columns:
        verdict_counts = sample["programmatic_verdict"].value_counts()
        print(f"\nProgrammatic verdict distribution:")
        for verdict in ["likely_correct", "suspect", "likely_error"]:
            count = verdict_counts.get(verdict, 0)
            pct = 100 * count / n if n else 0
            print(f"  {verdict:20s}: {count:4d} ({pct:5.1f}%)")

    # Per-tier flag rates
    flag_cols = [
        c for c in sample.columns if c.startswith("flag_") and c != "flag_count"
    ]
    if flag_cols:
        print(f"\nPer-tier flag rates:")
        tiers = [t for t in TIER_ORDER if t in sample["match_method"].values]
        header = f"  {'Tier':25s}" + "".join(f" {f.replace('flag_', ''):>14s}" for f in flag_cols)
        print(header)
        for tier in tiers:
            tier_rows = sample[sample["match_method"] == tier]
            nt = len(tier_rows)
            rates = []
            for f in flag_cols:
                flagged = int(tier_rows[f].astype(bool).sum())
                rate = 100 * flagged / nt if nt else 0
                rates.append(f"{flagged:3d} ({rate:4.1f}%)")
            print(f"  {tier:25s}" + "".join(f" {r:>14s}" for r in rates))

    # Per-tier sample allocation
    print(f"\nSample allocation by tier:")
    for tier in TIER_ORDER:
        tier_rows = sample[sample["match_method"] == tier]
        if tier_rows.empty:
            continue
        nt = len(tier_rows)
        pop = int(tier_rows["stratum_size"].iloc[0])
        print(f"  {tier:25s}: {nt:4d} / {pop:6d} (weight {pop/nt:.1f}x)")

    print(f"\n{'='*60}\n")


def write_sample(
    matches_path: Path = config.POSITION_MATCHES_FILE,
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
    output_path: Path = OUTPUT_FILE,
) -> pd.DataFrame:
    """Generate and write the spot-check sample."""
    audit_df = build_audit_frame(matches_path, holdings_path)
    sample = stratified_sample(audit_df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(output_path, index=False)
    logger.info("Wrote %d sampled rows to %s", len(sample), output_path)
    return sample


def write_review_summary(
    review_df: pd.DataFrame,
    output_path: Path = REVIEW_SUMMARY_FILE,
) -> str:
    """Write markdown summary for a completed manual review."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = render_review_summary(review_df)
    output_path.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matches", type=Path, default=config.POSITION_MATCHES_FILE,
        help="Path to position_matches.csv",
    )
    parser.add_argument(
        "--holdings", type=Path, default=config.UNIFIED_HOLDINGS_FILE,
        help="Path to private_markets_holdings.csv",
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_FILE,
        help="Output path for the sample CSV",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show strata sizes only, do not write output",
    )
    parser.add_argument(
        "--summarize", action="store_true",
        help="Compute review summary from labeled sample",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.summarize:
        if not args.output.exists():
            logger.error("Sample file not found: %s", args.output)
            return 1
        review_df = pd.read_csv(args.output)
        review_df["review_label"] = review_df["review_label"].fillna("").astype(str)
        reviewed_count = int(
            (review_df["review_label"].str.strip().str.len() > 0).sum()
        )
        if reviewed_count == 0:
            logger.error("No reviewed rows found. Fill in review_label column first.")
            return 1
        text = write_review_summary(review_df, REVIEW_SUMMARY_FILE)
        print(text)
        logger.info("Wrote review summary to %s", REVIEW_SUMMARY_FILE)
        return 0

    if args.dry_run:
        audit_df = build_audit_frame(args.matches, args.holdings)
        stratum_sizes = (
            audit_df.groupby("match_method", dropna=False).size().to_dict()
        )
        total = sum(stratum_sizes.values())
        allocation = allocate_sample(stratum_sizes)

        print(f"\nDry run: {total:,} total matches across {len(stratum_sizes)} tiers\n")
        print(f"{'Tier':25s} {'Population':>10s} {'Sample':>8s} {'Weight':>8s}")
        print("-" * 55)
        for tier in TIER_ORDER:
            if tier in stratum_sizes:
                pop = stratum_sizes[tier]
                samp = allocation.get(tier, 0)
                weight = f"{pop / samp:.1f}x" if samp else "n/a"
                print(f"{tier:25s} {pop:10,d} {samp:8d} {weight:>8s}")
        print("-" * 55)
        sample_total = sum(allocation.values())
        print(f"{'TOTAL':25s} {total:10,d} {sample_total:8d}")
        print()
        return 0

    # Default: generate sample
    sample = write_sample(args.matches, args.holdings, args.output)
    print_pre_review_summary(sample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
