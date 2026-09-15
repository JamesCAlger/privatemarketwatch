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

# All final matched rates follow financial-contract.v2: supported all-in coupon.
# Legacy convention and PIK arguments remain accepted for diagnostic callers;
# they cannot alter, complete, or add to the stored all-in coupon.


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

    # PIK is diagnostic only and joins on position identity. Borrower names
    # would fan out a single return across distinct loan tranches.
    if unified_pik_df is None:
        unified_pik_df=pd.DataFrame(columns=['cik','source','report_date','position_id','pik_rate'])
        if UNIFIED_HOLDINGS_FILE.exists():
            unified_pik_df=pd.read_csv(UNIFIED_HOLDINGS_FILE,dtype=str,
                usecols=['cik','source','report_date','position_id','pik_rate'])
    if not {'source','position_id'}.issubset(unified_pik_df.columns):
        unified_pik_df=pd.DataFrame(columns=['cik','source','report_date','position_id','pik_rate'])
    con=duckdb.connect(config={'threads':1,'memory_limit':'-1'})
    con.register('matches',matches_df);con.register('fee_uplift',fee_uplift_df);con.register('unified_pik',unified_pik_df)
    if con.execute("SELECT count(*) FROM (SELECT cik,quarter FROM fee_uplift GROUP BY ALL HAVING count(*)>1)").fetchone()[0]:
        raise ValueError('Repeated fee uplift denominator')
    if con.execute("""SELECT count(*) FROM (SELECT cik,source,position_id,report_date FROM unified_pik
        WHERE coalesce(position_id,'')<>'' GROUP BY ALL HAVING count(*)>1)""").fetchone()[0]:
        raise ValueError('Repeated position/date PIK diagnostics')

    # ------------------------------------------------------------------
    # Position-level returns
    # ------------------------------------------------------------------
    position_sql = f"""
    WITH
    pik_lookup AS (
        SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS _pk_cik,
            CAST(source AS VARCHAR) AS _pk_source,CAST(position_id AS VARCHAR) AS _pk_position,
            TRY_CAST(report_date AS DATE) AS _pk_date,TRY_CAST(pik_rate AS DOUBLE) AS pik_val
        FROM unified_pik WHERE coalesce(CAST(position_id AS VARCHAR),'')<>''
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
            CASE WHEN isfinite(TRY_CAST(m.begin_interest_rate AS DOUBLE))
                THEN TRY_CAST(m.begin_interest_rate AS DOUBLE) END AS effective_rate,
            pk.pik_val AS pik_rate_pct,
            -- Fee/OID uplift from fund-level income analysis
            COALESCE(TRY_CAST(u_fee.effective_uplift AS DOUBLE), 0) AS fee_uplift_pct,
            TRY_CAST(m.begin_shares_held AS DOUBLE) AS bsh,
            TRY_CAST(m.end_shares_held AS DOUBLE) AS esh,
            TRY_CAST(m.span_months AS INT) AS sm,
            TRY_CAST(m.match_score AS DOUBLE) AS mscore
        FROM matches m
        LEFT JOIN pik_lookup pk
            ON lpad(CAST(m.cik AS VARCHAR),10,'0')=pk._pk_cik
           AND m.source=pk._pk_source AND m.position_id=pk._pk_position
           AND TRY_CAST(m.begin_report_date AS DATE)=pk._pk_date
        LEFT JOIN fee_uplift u_fee
            ON m.cik=CAST(u_fee.cik AS VARCHAR) AND m.begin_quarter=CAST(u_fee.quarter AS VARCHAR)
        -- A price observation needs a positive mark at BOTH ends.
        --
        -- This used to be enforced by accident: every matcher tier required
        -- `b.fv > 0 AND e.fv > 0`, so a pair with a zero or negative leg could
        -- not exist and the filter here only had to name the begin leg.  Those
        -- guards were relaxed on 2026-09-08 so undrawn revolvers and
        -- delayed-draw commitments could chain (E15).  Measured on the first
        -- rebuild after that change, the newly reachable pairs were 24,809 with
        -- two negative marks (mean total return 2.5, min -150) and 5,502 with a
        -- sign flip or a zero (mean -41.4, min -41,604), against 474,027 sound
        -- observations -- and they moved DIRECT_LENDING from 135.4 to 133.9.
        --
        -- None of them is a price return.  A revolver repaid to zero drawn is a
        -- return OF principal; a commitment marked below par is a liability-like
        -- mark whose ratio to a later mark means nothing.  Requiring positivity
        -- explicitly keeps the index measuring what it always measured and
        -- confines the chain improvement to the holdings product.
        WHERE TRY_CAST(m.begin_fair_value AS DOUBLE) > 0
          AND TRY_CAST(m.end_fair_value AS DOUBLE) > 0
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
                -- Supported all-in coupon plus separately labelled fee/OID proxy, scaled by span
                WHEN index_classification IN ('DIRECT_LENDING', 'PREFERRED_EQUITY')
                THEN (COALESCE(bpa, bfv)
                      * (effective_rate + fee_uplift_pct)
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
            CASE WHEN income_return IS NOT NULL THEN LEAST(income_return, {MAX_INCOME_RETURN}) END AS guarded_income,
            capital_return + CASE WHEN income_return IS NOT NULL THEN LEAST(income_return, {MAX_INCOME_RETURN}) END AS total_return
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

    # Log observed rate availability and outlier guards
    if len(position_returns) > 0:
        outliers = (position_returns["total_return"] > MAX_RETURN).sum()
        capped = (position_returns["total_return"] < MIN_RETURN).sum()
        income_capped = (position_returns["income_return"] >= MAX_INCOME_RETURN - 1e-9).sum()
        logger.info("  Outliers excluded (>200%%): %d", outliers)
        logger.info("  Capped at -99%%: %d", capped)
        logger.info("  Income capped at %.0f%%: %d", MAX_INCOME_RETURN * 100, income_capped)

        supported=position_returns['income_rate'].notna().sum()
        logger.info('  Supported all-in income rates: %d; unavailable: %d',supported,len(position_returns)-supported)

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
