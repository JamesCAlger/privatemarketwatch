"""Index returns -- compute position-level total returns and aggregate to
quarterly index-level returns with chain-linked index levels.

Total return = capital return + income return (for lending) or
               capital return + distribution (for fund vehicles).

All data manipulation uses DuckDB SQL CTEs.
"""

import logging
import time
from typing import Optional, Tuple

import duckdb
import pandas as pd

from pipeline.config import (
    INDEX_RETURNS_FILE,
    OUTPUT_DIR,
    POSITION_MATCHES_FILE,
    POSITION_RETURNS_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# All-in-coupon classification from the FRED-anchored rate-convention gate.
# For these CIKs interest_rate already includes disclosed PIK, so the additive
# PIK term in the income formula would double-count. (Shadow diagnostic input;
# the classification should eventually graduate to first-class fund metadata.)
RATE_CONVENTION_GATE_FILE = OUTPUT_DIR / "shadow" / "bdc_rate_convention_gate.csv"


def _load_all_in_ciks() -> pd.DataFrame:
    """Return a one-column ('cik', 10-digit) frame of all_in_coupon filers.

    Empty (no suppression) if the gate output is absent, so production never
    hard-depends on the shadow artifact being present.
    """
    if RATE_CONVENTION_GATE_FILE.exists():
        g = pd.read_csv(RATE_CONVENTION_GATE_FILE, dtype=str)
        allin = g.loc[g["status"] == "all_in_coupon", ["cik"]].copy()
        allin["cik"] = allin["cik"].str.zfill(10)
        logger.info("Loaded %d all_in_coupon filers from %s (PIK suppressed in income)",
                    len(allin), RATE_CONVENTION_GATE_FILE.name)
        return allin
    logger.info("No rate-convention gate output; additive PIK applied to all filers")
    return pd.DataFrame(columns=["cik"])


# Minimum constituents for a valid index quarter
MIN_CONSTITUENTS = 10

# Outlier guards
MAX_RETURN = 2.0     # 200% -- above this, set to NULL
MIN_RETURN = -0.99   # -99% -- cap at this floor
MAX_INCOME_RETURN = 0.25  # 25% quarterly (~100% annualised) income cap

# Minimum beginning fair value for index inclusion (filters micro-positions)
MIN_BEGIN_FV = 100_000


def compute_returns(
    matches_df: Optional[pd.DataFrame] = None,
    fee_uplift_df: Optional[pd.DataFrame] = None,
    unified_pik_df: Optional[pd.DataFrame] = None,
    all_in_ciks_df: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Compute position-level and index-level returns from matched pairs.

    Parameters
    ----------
    matches_df : DataFrame, optional
        Output of match_positions(). Loaded from disk if None.
    fee_uplift_df : DataFrame, optional
        Per-CIK/quarter fee uplift. Loaded from disk if file exists and None.
    unified_pik_df : DataFrame, optional
        Rows from unified holdings with pik_rate > 0. Loaded from disk if
        file exists and None.

    Returns
    -------
    (position_returns_df, index_returns_df)
    """
    t0 = time.time()

    if matches_df is None:
        logger.info("Loading position matches from %s", POSITION_MATCHES_FILE.name)
        matches_df = pd.read_csv(POSITION_MATCHES_FILE, dtype=str)
        logger.info("  Loaded %d matched pairs", len(matches_df))

    if matches_df.empty:
        logger.warning("No matched pairs -- cannot compute returns")
        return pd.DataFrame(), pd.DataFrame()

    # Load fee uplift from disk if not provided and file exists
    if fee_uplift_df is None:
        from pipeline.config import FEE_UPLIFT_FILE
        if FEE_UPLIFT_FILE.exists():
            fee_uplift_df = pd.read_csv(FEE_UPLIFT_FILE, dtype=str)
            logger.info("Loaded fee uplift from %s (%d rows)",
                        FEE_UPLIFT_FILE.name, len(fee_uplift_df))

    # Create empty fee_uplift if still None
    if fee_uplift_df is None or fee_uplift_df.empty:
        fee_uplift_df = pd.DataFrame(columns=[
            "cik", "quarter", "effective_uplift",
        ])

    # Load unified holdings PIK data from disk if not provided
    if unified_pik_df is None:
        unified_pik_df = pd.DataFrame(columns=[
            "cik", "report_date", "issuer_name", "pik_rate",
        ])
        if UNIFIED_HOLDINGS_FILE.exists():
            _udf = pd.read_csv(
                UNIFIED_HOLDINGS_FILE, dtype=str,
                usecols=["cik", "report_date", "issuer_name", "pik_rate"],
            )
            # Only keep rows with non-null pik_rate for efficiency
            _udf = _udf[_udf["pik_rate"].notna() & (_udf["pik_rate"] != "")]
            if not _udf.empty:
                unified_pik_df = _udf
                logger.info("Loaded %d rows with pik_rate from unified holdings",
                            len(unified_pik_df))

    con = duckdb.connect()
    # Floating-point reductions can vary at the last digits under parallel
    # aggregation.  The refactor parity gate is byte-level, so keep this
    # deterministic.
    con.execute("PRAGMA threads=1")
    if all_in_ciks_df is None:
        all_in_ciks_df = _load_all_in_ciks()

    con.register("matches", matches_df)
    con.register("fee_uplift", fee_uplift_df)
    con.register("unified_pik", unified_pik_df)
    con.register("rate_convention", all_in_ciks_df)

    # ------------------------------------------------------------------
    # Position-level returns
    # ------------------------------------------------------------------
    position_sql = f"""
    WITH
    -- Derive implied SOFR per quarter from filers reporting both rate and spread
    implied_sofr AS (
        SELECT
            begin_quarter,
            MEDIAN(TRY_CAST(begin_interest_rate AS DOUBLE)
                   - TRY_CAST(begin_basis_spread AS DOUBLE)) AS sofr
        FROM matches
        WHERE index_classification = 'DIRECT_LENDING'
          AND TRY_CAST(begin_interest_rate AS DOUBLE) > 0
          AND TRY_CAST(begin_basis_spread AS DOUBLE) > 0
          AND TRY_CAST(begin_interest_rate AS DOUBLE)
              > TRY_CAST(begin_basis_spread AS DOUBLE)
        GROUP BY begin_quarter
    ),
    -- PIK rate lookup: pre-compute for join
    pik_lookup AS (
        SELECT CAST(cik AS VARCHAR) AS _pk_cik,
               CAST(report_date AS VARCHAR) AS _pk_date,
               LOWER(TRIM(CAST(issuer_name AS VARCHAR))) AS _pk_name,
               TRY_CAST(pik_rate AS DOUBLE) AS pik_val
        FROM unified_pik
    ),
    -- Same-filer median rate: fallback for positions with neither rate nor spread
    -- Includes PIK so the median captures total coupon yield
    filer_median_rate AS (
        SELECT
            m.cik,
            m.begin_quarter,
            MEDIAN(COALESCE(
                TRY_CAST(m.begin_interest_rate AS DOUBLE),
                TRY_CAST(m.begin_basis_spread AS DOUBLE) + s.sofr
            ) + COALESCE(pk.pik_val, 0)) AS filer_rate
        FROM matches m
        LEFT JOIN implied_sofr s ON m.begin_quarter = s.begin_quarter
        LEFT JOIN pik_lookup pk
          ON m.cik = pk._pk_cik
         AND m.begin_report_date = pk._pk_date
         AND LOWER(TRIM(m.begin_issuer_name)) = pk._pk_name
        WHERE m.index_classification IN ('DIRECT_LENDING', 'PREFERRED_EQUITY')
          AND COALESCE(
                TRY_CAST(m.begin_interest_rate AS DOUBLE),
                TRY_CAST(m.begin_basis_spread AS DOUBLE) + s.sofr
              ) > 0
        GROUP BY m.cik, m.begin_quarter
    ),
    typed AS (
        SELECT m.*,
            TRY_CAST(m.begin_fair_value AS DOUBLE) AS bfv,
            TRY_CAST(m.end_fair_value AS DOUBLE) AS efv,
            TRY_CAST(m.begin_cost AS DOUBLE) AS bc,
            TRY_CAST(m.end_cost AS DOUBLE) AS ec,
            TRY_CAST(m.begin_principal_amount AS DOUBLE) AS bpa,
            TRY_CAST(m.end_principal_amount AS DOUBLE) AS epa,
            TRY_CAST(m.begin_interest_rate AS DOUBLE) AS bir,
            TRY_CAST(m.begin_basis_spread AS DOUBLE) AS bbs,
            -- Effective income rate: direct > spread+SOFR > same-filer median
            -- Capped at 50% to match unified_holdings rate cap
            -- (CASE not LEAST: DuckDB LEAST skips NULLs so LEAST(NULL,50)=50)
            (CASE WHEN COALESCE(
                    TRY_CAST(m.begin_interest_rate AS DOUBLE),
                    TRY_CAST(m.begin_basis_spread AS DOUBLE) + s.sofr,
                    f.filer_rate
                ) > 50 THEN 50.0
            ELSE COALESCE(
                    TRY_CAST(m.begin_interest_rate AS DOUBLE),
                    TRY_CAST(m.begin_basis_spread AS DOUBLE) + s.sofr,
                    f.filer_rate
                )
            END) AS effective_rate,
            -- PIK rate from unified holdings
            COALESCE(pk.pik_val, 0) AS pik_rate_pct,
            -- All-in-coupon filer (FRED-anchored rate-convention gate): the
            -- disclosed interest_rate already INCLUDES PIK, so adding pik below
            -- would double-count. Suppress the additive PIK term for these CIKs.
            (rc.cik IS NOT NULL) AS rate_all_in,
            -- Fee/OID uplift from fund-level income analysis
            COALESCE(TRY_CAST(u_fee.effective_uplift AS DOUBLE), 0) AS fee_uplift_pct,
            TRY_CAST(m.begin_shares_held AS DOUBLE) AS bsh,
            TRY_CAST(m.end_shares_held AS DOUBLE) AS esh,
            TRY_CAST(m.span_months AS INT) AS sm,
            TRY_CAST(m.match_score AS DOUBLE) AS mscore
        FROM matches m
        LEFT JOIN implied_sofr s ON m.begin_quarter = s.begin_quarter
        LEFT JOIN filer_median_rate f
            ON m.cik = f.cik AND m.begin_quarter = f.begin_quarter
        LEFT JOIN pik_lookup pk
            ON m.cik = pk._pk_cik
           AND m.begin_report_date = pk._pk_date
           AND LOWER(TRIM(m.begin_issuer_name)) = pk._pk_name
        LEFT JOIN fee_uplift u_fee
            ON m.cik = CAST(u_fee.cik AS VARCHAR)
           AND m.begin_quarter = CAST(u_fee.quarter AS VARCHAR)
        LEFT JOIN rate_convention rc
            ON LPAD(CAST(m.cik AS VARCHAR), 10, '0') = rc.cik
        WHERE TRY_CAST(m.begin_fair_value AS DOUBLE) IS NOT NULL
          AND TRY_CAST(m.begin_fair_value AS DOUBLE) != 0
          AND TRY_CAST(m.end_fair_value AS DOUBLE) IS NOT NULL
    ),
    with_returns AS (
        SELECT *,
            -- Capital return: per-unit price return isolates price from quantity
            CASE
                -- DL with both principal amounts: price = FV / principal
                WHEN index_classification = 'DIRECT_LENDING'
                     AND bpa IS NOT NULL AND bpa > 0
                     AND epa IS NOT NULL AND epa > 0
                THEN (efv / epa - bfv / bpa) / (bfv / bpa)
                -- Equity with both share counts: price = FV / shares
                -- Guard: skip per-unit when shares ratio > 5x (unit mismatch)
                WHEN index_classification IN ('PREFERRED_EQUITY', 'COMMON_EQUITY')
                     AND bsh IS NOT NULL AND bsh > 0
                     AND esh IS NOT NULL AND esh > 0
                     AND esh / bsh <= 5 AND bsh / esh <= 5
                THEN (efv / esh - bfv / bsh) / (bfv / bsh)
                -- Equity with both cost bases: price = FV / cost
                -- Guard: skip when shares jumped > 5x (cost scales with shares)
                WHEN index_classification IN ('PREFERRED_EQUITY', 'COMMON_EQUITY')
                     AND bc IS NOT NULL AND bc > 0
                     AND ec IS NOT NULL AND ec > 0
                     AND (bsh IS NULL OR esh IS NULL
                          OR bsh <= 0 OR esh <= 0
                          OR (esh / bsh <= 5 AND bsh / esh <= 5))
                THEN (efv / ec - bfv / bc) / (bfv / bc)
                -- Fallback: raw FV change (assumes no transactions)
                ELSE (efv - bfv) / bfv
            END AS capital_return,

            -- Income return: depends on index classification
            CASE
                -- Direct Lending + Preferred Equity: coupon/dividend + PIK + fee/OID uplift, scaled by span
                WHEN index_classification IN ('DIRECT_LENDING', 'PREFERRED_EQUITY')
                THEN (COALESCE(bpa, bfv)
                      * (COALESCE(effective_rate, 0)
                         + CASE WHEN rate_all_in THEN 0 ELSE pik_rate_pct END
                         + fee_uplift_pct)
                      / 100.0 * COALESCE(sm, 3) / 12.0) / bfv
                -- Fund vehicles: return-of-capital proxy
                WHEN index_classification IN ('PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND')
                THEN GREATEST(0, COALESCE(bc, bfv) - COALESCE(ec, efv)) / bfv
                -- Common Equity, Unclassified: no income
                ELSE 0
            END AS income_return
        FROM typed
    ),
    with_total AS (
        SELECT *,
            -- Cap income_return before summing into total
            LEAST(income_return, {MAX_INCOME_RETURN}) AS guarded_income,
            capital_return + LEAST(income_return, {MAX_INCOME_RETURN}) AS total_return
        FROM with_returns
    ),
    with_guards AS (
        SELECT *,
            -- Outlier guard
            CASE
                WHEN total_return > {MAX_RETURN} THEN NULL
                WHEN total_return < {MIN_RETURN} THEN {MIN_RETURN}
                ELSE total_return
            END AS guarded_return,
            -- Span adjustment: convert multi-quarter to quarterly equivalent
            CASE
                WHEN sm IS NOT NULL AND sm > 4
                THEN TRUE
                ELSE FALSE
            END AS span_adjusted
        FROM with_total
    ),
    final AS (
        SELECT *,
            CASE
                WHEN guarded_return IS NULL THEN NULL
                WHEN span_adjusted AND sm > 0
                THEN POWER(1 + guarded_return, 3.0 / sm) - 1
                ELSE guarded_return
            END AS quarterly_total_return
        FROM with_guards
    )
    SELECT
        cik, entity_name, source,
        begin_quarter, end_quarter,
        begin_issuer_name AS issuer_name,
        index_classification, asset_category,
        bfv AS begin_fair_value, efv AS end_fair_value,
        bc AS begin_cost, ec AS end_cost,
        bpa AS begin_principal_amount, epa AS end_principal_amount,
        bsh AS begin_shares_held, esh AS end_shares_held,
        bir AS begin_interest_rate, bbs AS begin_basis_spread,
        effective_rate AS income_rate,
        pik_rate_pct, fee_uplift_pct,
        capital_return, guarded_income AS income_return, total_return,
        quarterly_total_return, match_method, mscore AS match_score,
        sm AS span_months, span_adjusted,
        CAST(position_id AS VARCHAR) AS position_id
    FROM final
    """

    position_returns = con.execute(position_sql).fetchdf()
    logger.info("Position returns: %d rows", len(position_returns))

    # Log outlier and imputation stats
    if len(position_returns) > 0:
        outliers = position_returns["quarterly_total_return"].isna().sum()
        capped = (position_returns["total_return"] < MIN_RETURN).sum()
        income_capped = (position_returns["income_return"] >= MAX_INCOME_RETURN - 1e-9).sum()
        logger.info("  Outliers excluded (>200%%): %d", outliers)
        logger.info("  Capped at -99%%: %d", capped)
        logger.info("  Income capped at %.0f%%: %d", MAX_INCOME_RETURN * 100, income_capped)

        dl = position_returns[position_returns["index_classification"] == "DIRECT_LENDING"]
        if len(dl) > 0:
            has_bir = dl["begin_interest_rate"].notna() & (dl["begin_interest_rate"] > 0)
            has_bbs = dl["begin_basis_spread"].notna() & (dl["begin_basis_spread"] > 0)
            has_erate = dl["income_rate"].notna() & (dl["income_rate"] > 0)
            # Tier 1: direct interest rate
            tier1 = has_bir.sum()
            # Tier 2: no direct rate, has basis_spread, got effective rate
            tier2 = (~has_bir & has_bbs & has_erate).sum()
            # Tier 3: no direct rate, no spread, got effective rate (filer median)
            tier3 = (~has_bir & ~has_bbs & has_erate).sum()
            # Still missing
            no_rate = len(dl) - has_erate.sum()
            logger.info("  DL income rates: %d direct, %d spread+SOFR, %d filer-median, %d missing",
                         tier1, tier2, tier3, no_rate)
            has_pik = dl["pik_rate_pct"].notna() & (dl["pik_rate_pct"] > 0)
            has_uplift = dl["fee_uplift_pct"].notna() & (dl["fee_uplift_pct"] > 0)
            logger.info("  DL PIK: %d positions (%.1f%%), median %.1f%%",
                         has_pik.sum(), 100 * has_pik.mean(),
                         dl.loc[has_pik, "pik_rate_pct"].median() if has_pik.any() else 0)
            logger.info("  DL fee uplift: %d positions (%.1f%%), median %.1f%%",
                         has_uplift.sum(), 100 * has_uplift.mean(),
                         dl.loc[has_uplift, "fee_uplift_pct"].median() if has_uplift.any() else 0)

    # Save position returns in deterministic order. The aggregation is order
    # independent, but byte-parity checks and downstream reviews are not.
    position_returns = position_returns.sort_values(
        list(position_returns.columns),
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    # Save position returns
    position_returns.to_csv(POSITION_RETURNS_FILE, index=False)
    from pipeline.utils import write_parquet_companion
    write_parquet_companion(POSITION_RETURNS_FILE)
    logger.info("Saved position returns to %s", POSITION_RETURNS_FILE.name)

    # Register for index aggregation
    con.register("pos_returns", position_returns)

    # ------------------------------------------------------------------
    # Index-level aggregation
    # ------------------------------------------------------------------
    index_sql = f"""
    WITH
    valid AS (
        SELECT *
        FROM pos_returns
        WHERE quarterly_total_return IS NOT NULL
          AND index_classification IS NOT NULL
          AND index_classification != ''
          AND index_classification != 'UNCLASSIFIED'
          AND begin_fair_value >= {MIN_BEGIN_FV}
    ),
    quarterly AS (
        SELECT
            index_classification,
            end_quarter AS quarter,
            -- FV-weighted return
            SUM(begin_fair_value * quarterly_total_return) /
                NULLIF(SUM(begin_fair_value), 0) AS fv_weighted_return,
            -- Equal-weighted return
            AVG(quarterly_total_return) AS equal_weighted_return,
            -- Cost-weighted return
            SUM(
                CASE WHEN begin_cost IS NOT NULL AND begin_cost > 0
                     THEN begin_cost * quarterly_total_return
                     ELSE 0
                END
            ) /
            NULLIF(SUM(
                CASE WHEN begin_cost IS NOT NULL AND begin_cost > 0
                     THEN begin_cost
                     ELSE 0
                END
            ), 0) AS cost_weighted_return,
            COUNT(*) AS constituent_count,
            SUM(begin_fair_value) AS total_begin_fv,
            SUM(end_fair_value) AS total_end_fv
        FROM valid
        GROUP BY index_classification, end_quarter
    ),
    -- Enforce minimum constituent threshold
    filtered AS (
        SELECT * FROM quarterly
        WHERE constituent_count >= {MIN_CONSTITUENTS}
    ),
    -- Chain-link: index_level = 100 * PRODUCT(1 + R)
    chained AS (
        SELECT *,
            100.0 * EXP(
                SUM(LN(1 + fv_weighted_return))
                OVER (PARTITION BY index_classification
                      ORDER BY quarter
                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            ) AS index_level_fv,
            100.0 * EXP(
                SUM(LN(1 + equal_weighted_return))
                OVER (PARTITION BY index_classification
                      ORDER BY quarter
                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            ) AS index_level_equal,
            100.0 * EXP(
                SUM(LN(1 + COALESCE(cost_weighted_return, equal_weighted_return)))
                OVER (PARTITION BY index_classification
                      ORDER BY quarter
                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            ) AS index_level_cost
        FROM filtered
    )
    SELECT
        index_classification, quarter,
        fv_weighted_return, equal_weighted_return, cost_weighted_return,
        constituent_count,
        total_begin_fv, total_end_fv,
        index_level_fv, index_level_equal, index_level_cost
    FROM chained
    ORDER BY index_classification, quarter
    """

    index_returns = con.execute(index_sql).fetchdf()
    con.close()

    logger.info("Index returns: %d quarter-index rows", len(index_returns))

    # Log per-index summary
    for idx_name in index_returns["index_classification"].unique():
        idx_rows = index_returns[
            index_returns["index_classification"] == idx_name
        ]
        n_quarters = len(idx_rows)
        avg_constituents = idx_rows["constituent_count"].mean()
        final_level = idx_rows["index_level_fv"].iloc[-1] if len(idx_rows) > 0 else 0
        logger.info("  %s: %d quarters, avg %.0f constituents, FV index %.1f",
                     idx_name, n_quarters, avg_constituents, final_level)

    # Save
    index_returns.to_csv(INDEX_RETURNS_FILE, index=False)
    elapsed = time.time() - t0
    logger.info("Returns computation complete in %.1f s", elapsed)

    return position_returns, index_returns
