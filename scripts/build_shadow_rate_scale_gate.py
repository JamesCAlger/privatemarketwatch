"""Shadow rate/scale gate -- the interest_rate axis (the 2% vs 0.02% problem).

See docs/refactoring/frontier_architecture.md. Read-only; writes only to
data/output/shadow/.

Approach (mirrors the FV conservation gate: reconstruct a quantity, reconcile to
an independent fund-level anchor, localize residuals):

  Core check (PERIOD-INDEPENDENT, the strong signal):
    - portfolio weighted-average coupon = sum(rate*principal)/sum(principal) per
      CIK-quarter. A credit BDC's all-in coupon sits ~5-15%; outside [2, 25]%
      signals a systematic scale error (decimal-scaled 0.085, or double-scaled).
    - per-position scale flags: rate in (0,1) -> likely a fraction not a percent
      (e.g. 0.085 should be 8.5); rate > 50 -> likely double-scaled / bad.

  Loose check (income reconciliation, period-CAVEATED):
    - reconstructed annual coupon = sum(rate/100 * principal) vs fund-reported
      total_investment_income. Wide band only (the filing-period mismatch makes
      this a 100x-error detector, not a precision check) -- so we flag only gross
      ratios (<0.1 or >10), exactly as the architecture says income recon should.

Scope: the v3-wrapper BDC CIKs (same cohort basis as the FV shadow ledger).
unified interest_rate is harmonized to PERCENT; principal_amount is USD.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import duckdb

from pipeline.config import (
    FUND_FINANCIALS_FILE,
    OUTPUT_DIR,
    OVERRIDES_DIR,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_rate_scale_gate")

WRAPPER_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"
SHADOW_DIR = OUTPUT_DIR / "shadow"
_CIK_RE = re.compile(r"^\d{10}$")

# Plausible all-in coupon band for a credit BDC portfolio (percent).
WAVG_LO, WAVG_HI = 2.0, 25.0
DECIMAL_SUSPECT_MAX = 1.0     # rate in (0, 1) -> looks like a fraction, not a %
OVER_SUSPECT_MIN = 50.0       # rate > 50% -> implausible / double-scaled
DECIMAL_FV_SHARE_FLAG = 0.01  # >1% of rated FV in suspect rows -> flag the quarter


def _unified() -> str:
    if UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{UNIFIED_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def wrapped_ciks() -> list[str]:
    return sorted(p.stem for p in WRAPPER_DIR.glob("*.json") if _CIK_RE.match(p.stem))


def main(argv: list[str] | None = None) -> int:
    ciks = wrapped_ciks()
    if not ciks:
        logger.error("no wrapper CIK configs in %s", WRAPPER_DIR)
        return 1
    logger.info("rate/scale gate cohort: %d v3-wrapped CIKs", len(ciks))

    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in ciks])

    # Position rows with a usable rate and principal (debt positions).
    con.execute(
        f"""
        CREATE TABLE pos AS
        SELECT CAST(cik AS VARCHAR) AS cik,
               CAST(report_date AS VARCHAR) AS report_date,
               issuer_name,
               bdc_investment_identifier AS ident,
               TRY_CAST(interest_rate AS DOUBLE) AS rate,
               TRY_CAST(principal_amount AS DOUBLE) AS principal,
               TRY_CAST(fair_value AS DOUBLE) AS fv
        FROM {_unified()}
        WHERE bdc_dimensions_raw IS NOT NULL
          AND CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped)
        """
    )

    con.execute(
        f"""
        CREATE TABLE ffin AS
        SELECT CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date,
               max(TRY_CAST(total_investment_income AS DOUBLE)) AS fund_income
        FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
        WHERE source='companyfacts' AND total_investment_income IS NOT NULL
        GROUP BY 1, 2
        """
    )

    con.execute(
        f"""
        CREATE TABLE rate_gate AS
        WITH g AS (
            SELECT cik, report_date,
                count(*) AS n_positions,
                sum(CASE WHEN rate > 0 AND principal > 0 THEN 1 ELSE 0 END) AS n_rated,
                -- weighted-average coupon (period-independent)
                CASE WHEN sum(CASE WHEN rate > 0 AND principal > 0 THEN principal ELSE 0 END) > 0
                     THEN sum(CASE WHEN rate > 0 AND principal > 0 THEN rate*principal ELSE 0 END)
                          / sum(CASE WHEN rate > 0 AND principal > 0 THEN principal ELSE 0 END)
                END AS wavg_coupon,
                -- reconstructed annual coupon (for loose income recon)
                sum(CASE WHEN rate > 0 AND principal > 0 THEN rate/100.0*principal ELSE 0 END) AS recon_annual_coupon,
                -- per-position scale suspects
                sum(CASE WHEN rate > 0 AND rate < {DECIMAL_SUSPECT_MAX} THEN 1 ELSE 0 END) AS n_decimal_suspect,
                sum(CASE WHEN rate > 0 AND rate < {DECIMAL_SUSPECT_MAX} THEN COALESCE(fv,0) ELSE 0 END) AS decimal_suspect_fv,
                sum(CASE WHEN rate > {OVER_SUSPECT_MIN} THEN 1 ELSE 0 END) AS n_over_suspect,
                sum(CASE WHEN rate IS NOT NULL THEN COALESCE(fv,0) ELSE 0 END) AS rated_fv
            FROM pos GROUP BY cik, report_date
        )
        SELECT g.*,
            CASE WHEN g.rated_fv > 0 THEN round(g.decimal_suspect_fv/g.rated_fv, 4) END AS decimal_suspect_fv_share,
            ff.fund_income,
            CASE WHEN ff.fund_income > 0 THEN round(g.recon_annual_coupon/ff.fund_income, 3) END AS income_ratio,
            CASE
                WHEN g.wavg_coupon IS NULL THEN 'no_rate_data'
                WHEN g.wavg_coupon < {WAVG_LO} OR g.wavg_coupon > {WAVG_HI} THEN 'wavg_out_of_band'
                WHEN g.rated_fv > 0 AND g.decimal_suspect_fv/g.rated_fv > {DECIMAL_FV_SHARE_FLAG} THEN 'decimal_scale_rows'
                WHEN g.n_over_suspect > 0 THEN 'over_scale_rows'
                ELSE 'scale_ok'
            END AS status,
            CASE WHEN ff.fund_income > 0 AND (g.recon_annual_coupon/ff.fund_income < 0.1
                                          OR g.recon_annual_coupon/ff.fund_income > 10)
                 THEN true ELSE false END AS income_gross_mismatch
        FROM g LEFT JOIN ffin ff USING (cik, report_date)
        """
    )

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out = SHADOW_DIR / "bdc_rate_scale_gate.csv"
    con.execute(
        f"""
        COPY (SELECT cik, report_date, status, n_positions, n_rated,
                     round(wavg_coupon,2) AS wavg_coupon, decimal_suspect_fv_share,
                     n_decimal_suspect, n_over_suspect, income_ratio, income_gross_mismatch
              FROM rate_gate ORDER BY status, wavg_coupon)
        TO '{out.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    # Per-position scale-suspect rows (localization).
    sus = SHADOW_DIR / "bdc_rate_scale_suspect_rows.csv"
    con.execute(
        f"""
        COPY (
            SELECT cik, report_date, issuer_name, rate, principal, fv,
                   CASE WHEN rate > 0 AND rate < {DECIMAL_SUSPECT_MAX} THEN 'decimal_suspect'
                        WHEN rate > {OVER_SUSPECT_MIN} THEN 'over_scale' END AS flag, ident
            FROM pos
            WHERE (rate > 0 AND rate < {DECIMAL_SUSPECT_MAX}) OR rate > {OVER_SUSPECT_MIN}
            ORDER BY fv DESC NULLS LAST
        ) TO '{sus.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    logger.info("wrote %s", out)
    logger.info("wrote %s", sus)

    logger.info("rate/scale gate status (CIK-quarters):")
    for st, n in con.execute("SELECT status, count(*) FROM rate_gate GROUP BY 1 ORDER BY 2 DESC").fetchall():
        logger.info("  %-20s : %4d", st, n)
    med, lo, hi = con.execute(
        "SELECT round(median(wavg_coupon),2), round(min(wavg_coupon),2), round(max(wavg_coupon),2) "
        "FROM rate_gate WHERE wavg_coupon IS NOT NULL"
    ).fetchone()
    logger.info("portfolio weighted-avg coupon: median %s%%, range [%s, %s]", med, lo, hi)
    nrows, ngross = con.execute(
        "SELECT count(*), sum(CASE WHEN income_gross_mismatch THEN 1 ELSE 0 END) "
        "FROM rate_gate WHERE fund_income IS NOT NULL"
    ).fetchone()
    logger.info("income reconciliation (loose): %d CIK-qtrs with fund income, %d gross mismatch (>10x off)",
                nrows, ngross)
    return 0


if __name__ == "__main__":
    sys.exit(main())
