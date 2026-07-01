"""Shadow rate-convention gate -- does interest_rate mean ALL-IN or SPREAD?

See docs/refactoring/frontier_architecture.md. Read-only; writes only to
data/output/shadow/. Sibling of build_shadow_rate_scale_gate.py (that gate guards
rate MAGNITUDE; this gate guards rate SEMANTICS).

Why this gate exists
--------------------
Filers define their own interest_rate semantics (Reg S-X mandates disclosure, not
a canonical representation; XBRL tags the filer's presentation, not normalized
meaning). Two valid filings can mean different things by `interest_rate`:
  - ALL-IN coupon  (e.g. Ares: interest_rate ~= basis_spread + reference)
  - SPREAD only    (e.g. Stepstone: interest_rate ~= basis_spread, reference missing)
This matters because index_returns income = effective_rate + pik_rate + fee_uplift
ADDS pik_rate on top. When interest_rate is the ALL-IN coupon, the disclosed PIK
is a SUBSET of it, so the additive term DOUBLE-COUNTS PIK income. When it is the
SPREAD, income is instead UNDER-counted (missing the reference leg). The two
conventions need opposite corrections, so they must first be told apart.

Approach (mirrors the other shadow gates: reconstruct a quantity, reconcile to an
independent anchor, localize residuals):
  - residual = interest_rate - basis_spread, per floating debt position.
  - implied_reference = the market reference rate at the report_date, read from a
    cached, independent FRED SOFR series (SOFR90DAYAVG) via an as-of join (latest
    value on or before report_date). This is an EXTERNAL anchor -- the population
    cannot satisfy the gate by editing its own output -- which is why the check is
    not circular. (Validated: the FRED anchor reproduces the cohort-median verdicts
    exactly, with a ~4-5pp separation margin that dwarfs anchor ambiguity.)
  - per CIK: median signed deviation dev = residual - implied_reference.
      dev ~ 0                 -> interest_rate ~= spread + reference  => ALL_IN
      residual ~ 0 (dev ~ -ref) -> interest_rate ~= spread            => SPREAD_AS_RATE
  - PIK exposure: for ALL_IN filers, every row with pik_rate > 0 is a
    double-count-exposed row (PIK already inside the all-in coupon).

Scope: the v3-wrapper BDC CIKs (same cohort basis as the other shadow gates).
unified interest_rate / basis_spread / pik_rate are harmonized to PERCENT.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import duckdb

from pipeline.config import (
    OUTPUT_DIR,
    OVERRIDES_DIR,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_rate_convention_gate")

WRAPPER_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"
SHADOW_DIR = OUTPUT_DIR / "shadow"
# Independent reference anchor: cached FRED SOFR90DAYAVG (90-day average SOFR, a
# proxy for the 3M term reference BDC loans apply). Cached on disk (no runtime
# network); fetched once from fred.stlouisfed.org. Validated 2026-06-19 to give
# the IDENTICAL per-CIK classification as the prior cohort-median anchor (0
# disagreements vs both SOFR90DAYAVG and overnight SOFR), so the rule's signal is
# independent of the population, not a self-reference artifact.
REFERENCE_RATE_FILE = OUTPUT_DIR.parent / "raw" / "reference_rates" / "SOFR90DAYAVG.csv"
_CIK_RE = re.compile(r"^\d{10}$")

# Bounds for a usable floating-rate debt observation (percent).
RATE_LO, RATE_HI = 0.0, 40.0     # plausible all-in coupon ceiling
SPREAD_LO, SPREAD_HI = 0.0, 25.0  # plausible credit spread ceiling

# Classification thresholds.
MIN_N_FLOATING = 20      # need enough floating rows to classify a filer
DEV_TOL = 1.0            # |median dev| <= 1.0pp  => interest_rate ~= spread+reference
ABSDEV_TOL = 1.75        # median |dev| guard against high-variance fits
SPREAD_RESID_MAX = 1.0   # median residual <= 1.0pp => interest_rate ~= spread

# Single source of truth for the per-CIK status classification. Referenced by the
# gate SQL and by tests. Expects plain (unqualified) column names in scope:
# n_floating, median_dev, median_abs_dev, median_residual.
STATUS_CASE_SQL = f"""
    CASE
        WHEN COALESCE(n_floating, 0) = 0 THEN 'no_floating_rate_rows'
        WHEN n_floating < {MIN_N_FLOATING} THEN 'insufficient_floating'
        WHEN abs(median_dev) <= {DEV_TOL}
             AND median_abs_dev <= {ABSDEV_TOL} THEN 'all_in_coupon'
        WHEN median_residual <= {SPREAD_RESID_MAX} THEN 'spread_as_rate'
        ELSE 'unresolved_convention'
    END
"""


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
    logger.info("rate-convention gate cohort: %d v3-wrapped CIKs", len(ciks))

    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in ciks])

    # BDC position rows with rate / spread / pik for wrapped CIKs.
    con.execute(
        f"""
        CREATE TABLE pos AS
        SELECT CAST(cik AS VARCHAR) AS cik,
               CAST(report_date AS VARCHAR) AS report_date,
               issuer_name,
               bdc_investment_identifier AS ident,
               TRY_CAST(interest_rate AS DOUBLE) AS rate,
               TRY_CAST(basis_spread AS DOUBLE) AS bs,
               TRY_CAST(pik_rate AS DOUBLE) AS pik,
               TRY_CAST(fair_value AS DOUBLE) AS fv
        FROM {_unified()}
        WHERE bdc_dimensions_raw IS NOT NULL
          AND CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped)
        """
    )

    # Floating debt observations usable for the identity test.
    con.execute(
        f"""
        CREATE TABLE flt AS
        SELECT cik, report_date, CAST(report_date AS DATE) AS rd,
               (rate - bs) AS residual, fv
        FROM pos
        WHERE rate > {RATE_LO} AND rate <= {RATE_HI}
          AND bs   > {SPREAD_LO} AND bs   <= {SPREAD_HI}
        """
    )

    # Independent reference anchor: cached FRED SOFR90DAYAVG (daily, business days).
    if not REFERENCE_RATE_FILE.exists():
        logger.error("missing cached reference series: %s", REFERENCE_RATE_FILE)
        return 1
    con.execute(
        f"""
        CREATE TABLE fred AS
        SELECT CAST(observation_date AS DATE) AS d,
               TRY_CAST(NULLIF(CAST(SOFR90DAYAVG AS VARCHAR), '.') AS DOUBLE) AS ref
        FROM read_csv_auto('{REFERENCE_RATE_FILE.as_posix()}')
        WHERE TRY_CAST(observation_date AS DATE) IS NOT NULL
          AND TRY_CAST(NULLIF(CAST(SOFR90DAYAVG AS VARCHAR), '.') AS DOUBLE) IS NOT NULL
        """
    )
    # Per report_date reference = latest FRED value on or before report_date.
    con.execute(
        """
        CREATE TABLE implied_ref AS
        SELECT q.report_date, q.implied_ref, q.n
        FROM (
            SELECT d.report_date, x.ref AS implied_ref, d.n
            FROM (SELECT report_date, max(rd) AS rd, count(*) AS n
                  FROM flt GROUP BY report_date) d
            ASOF LEFT JOIN fred x ON d.rd >= x.d
        ) q
        WHERE q.implied_ref IS NOT NULL
        """
    )

    # Per-row signed deviation from the period reference rate.
    con.execute(
        """
        CREATE TABLE dev AS
        SELECT f.cik, f.report_date, f.residual, r.implied_ref,
               (f.residual - r.implied_ref) AS dev
        FROM flt f JOIN implied_ref r USING (report_date)
        """
    )

    # Per-CIK floating-fit aggregates.
    con.execute(
        """
        CREATE TABLE cik_fit AS
        SELECT cik,
               count(*) AS n_floating,
               round(MEDIAN(residual), 3)      AS median_residual,
               round(MEDIAN(implied_ref), 3)   AS median_implied_ref,
               round(MEDIAN(dev), 3)           AS median_dev,
               round(MEDIAN(abs(dev)), 3)      AS median_abs_dev
        FROM dev GROUP BY cik
        """
    )

    # Per-CIK PIK exposure (over all BDC rows with a positive rate).
    con.execute(
        """
        CREATE TABLE cik_pik AS
        SELECT cik,
               sum(CASE WHEN pik > 0 AND rate > 0 THEN 1 ELSE 0 END) AS n_pik_rows,
               round(sum(CASE WHEN pik > 0 AND rate > 0 THEN COALESCE(fv,0) ELSE 0 END)/1e9, 3) AS pik_fv_b,
               count(*) AS n_bdc_rows
        FROM pos GROUP BY cik
        """
    )

    # Gate: classify each wrapped CIK's rate convention + PIK exposure.
    con.execute(
        f"""
        CREATE TABLE rate_convention_gate AS
        WITH base AS (
            SELECT
                w.cik,
                COALESCE(p.n_bdc_rows, 0)  AS n_bdc_rows,
                COALESCE(f.n_floating, 0)  AS n_floating,
                f.median_residual, f.median_implied_ref, f.median_dev, f.median_abs_dev,
                COALESCE(p.n_pik_rows, 0)  AS n_pik_rows,
                COALESCE(p.pik_fv_b, 0)    AS pik_fv_b
            FROM wrapped w
            LEFT JOIN cik_fit f USING (cik)
            LEFT JOIN cik_pik p USING (cik)
        )
        SELECT base.*, {STATUS_CASE_SQL} AS status FROM base
        """
    )
    # Rows whose income is double-count-exposed: ALL_IN filers with PIK present.
    con.execute(
        """
        ALTER TABLE rate_convention_gate ADD COLUMN double_count_exposed_rows INTEGER;
        ALTER TABLE rate_convention_gate ADD COLUMN double_count_exposed_fv_b DOUBLE;
        UPDATE rate_convention_gate SET
            double_count_exposed_rows = CASE WHEN status='all_in_coupon' THEN n_pik_rows ELSE 0 END,
            double_count_exposed_fv_b = CASE WHEN status='all_in_coupon' THEN pik_fv_b ELSE 0 END;
        """
    )

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out = SHADOW_DIR / "bdc_rate_convention_gate.csv"
    con.execute(
        f"""
        COPY (SELECT cik, status, n_bdc_rows, n_floating,
                     median_residual, median_implied_ref, median_dev, median_abs_dev,
                     n_pik_rows, pik_fv_b,
                     double_count_exposed_rows, double_count_exposed_fv_b
              FROM rate_convention_gate
              ORDER BY status, double_count_exposed_fv_b DESC NULLS LAST)
        TO '{out.as_posix()}' (HEADER, DELIMITER ',')
        """
    )

    # Localization: the double-count-exposed rows (ALL_IN filers, PIK present).
    rows = SHADOW_DIR / "bdc_rate_convention_pik_exposed_rows.csv"
    con.execute(
        f"""
        COPY (
            SELECT p.cik, p.report_date, p.issuer_name,
                   p.rate AS interest_rate, p.bs AS basis_spread, p.pik AS pik_rate,
                   p.fv AS fair_value, p.ident
            FROM pos p
            JOIN rate_convention_gate g ON g.cik = p.cik AND g.status = 'all_in_coupon'
            WHERE p.pik > 0 AND p.rate > 0
            ORDER BY p.fv DESC NULLS LAST
        ) TO '{rows.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    # Quarterly implied-reference curve (the gate's self-validation artifact).
    curve = SHADOW_DIR / "bdc_rate_convention_implied_ref.csv"
    con.execute(
        f"""
        COPY (SELECT report_date, round(implied_ref,3) AS implied_ref, n
              FROM implied_ref ORDER BY report_date)
        TO '{curve.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    logger.info("wrote %s", out)
    logger.info("wrote %s", rows)
    logger.info("wrote %s", curve)

    logger.info("rate-convention gate status (CIKs):")
    for st, n in con.execute(
        "SELECT status, count(*) FROM rate_convention_gate GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        logger.info("  %-22s : %3d", st, n)
    nrows, nfv = con.execute(
        "SELECT sum(double_count_exposed_rows), round(sum(double_count_exposed_fv_b),1) "
        "FROM rate_convention_gate"
    ).fetchone()
    logger.info("double-count-exposed (ALL_IN filers with PIK): %s rows / $%sB FV", nrows, nfv)
    logger.info("implied-reference curve (should track SOFR/Fed-funds):")
    for rd, ir, n in con.execute(
        "SELECT report_date, round(implied_ref,2), n FROM implied_ref "
        "WHERE report_date >= '2022-01-01' ORDER BY report_date"
    ).fetchall():
        logger.info("  %s  implied_ref=%s  n=%d", rd, ir, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
