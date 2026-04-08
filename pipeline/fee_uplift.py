"""Compute per-CIK fee uplift from fund-level income vs portfolio coupon yields.

Fee uplift = (total income yield) - (median coupon + PIK yield).
This captures origination fees, amendment fees, prepayment penalties,
and OID accretion that are visible in income statements but not in the
schedule-of-investments coupon fields.

For N-PORT filers (no income statement), the cross-sectional BDC median
uplift is used as a proxy.

Public API
----------
compute_fee_uplift(fund_income_df=None, unified_df=None) -> pd.DataFrame
"""

import logging
import time
from typing import Optional

import duckdb
import pandas as pd

from pipeline.config import (
    BDC_FUND_INCOME_FILE,
    FEE_UPLIFT_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# Guard rails
MAX_UPLIFT_PCT = 5.0    # Cap individual uplift; above this reverts to cross-sectional median
MIN_UPLIFT_PCT = 0.0    # Negative uplift means coupon exceeds income (data issue)
MAX_CROSS_SECTIONAL = 5.0  # Exclude outliers from cross-sectional median computation


def compute_fee_uplift(
    fund_income_df: Optional[pd.DataFrame] = None,
    unified_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Compute per-CIK per-quarter fee uplift.

    Parameters
    ----------
    fund_income_df : DataFrame, optional
        Output of extract_bdc_fund_income(). Loaded from disk if None.
    unified_df : DataFrame, optional
        Unified holdings. Loaded from disk if None.

    Returns
    -------
    DataFrame with columns:
        cik, quarter, total_income_yield, median_all_in_coupon,
        fee_uplift_pct, cross_sectional_median_uplift, effective_uplift
    """
    t0 = time.time()

    # Load from disk if not provided
    if fund_income_df is None:
        if not BDC_FUND_INCOME_FILE.exists():
            logger.warning("No fund income file at %s -- returning empty uplift",
                          BDC_FUND_INCOME_FILE)
            return pd.DataFrame(columns=[
                "cik", "quarter", "total_income_yield",
                "median_all_in_coupon", "fee_uplift_pct",
                "cross_sectional_median_uplift", "effective_uplift",
            ])
        fund_income_df = pd.read_csv(BDC_FUND_INCOME_FILE, dtype=str)
        logger.info("Loaded fund income: %d rows", len(fund_income_df))

    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            logger.warning("No unified holdings at %s", UNIFIED_HOLDINGS_FILE)
            return pd.DataFrame(columns=[
                "cik", "quarter", "total_income_yield",
                "median_all_in_coupon", "fee_uplift_pct",
                "cross_sectional_median_uplift", "effective_uplift",
            ])
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
        logger.info("Loaded unified holdings: %d rows", len(unified_df))

    if fund_income_df.empty:
        logger.warning("Empty fund income -- returning empty uplift")
        return pd.DataFrame(columns=[
            "cik", "quarter", "total_income_yield",
            "median_all_in_coupon", "fee_uplift_pct",
            "cross_sectional_median_uplift", "effective_uplift",
        ])

    con = duckdb.connect()
    con.register("fund_income", fund_income_df)
    con.register("unified", unified_df)

    # Both fund_income and unified now use 10-digit zero-padded CIKs.
    sql = f"""
    WITH
    -- Total portfolio FV (ALL positions, not just DL) -- income stmt covers whole fund
    total_portfolio_fv AS (
        SELECT
            CAST(cik AS VARCHAR) AS cik,
            CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR) || 'q' ||
                CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) AS quarter,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
        FROM unified
        WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
          AND TRY_CAST(fair_value AS DOUBLE) > 0
        GROUP BY 1, 2
        HAVING total_fv > 0
    ),
    -- DL-only coupon median (the benchmark we subtract)
    dl_coupon_median AS (
        SELECT
            CAST(cik AS VARCHAR) AS cik,
            CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR) || 'q' ||
                CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) AS quarter,
            MEDIAN(
                COALESCE(TRY_CAST(interest_rate AS DOUBLE), 0)
                + COALESCE(TRY_CAST(pik_rate AS DOUBLE), 0)
            ) AS median_all_in_coupon
        FROM unified
        WHERE index_classification = 'DIRECT_LENDING'
          AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
          AND TRY_CAST(fair_value AS DOUBLE) > 0
        GROUP BY 1, 2
    ),
    -- Combined: total FV + DL coupon (inner join = only CIKs with DL positions)
    portfolio_fv AS (
        SELECT
            t.cik,
            t.quarter,
            t.total_fv,
            d.median_all_in_coupon
        FROM total_portfolio_fv t
        JOIN dl_coupon_median d ON t.cik = d.cik AND t.quarter = d.quarter
    ),
    -- Annualized income: fund_income records are already quarterly-scaled
    -- by _derive_quarterly_income(), so annualize by multiplying by 4.
    annualized_income AS (
        SELECT
            CAST(cik AS VARCHAR) AS cik,
            CAST(report_quarter AS VARCHAR) AS quarter,
            TRY_CAST(total_investment_income AS DOUBLE) * 4.0
                AS annualized_income
        FROM fund_income
        WHERE TRY_CAST(total_investment_income AS DOUBLE) IS NOT NULL
          AND TRY_CAST(total_investment_income AS DOUBLE) > 0
    ),
    per_cik_uplift AS (
        SELECT
            p.cik,
            p.quarter,
            ai.annualized_income / p.total_fv * 100.0 AS total_income_yield,
            p.median_all_in_coupon,
            (ai.annualized_income / p.total_fv * 100.0) - p.median_all_in_coupon
                AS fee_uplift_pct
        FROM portfolio_fv p
        JOIN annualized_income ai
          ON p.cik = ai.cik AND p.quarter = ai.quarter
        WHERE ai.annualized_income IS NOT NULL
    ),
    cross_sectional AS (
        SELECT
            quarter,
            MEDIAN(fee_uplift_pct) AS cross_sectional_median_uplift
        FROM per_cik_uplift
        WHERE fee_uplift_pct >= 0 AND fee_uplift_pct <= {MAX_CROSS_SECTIONAL}
        GROUP BY quarter
    )
    SELECT
        u.cik,
        u.quarter,
        u.total_income_yield,
        u.median_all_in_coupon,
        u.fee_uplift_pct,
        cs.cross_sectional_median_uplift,
        CASE
            WHEN u.fee_uplift_pct >= {MIN_UPLIFT_PCT}
                 AND u.fee_uplift_pct <= {MAX_UPLIFT_PCT}
            THEN u.fee_uplift_pct
            ELSE cs.cross_sectional_median_uplift
        END AS effective_uplift
    FROM per_cik_uplift u
    LEFT JOIN cross_sectional cs ON u.quarter = cs.quarter
    ORDER BY u.cik, u.quarter
    """

    result = con.execute(sql).fetchdf()
    con.close()

    logger.info("Fee uplift: %d rows", len(result))

    if len(result) > 0:
        valid = result["effective_uplift"].notna()
        if valid.any():
            median_uplift = result.loc[valid, "effective_uplift"].median()
            logger.info("  Median effective uplift: %.1f%%", median_uplift)

        # Log per-year summary
        result["_year"] = result["quarter"].str[:4]
        for year in sorted(result["_year"].unique()):
            yr_data = result[result["_year"] == year]
            yr_median = yr_data["effective_uplift"].median()
            logger.info("  %s: median uplift %.1f%%, %d CIK-quarters",
                         year, yr_median if pd.notna(yr_median) else 0,
                         len(yr_data))
        result = result.drop(columns=["_year"])

    # Save
    result.to_csv(FEE_UPLIFT_FILE, index=False)
    elapsed = time.time() - t0
    logger.info("Fee uplift computation complete in %.1f s", elapsed)

    return result
