"""Heuristic triage for position match quality.

Applies five checks to C/D/E match pairs, joining each side back to
holdings to retrieve classification, maturity, instrument description,
and interest rate.  Returns the input DataFrame augmented with boolean
flag columns and a composite triage_flags count.

The join pattern mirrors oracle_checks.check_J07_hard_gate_rejection_audit.
"""

from __future__ import annotations

import logging
import re as _re

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# Default tiers to triage
DEFAULT_TRIAGE_TIERS = {"C_normalized_name", "D_fuzzy", "E_entity_fingerprint"}

# Flag severity levels
_SEVERITY = {
    "flag_classification_flip": "high",
    "flag_subtype_mismatch": "high",
    "flag_maturity_gap": "medium",
    "flag_fv_ratio_extreme": "medium",
    "flag_rate_discontinuity": "low",
}

FLAG_COLUMNS = sorted(_SEVERITY.keys())


def parse_instrument_subtype(description: str) -> str:
    """Parse instrument sub-type from description text.

    Returns one of: REVOLVER, DDTL, TERM_LOAN, WARRANT, EQUITY, or
    empty string if unclassifiable.  Mirrors the J07 _parse_subtype logic.
    """
    if not description:
        return ""
    d = str(description)
    if _re.search(r"(?i)\b(?:revolv(?:er|ing)|rcf|revolving\s+credit)\b", d):
        return "REVOLVER"
    if _re.search(r"(?i)\b(?:ddtl|delayed\s+draw)\b", d):
        return "DDTL"
    if _re.search(r"(?i)\b(?:term\s+loan|tl[a-d]?\b)", d):
        return "TERM_LOAN"
    if _re.search(r"(?i)\b(?:warrants?)\b", d):
        return "WARRANT"
    if _re.search(
        r"(?i)\b(?:common\s+(?:stock|equity|units?)"
        r"|preferred\s+(?:stock|equity|units?)"
        r"|membership\s+interest|llc\s+interest"
        r"|equity\s+interest|class\s+[a-c]\b"
        r"|ordinary\s+shares)\b",
        d,
    ):
        return "EQUITY"
    return ""


def triage_match_quality(
    matches_df: pd.DataFrame,
    holdings_df: pd.DataFrame,
    *,
    cik: str | None = None,
    tiers: set[str] | None = None,
) -> pd.DataFrame:
    """Triage C/D/E match pairs for quality issues.

    Parameters
    ----------
    matches_df : pd.DataFrame
        Position match pairs (output of match_positions).
    holdings_df : pd.DataFrame
        Unified holdings DataFrame.
    cik : str, optional
        Filter to a single CIK.
    tiers : set[str], optional
        Match methods to triage.  Defaults to C/D/E tiers.

    Returns
    -------
    pd.DataFrame
        Input rows for the requested tiers, augmented with boolean flag
        columns and a composite ``triage_flags`` count.
    """
    if matches_df is None or matches_df.empty:
        return pd.DataFrame()
    if holdings_df is None or holdings_df.empty:
        return pd.DataFrame()

    triage_tiers = tiers if tiers is not None else DEFAULT_TRIAGE_TIERS

    required_m = {
        "cik", "match_method", "begin_report_date", "end_report_date",
        "begin_issuer_name", "end_issuer_name",
        "begin_fair_value", "end_fair_value",
    }
    if not required_m.issubset(matches_df.columns):
        logger.warning("triage_match_quality: missing columns in matches_df")
        return pd.DataFrame()

    required_h = {"cik", "report_date", "issuer_name", "source"}
    if not required_h.issubset(holdings_df.columns):
        logger.warning("triage_match_quality: missing columns in holdings_df")
        return pd.DataFrame()

    # Filter to target tiers and CIK
    df = matches_df.copy()
    df["cik"] = df["cik"].astype(str).str.zfill(10)
    df = df[df["match_method"].isin(triage_tiers)].copy()

    if cik is not None:
        cik_norm = str(cik).replace(" ", "").zfill(10)
        df = df[df["cik"] == cik_norm].copy()

    if df.empty:
        return pd.DataFrame()

    df = df.reset_index(drop=True)
    df["_idx"] = range(len(df))

    # Prepare holdings subset
    h = holdings_df.copy()
    h["cik"] = h["cik"].astype(str).str.zfill(10)
    h_cols = ["cik", "report_date", "issuer_name", "source", "fair_value"]
    for col in ("index_classification", "maturity_date",
                "instrument_description", "interest_rate", "basis_spread"):
        if col in h.columns:
            h_cols.append(col)
    h = h[h_cols].copy()
    h["report_date"] = h["report_date"].astype(str)
    h["issuer_name"] = h["issuer_name"].astype(str)

    # Join both sides to holdings via DuckDB (same pattern as J07)
    con = duckdb.connect()
    con.register("triage_m", df)
    con.register("h", h)

    for side in ("begin", "end"):
        extra_cols = []
        if "index_classification" in h.columns:
            extra_cols.append(f"h.index_classification AS {side}_ic")
        if "maturity_date" in h.columns:
            extra_cols.append(f"CAST(h.maturity_date AS VARCHAR) AS {side}_maturity")
        if "instrument_description" in h.columns:
            extra_cols.append(
                f"CAST(h.instrument_description AS VARCHAR) AS {side}_inst_desc"
            )
        if "interest_rate" in h.columns:
            extra_cols.append(
                f"TRY_CAST(h.interest_rate AS DOUBLE) AS {side}_rate"
            )
        if "basis_spread" in h.columns:
            extra_cols.append(
                f"TRY_CAST(h.basis_spread AS DOUBLE) AS {side}_spread"
            )

        extra_select = ", " + ", ".join(extra_cols) if extra_cols else ""

        sql = f"""
        SELECT m._idx{extra_select}
        FROM triage_m m
        LEFT JOIN h
          ON m.cik = h.cik AND h.source = 'bdc'
          AND CAST(m.{side}_report_date AS VARCHAR) = CAST(h.report_date AS VARCHAR)
          AND CAST(m.{side}_issuer_name AS VARCHAR) = CAST(h.issuer_name AS VARCHAR)
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY m._idx
          ORDER BY ABS(COALESCE(TRY_CAST(m.{side}_fair_value AS DOUBLE), 0)
                       - COALESCE(TRY_CAST(h.fair_value AS DOUBLE), 0)) ASC
        ) = 1
        """
        side_df = con.execute(sql).fetchdf()
        df = df.merge(side_df, on="_idx", how="left")

    con.close()

    # Fill NaN for joined columns
    for col in ("begin_ic", "end_ic", "begin_maturity", "end_maturity",
                "begin_inst_desc", "end_inst_desc"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
        else:
            df[col] = ""

    for col in ("begin_rate", "end_rate", "begin_spread", "end_spread"):
        if col not in df.columns:
            df[col] = float("nan")

    # ---- Apply five heuristic checks ----

    # 1. Classification flip
    both_ic = df["begin_ic"].str.strip().ne("") & df["end_ic"].str.strip().ne("")
    df["flag_classification_flip"] = both_ic & (df["begin_ic"] != df["end_ic"])

    # 2. Instrument sub-type mismatch
    df["_b_subtype"] = df["begin_inst_desc"].apply(parse_instrument_subtype)
    df["_e_subtype"] = df["end_inst_desc"].apply(parse_instrument_subtype)
    both_sub = df["_b_subtype"].ne("") & df["_e_subtype"].ne("")
    df["flag_subtype_mismatch"] = both_sub & (df["_b_subtype"] != df["_e_subtype"])

    # 3. Maturity gap > 365 days
    df["_b_mat"] = pd.to_datetime(df["begin_maturity"], errors="coerce")
    df["_e_mat"] = pd.to_datetime(df["end_maturity"], errors="coerce")
    both_mat = df["_b_mat"].notna() & df["_e_mat"].notna()
    mat_gap = (df["_b_mat"] - df["_e_mat"]).abs().dt.days
    df["flag_maturity_gap"] = both_mat & (mat_gap > 365)

    # 4. FV ratio extreme (>10x)
    b_fv = pd.to_numeric(df["begin_fair_value"], errors="coerce").abs()
    e_fv = pd.to_numeric(df["end_fair_value"], errors="coerce").abs()
    min_fv = pd.concat([b_fv, e_fv], axis=1).min(axis=1)
    max_fv = pd.concat([b_fv, e_fv], axis=1).max(axis=1)
    both_fv = (min_fv > 0) & max_fv.notna()
    fv_ratio = max_fv / min_fv.replace(0, float("nan"))
    df["flag_fv_ratio_extreme"] = both_fv & (fv_ratio > 10)

    # 5. Rate discontinuity (>5 pct pts)
    # Use basis_spread if available, fall back to interest_rate
    b_rate = pd.to_numeric(df["begin_spread"], errors="coerce")
    e_rate = pd.to_numeric(df["end_spread"], errors="coerce")
    # Fall back to interest_rate where spread is missing
    b_rate_ir = pd.to_numeric(df["begin_rate"], errors="coerce")
    e_rate_ir = pd.to_numeric(df["end_rate"], errors="coerce")
    b_rate = b_rate.fillna(b_rate_ir)
    e_rate = e_rate.fillna(e_rate_ir)
    both_rate = b_rate.notna() & e_rate.notna()
    rate_diff = (b_rate - e_rate).abs()
    df["flag_rate_discontinuity"] = both_rate & (rate_diff > 5.0)

    # Composite count and severity
    df["triage_flags"] = sum(
        df[col].astype(int) for col in FLAG_COLUMNS
    )
    df["triage_severity"] = ""
    for col in FLAG_COLUMNS:
        mask = df[col]
        sev = _SEVERITY[col]
        # Promote severity: high > medium > low
        if sev == "high":
            df.loc[mask, "triage_severity"] = "high"
        elif sev == "medium":
            df.loc[
                mask & (df["triage_severity"] != "high"), "triage_severity"
            ] = "medium"
        elif sev == "low":
            df.loc[
                mask & ~df["triage_severity"].isin(["high", "medium"]),
                "triage_severity",
            ] = "low"

    # Drop internal columns
    drop_cols = [
        "_idx", "_b_subtype", "_e_subtype", "_b_mat", "_e_mat",
        "begin_ic", "end_ic", "begin_maturity", "end_maturity",
        "begin_inst_desc", "end_inst_desc",
        "begin_rate", "end_rate", "begin_spread", "end_spread",
    ]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])

    # Sort: flagged rows first (descending flags), then by FV descending
    df = df.sort_values(
        ["triage_flags", "begin_fair_value"],
        ascending=[False, False],
        key=lambda s: pd.to_numeric(s, errors="coerce") if s.name == "begin_fair_value" else s,
    ).reset_index(drop=True)

    return df
