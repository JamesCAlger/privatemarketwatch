"""Unified tier-tagged validation-results runner (read-only shadow).

Wires the three parametric gate engines -- conservation (aggregate vs external
total), identity (per-row algebraic relation), cross-source (two independent
sources agree) -- into ONE run over a shared connection, and normalizes their
outputs into a single validation-results ledger:

    engine | rule_name | tier | enforcement | cik | period_kind | period
          | status (pass|fail|skip) | metric | metric_name | n_units

This is the read-only "what is validated, how tightly, and would it pass"
panel. Tight checks here are the promotion-to-blocking candidates; the same
ledger is where weak checks would graduate as flags. Nothing here blocks the
build -- it measures.

Outputs (data/output/shadow/):
  - validation_results_ledger.csv   (one row per check x CIK-period)
  - validation_results_summary.csv  (per engine x rule: pass/fail/skip + fail%)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import duckdb

# sibling imports (the engines live in this dir; not a package)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import shadow_conservation_engine as cons   # noqa: E402
import shadow_identity_engine as idn         # noqa: E402
import shadow_cross_source_engine as xsrc    # noqa: E402

from pipeline.config import OUTPUT_DIR       # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_validation_runner")
SHADOW_DIR = OUTPUT_DIR / "shadow"

# Per-engine normalization to the common ledger schema (11 columns, same order).
_CONS = """
SELECT 'conservation' AS engine, rule_name, tier, enforcement, cik,
       'report_date' AS period_kind, report_date AS period,
       CASE status WHEN 'reconciles' THEN 'pass'
                   WHEN 'no_anchor'  THEN 'skip' ELSE 'fail' END AS status,
       residual_pct AS metric, 'residual_pct' AS metric_name, 1 AS n_units
FROM result_{name}
"""
_XS = """
SELECT 'cross_source' AS engine, rule_name, tier, enforcement, cik,
       'report_quarter' AS period_kind, report_quarter AS period,
       CASE status WHEN 'agree' THEN 'pass' ELSE 'fail' END AS status,
       pct_diff AS metric, 'pct_diff' AS metric_name, 1 AS n_units
FROM result_{name}
"""
_IDN = """
SELECT 'identity' AS engine, rule_name, any_value(tier) AS tier,
       any_value(enforcement) AS enforcement, cik,
       'report_date' AS period_kind, report_date AS period,
       CASE WHEN sum(CASE WHEN NOT holds THEN 1 ELSE 0 END) = 0 THEN 'pass' ELSE 'fail' END AS status,
       round(100.0*sum(CASE WHEN NOT holds THEN 1 ELSE 0 END)/count(*), 2) AS metric,
       'violation_pct' AS metric_name, count(*) AS n_units
FROM result_{name} GROUP BY rule_name, cik, report_date
"""


def main(argv: list[str] | None = None) -> int:
    ciks = cons.wrapped_ciks()
    if not ciks:
        logger.error("no wrapper CIK configs")
        return 1
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in ciks])
    logger.info("validation runner: cohort %d CIKs", len(ciks))

    parts: list[str] = []

    # 1. conservation (always creates result_<name>)
    for r in cons.RULES:
        cons.run_rule(con, r)
        parts.append(_CONS.format(name=r.name))
    logger.info("conservation: %d rules", len(cons.RULES))

    # 2. identity (skips rules with absent columns)
    cache: dict[str, set[str]] = {}
    n_idn = 0
    for r in idn.RULES:
        if idn.run_rule(con, r, cache):
            parts.append(_IDN.format(name=r.name)); n_idn += 1
    logger.info("identity: %d/%d rules ran", n_idn, len(idn.RULES))

    # 3. cross-source (skips rules with absent columns)
    n_xs = 0
    for r in xsrc.RULES:
        if xsrc.run_rule(con, r):
            parts.append(_XS.format(name=r.name)); n_xs += 1
    logger.info("cross_source: %d/%d rules ran", n_xs, len(xsrc.RULES))

    con.execute("CREATE TABLE ledger AS " + " UNION ALL ".join(parts))

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = SHADOW_DIR / "validation_results_ledger.csv"
    con.execute(
        f"""COPY (SELECT * FROM ledger ORDER BY engine, rule_name, status, cik, period)
            TO '{ledger_path.as_posix()}' (HEADER, DELIMITER ',')"""
    )
    summary_path = SHADOW_DIR / "validation_results_summary.csv"
    con.execute(
        f"""
        COPY (
            SELECT engine, rule_name, tier, enforcement,
                   count(*) AS n_groups,
                   sum(CASE WHEN status='pass' THEN 1 ELSE 0 END) AS n_pass,
                   sum(CASE WHEN status='fail' THEN 1 ELSE 0 END) AS n_fail,
                   sum(CASE WHEN status='skip' THEN 1 ELSE 0 END) AS n_skip,
                   round(100.0*sum(CASE WHEN status='fail' THEN 1 ELSE 0 END)
                         /NULLIF(sum(CASE WHEN status IN ('pass','fail') THEN 1 ELSE 0 END),0), 2) AS fail_pct
            FROM ledger GROUP BY 1,2,3,4 ORDER BY engine, fail_pct DESC NULLS LAST
        ) TO '{summary_path.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    logger.info("wrote %s", ledger_path)
    logger.info("wrote %s", summary_path)

    total = con.execute("SELECT count(*) FROM ledger").fetchone()[0]
    logger.info("ledger: %d check-results across %d rules", total,
                len(cons.RULES) + n_idn + n_xs)
    logger.info("rollup by engine x tier x status:")
    for eng, tier, st, n in con.execute(
        "SELECT engine, tier, status, count(*) FROM ledger GROUP BY 1,2,3 ORDER BY 1,2,3"
    ).fetchall():
        logger.info("  %-13s %-5s %-5s : %6d", eng, tier, st, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
