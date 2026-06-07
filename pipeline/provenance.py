"""Opt-in provenance diagnostic artifacts.

Three artifacts wire up the full chain: production datapoint -> classification
rules -> raw XBRL facts.

1. holdings_wrapper_provenance.csv -- per-row wrapper classification for every
   BDC row in unified holdings.
2. xbrl_concept_map.json -- static inversion of CONCEPT_MAP from bdc_filings.
3. position_provenance_index.csv -- full-chain provenance for each
   position_returns row.

All artifacts are written to data/output/provenance/ by default and are
excluded from the standard rebuild-all path.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.config import (
    HOLDINGS_WRAPPER_PROVENANCE_FILE,
    POSITION_PROVENANCE_INDEX_FILE,
    POSITION_RETURNS_FILE,
    PROVENANCE_DIR,
    UNIFIED_HOLDINGS_FILE,
    XBRL_CONCEPT_MAP_FILE,
)

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# 1. Holdings wrapper provenance
# -------------------------------------------------------------------------


def build_holdings_wrapper_provenance(
    unified_df: pd.DataFrame | None = None,
    output_path: Path | None = None,
) -> pd.DataFrame:
    """Re-run wrapper classification on BDC rows and emit join-key + wrapper columns.

    Parameters
    ----------
    unified_df : DataFrame, optional
        Pre-loaded unified holdings.  Read from disk if not provided.
    output_path : Path, optional
        Override destination (used by tests with tmp_path).

    Returns
    -------
    DataFrame with join key (cik, report_date, bdc_investment_identifier)
    plus all WRAPPER_COLUMNS.
    """
    from pipeline.bdc_xbrl_wrapper import WRAPPER_COLUMNS, add_bdc_xbrl_wrapper_columns

    if unified_df is None:
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    # Filter to BDC rows with a non-empty identifier
    mask = (
        unified_df.get("source", pd.Series(dtype=str)).eq("bdc")
        & unified_df.get("bdc_investment_identifier", pd.Series(dtype=str)).fillna("").ne("")
    )
    bdc_df = unified_df.loc[mask].copy()

    if bdc_df.empty:
        join_cols = ["cik", "report_date", "bdc_investment_identifier"]
        return pd.DataFrame(columns=join_cols + list(WRAPPER_COLUMNS))

    # Drop any pre-existing wrapper columns so add_bdc_xbrl_wrapper_columns
    # starts fresh
    for col in WRAPPER_COLUMNS:
        if col in bdc_df.columns:
            bdc_df.drop(columns=col, inplace=True)

    wrapped = add_bdc_xbrl_wrapper_columns(
        bdc_df,
        identifier_col="bdc_investment_identifier",
        cik_col="cik",
    )

    keep_cols = ["cik", "report_date", "bdc_investment_identifier"] + list(WRAPPER_COLUMNS)
    result = wrapped[keep_cols].copy()

    dest = output_path or HOLDINGS_WRAPPER_PROVENANCE_FILE
    if output_path is None:
        PROVENANCE_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(dest, index=False)
    logger.info(
        "Holdings wrapper provenance: %d rows written to %s",
        len(result),
        dest,
    )
    return result


# -------------------------------------------------------------------------
# 2. XBRL concept map
# -------------------------------------------------------------------------


def build_xbrl_concept_map(
    output_path: Path | None = None,
) -> dict[str, list[str]]:
    """Invert CONCEPT_MAP from bdc_filings: output column -> concept patterns.

    Returns a dict keyed by output column name (e.g. "fair_value"), where each
    value is the list of XBRL concept substrings that map to it, in the
    priority order they appear in CONCEPT_MAP (first match wins at extraction
    time).
    """
    from pipeline.bdc_filings import CONCEPT_MAP

    inverted: dict[str, list[str]] = {}
    for concept_pattern, output_col in CONCEPT_MAP:
        inverted.setdefault(output_col, []).append(concept_pattern)

    dest = output_path or XBRL_CONCEPT_MAP_FILE
    if output_path is None:
        PROVENANCE_DIR.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(inverted, fh, indent=2)
    logger.info("XBRL concept map: %d output columns written to %s", len(inverted), dest)
    return inverted


# -------------------------------------------------------------------------
# 3. Position provenance index
# -------------------------------------------------------------------------

_QUARTER_TO_DATE_SQL = """
    CAST(
        CAST(CAST(LEFT(end_quarter, 4) AS INT) AS VARCHAR)
        || '-'
        || CASE RIGHT(end_quarter, 1)
            WHEN '1' THEN '03-31'
            WHEN '2' THEN '06-30'
            WHEN '3' THEN '09-30'
            WHEN '4' THEN '12-31'
           END
    AS VARCHAR)
"""


def build_position_provenance_index(
    position_returns_df: pd.DataFrame | None = None,
    unified_df: pd.DataFrame | None = None,
    wrapper_provenance_df: pd.DataFrame | None = None,
    output_path: Path | None = None,
) -> pd.DataFrame:
    """Build denormalized provenance for each position_returns row.

    Joins position_returns -> unified_holdings -> wrapper_provenance to carry
    accession_number, bdc_dimensions_raw, wrapper_rule_id, etc. through to a
    single lookup table.

    Parameters
    ----------
    position_returns_df : DataFrame, optional
        Pre-loaded position returns.  Read from disk if not provided.
    unified_df : DataFrame, optional
        Pre-loaded unified holdings.  Read from disk if not provided.
    wrapper_provenance_df : DataFrame, optional
        Pre-loaded wrapper provenance.  Built inline if not provided.
    output_path : Path, optional
        Override destination.

    Returns
    -------
    DataFrame with one row per (position_id, end_quarter).
    """
    if position_returns_df is None:
        position_returns_df = pd.read_csv(POSITION_RETURNS_FILE, dtype=str)
    if unified_df is None:
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    if wrapper_provenance_df is None:
        wrapper_provenance_df = build_holdings_wrapper_provenance(
            unified_df=unified_df,
            output_path=output_path.parent / "holdings_wrapper_provenance.csv"
            if output_path
            else None,
        )

    con = duckdb.connect()
    con.register("pos_returns", position_returns_df)
    con.register("unified", unified_df)
    con.register("wrapper_prov", wrapper_provenance_df)

    sql = f"""
    WITH pr_with_date AS (
        SELECT
            *,
            {_QUARTER_TO_DATE_SQL} AS _report_date
        FROM pos_returns
    ),
    joined AS (
        SELECT
            pr.position_id,
            pr.cik,
            pr.entity_name,
            pr.end_quarter,
            pr.issuer_name,
            pr.index_classification,
            pr.asset_category,
            uh.accession_number,
            uh.report_date,
            uh.source,
            uh.bdc_investment_identifier,
            uh.bdc_dimensions_raw,
            uh.position_key,
            wp.wrapper_rule_id,
            wp.wrapper_disposition,
            wp.wrapper_family,
            wp.wrapper_signature_status,
            wp.wrapper_version,
            ROW_NUMBER() OVER (
                PARTITION BY pr.position_id, pr.end_quarter
                ORDER BY uh.accession_number NULLS LAST
            ) AS _rn
        FROM pr_with_date pr
        LEFT JOIN unified uh
            ON pr.position_id = uh.position_id
           AND pr.cik = uh.cik
           AND uh.report_date = pr._report_date
        LEFT JOIN wrapper_prov wp
            ON uh.cik = wp.cik
           AND uh.report_date = wp.report_date
           AND uh.bdc_investment_identifier = wp.bdc_investment_identifier
    )
    SELECT
        position_id,
        cik,
        entity_name,
        end_quarter,
        issuer_name,
        index_classification,
        asset_category,
        accession_number,
        report_date,
        source,
        bdc_investment_identifier,
        bdc_dimensions_raw,
        position_key,
        wrapper_rule_id,
        wrapper_disposition,
        wrapper_family,
        wrapper_signature_status,
        wrapper_version
    FROM joined
    WHERE _rn = 1
    ORDER BY position_id, end_quarter
    """

    result = con.execute(sql).fetchdf()
    con.close()

    # Add filing_path column for BDC rows
    def _filing_path(row: pd.Series) -> str:
        acc = row.get("accession_number")
        cik = row.get("cik")
        if pd.isna(acc) or pd.isna(cik) or not acc or not cik:
            return ""
        acc_no_dashes = str(acc).replace("-", "")
        return f"data/raw/filings/bdc_xbrl/{cik}/{acc_no_dashes}/"

    result["filing_path"] = result.apply(_filing_path, axis=1)

    dest = output_path or POSITION_PROVENANCE_INDEX_FILE
    if output_path is None:
        PROVENANCE_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(dest, index=False)
    logger.info(
        "Position provenance index: %d rows written to %s",
        len(result),
        dest,
    )
    return result
