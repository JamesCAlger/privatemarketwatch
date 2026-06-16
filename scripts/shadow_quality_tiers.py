"""Read-only quality-tier rollup + coverage/blind-spot view over the shadow ledger.

Turns the per-check validation_results_ledger into:
  1. a per-(cik, report_date) DATA-QUALITY TIER, and
  2. a COVERAGE / blind-spot view -- which cohort fund-quarters have NO independent
     tight check, so "no flag" is not silently read as "verified".

Reads the ledger the runner already writes; does NOT re-run any engine, and does
NOT touch shadow_validation_runner.py (decoupled on purpose). Read-only: writes
only to data/output/shadow/.

Quality-tier ladder (per cik-quarter, over the cohort universe):
  under_review : >=1 SURFACED flag (an independent check flagged it)
  verified     : a STRONG FV/cost anchor PASSED and nothing surfaced
  preliminary  : evaluated, but no strong-anchor pass, nothing surfaced
  unverified   : NO check evaluated it at all

A "strong anchor" is an independent FV/cost reconciliation -- gav_recon (FV vs
fund denominator), cost_conservation (cost vs companyfacts InvestmentOwnedAtCost),
html_agg (extracted FV vs companyfacts), or source_recon (XBRL source recon).
These are distinguished from the weaker per-row algebraic checks (identity) and
cross_source-vs-highlights (which reconciles against the broken highlights
artifact) -- counting those as "coverage" would overstate confidence. The coverage
view reports STRONG-anchor blind spots: fund-quarters with no FV/cost anchor at all.

Coverage universe = cohort fund-quarters the cohort-scoped engines evaluated (they
emit a row -- including skip/no_anchor -- for every cohort cik-quarter). Global
(oracle/vrules/classification) and name-keyed (aggregate_header) checks cannot
localize to a cik-quarter and are excluded.
"""

from __future__ import annotations

import logging
import sys

import duckdb

from pipeline.config import OUTPUT_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_quality_tiers")
SHADOW_DIR = OUTPUT_DIR / "shadow"
LEDGER = SHADOW_DIR / "validation_results_ledger.csv"


def main(argv: list[str] | None = None) -> int:
    if not LEDGER.exists():
        logger.error("ledger not found: %s (run shadow_validation_runner.py first)", LEDGER)
        return 1
    con = duckdb.connect()
    con.execute(f"CREATE TABLE L AS SELECT * FROM read_csv_auto('{LEDGER.as_posix()}', sample_size=-1)")

    # Universe: cohort fund-quarters the cohort-scoped engines evaluated.
    con.execute("""
        CREATE TABLE univ AS
        SELECT DISTINCT cik, period FROM L
        WHERE engine IN ('conservation','identity','cross_source','weak')
          AND period LIKE '____-__-__'
    """)
    # Per (cik, period): surfaced flags, strong-anchor evaluation/pass, any-eval,
    # and which strong FV/cost anchors actually evaluated it (pass/fail, not skip).
    # Strong-anchor PASS = an independent FV/cost reconciliation reconciled.
    con.execute("""
        CREATE TABLE q AS
        SELECT u.cik, u.period,
            SUM(CASE WHEN l.surface THEN 1 ELSE 0 END) AS n_surfaced,
            SUM(CASE WHEN l.status IN ('pass','fail','warn') THEN 1 ELSE 0 END) AS n_any_eval,
            string_agg(DISTINCT CASE WHEN l.surface THEN l.confidence END, ', ') AS surfaced_kinds,
            -- strong FV/cost anchor evaluation flags
            MAX(CASE WHEN l.engine='gav_recon' AND l.status IN ('pass','fail') THEN 1 ELSE 0 END) AS ev_gav,
            MAX(CASE WHEN l.engine='conservation' AND l.rule_name='cost_conservation'
                     AND l.status IN ('pass','fail') THEN 1 ELSE 0 END) AS ev_cost,
            MAX(CASE WHEN l.engine='html_extract' AND l.rule_name='html_agg'
                     AND l.status IN ('pass','fail') THEN 1 ELSE 0 END) AS ev_html,
            MAX(CASE WHEN l.engine='source_recon' AND l.status IN ('pass','fail') THEN 1 ELSE 0 END) AS ev_source,
            -- strong-anchor PASS (reconciled clean)
            MAX(CASE WHEN (l.engine='gav_recon' AND l.status='pass')
                       OR (l.engine='conservation' AND l.rule_name='cost_conservation' AND l.status='pass')
                       OR (l.engine='html_extract' AND l.rule_name='html_agg' AND l.status='pass')
                     THEN 1 ELSE 0 END) AS strong_pass,
            -- weaker per-row / algebraic coverage (informational)
            MAX(CASE WHEN l.engine='identity' AND l.status IN ('pass','fail') THEN 1 ELSE 0 END) AS ev_identity
        FROM univ u
        LEFT JOIN L l ON l.cik = u.cik AND l.period = u.period
        GROUP BY u.cik, u.period
    """)

    con.execute("""
        CREATE TABLE tiers AS
        SELECT *,
            (ev_gav + ev_cost + ev_html + ev_source) AS n_strong_anchor,
            CASE
                WHEN n_surfaced > 0 THEN 'under_review'
                WHEN strong_pass = 1 THEN 'verified'
                WHEN n_any_eval > 0 THEN 'preliminary'
                ELSE 'unverified'
            END AS quality_tier
        FROM q
    """)

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    tiers_path = SHADOW_DIR / "validation_quality_tiers.csv"
    con.execute(f"""
        COPY (
            SELECT cik, period, quality_tier, n_surfaced, surfaced_kinds,
                   n_strong_anchor, strong_pass, ev_gav, ev_cost, ev_html, ev_source,
                   ev_identity, n_any_eval
            FROM tiers ORDER BY
                CASE quality_tier WHEN 'under_review' THEN 0 WHEN 'unverified' THEN 1
                                  WHEN 'preliminary' THEN 2 ELSE 3 END, cik, period
        ) TO '{tiers_path.as_posix()}' (HEADER, DELIMITER ',')
    """)

    # Coverage gaps = STRONG-anchor blind spots: fund-quarters with NO independent
    # FV/cost reconciliation (only algebraic/row/weak checks touched them).
    gaps_path = SHADOW_DIR / "validation_coverage_gaps.csv"
    con.execute(f"""
        COPY (
            SELECT cik, period, quality_tier, n_any_eval, ev_identity
            FROM tiers WHERE n_strong_anchor = 0
            ORDER BY cik, period
        ) TO '{gaps_path.as_posix()}' (HEADER, DELIMITER ',')
    """)

    total = con.execute("SELECT count(*) FROM tiers").fetchone()[0]
    logger.info("quality tiers over %d cohort fund-quarters:", total)
    for tier, n in con.execute(
        "SELECT quality_tier, count(*) FROM tiers GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        logger.info("  %-13s : %5d (%4.1f%%)", tier, n, 100.0 * n / total)
    logger.info("strong FV/cost anchor coverage per fund-quarter (of 4: gav/cost/html/source):")
    for k, n in con.execute(
        "SELECT n_strong_anchor, count(*) FROM tiers GROUP BY 1 ORDER BY 1"
    ).fetchall():
        tag = "  <-- BLIND SPOT (no FV/cost anchor)" if k == 0 else ""
        logger.info("  %d strong anchor(s): %5d fund-quarters%s", k, n, tag)
    blind = con.execute("SELECT count(*) FROM tiers WHERE n_strong_anchor=0").fetchone()[0]
    logger.info("strong-anchor blind spots: %d (%.1f%%)", blind, 100.0 * blind / total)
    logger.info("wrote %s", tiers_path)
    logger.info("wrote %s", gaps_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
