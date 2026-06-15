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
import shadow_weak_engine as wk              # noqa: E402
import shadow_adapter as adp                 # noqa: E402

from pipeline.config import OUTPUT_DIR       # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_validation_runner")
SHADOW_DIR = OUTPUT_DIR / "shadow"

# ---------------------------------------------------------------------------
# Bootstrap precision/confidence (no truth set). Production is NOT truth (that
# would be circular), and we have no gold set yet -- so confidence is derived
# from INDEPENDENCE signals computable today:
#   confirmed_impossible : violation is logically impossible (precision 1.0)
#   tight_anchor         : tight check failed vs an independent anchor (high)
#   source_blocking_<c>  : source_reconciliation's OWN residual classification
#                          (blocking_issue + mechanism + confidence high/medium/low);
#                          defers to the mature upstream artifact, not the heuristic
#   corroborated         : weak warn co-located with a tight fail at same cik+period
#   scope_caveat         : rule is known definitional/scope-heavy -> suppress
#   lone_weak            : weak warn, no corroboration -> low confidence (noise)
# surface = {confirmed_impossible, tight_anchor, corroborated,
#            source_blocking_high, source_blocking_medium} (low-confidence source
#            residuals are not surfaced, per source_reconciliation's own grade).
# These are PROXIES; real precision still needs the source-adjudicated gold set
# that the Part B review loop accrues.
# ---------------------------------------------------------------------------
CONFIRMED_IMPOSSIBLE = {"R07", "E02"}   # positions FV > fund total assets -> impossible
SCOPE_CAVEAT = {"income_identity", "pct_position_concentration",
                "fmt_pct_of_net_assets", "dl_rate_fill"}  # definitional / scope-heavy


def _sql_set(s: set[str]) -> str:
    return ", ".join(f"'{x}'" for x in sorted(s))

# Per-engine normalization to the common ledger schema (11 columns, same order).
_CONS = """
SELECT 'conservation' AS engine, rule_name, tier, enforcement, cik,
       'report_date' AS period_kind, report_date AS period,
       CASE status WHEN 'reconciles' THEN 'pass'
                   WHEN 'no_anchor'  THEN 'skip' ELSE 'fail' END AS status,
       residual_pct AS metric, 'residual_pct' AS metric_name, 1 AS n_units,
       CAST(NULL AS VARCHAR) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
FROM result_{name}
"""
_XS = """
SELECT 'cross_source' AS engine, rule_name, tier, enforcement, cik,
       'report_quarter' AS period_kind, report_quarter AS period,
       CASE status WHEN 'agree' THEN 'pass' ELSE 'fail' END AS status,
       pct_diff AS metric, 'pct_diff' AS metric_name, 1 AS n_units,
       CAST(NULL AS VARCHAR) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
FROM result_{name}
"""
_IDN = """
SELECT 'identity' AS engine, rule_name, any_value(tier) AS tier,
       any_value(enforcement) AS enforcement, cik,
       'report_date' AS period_kind, report_date AS period,
       CASE WHEN sum(CASE WHEN NOT holds THEN 1 ELSE 0 END) = 0 THEN 'pass' ELSE 'fail' END AS status,
       round(100.0*sum(CASE WHEN NOT holds THEN 1 ELSE 0 END)/count(*), 2) AS metric,
       'violation_pct' AS metric_name, count(*) AS n_units,
       CAST(NULL AS VARCHAR) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
FROM result_{name} GROUP BY rule_name, cik, report_date
"""
# weak rules emit pass|warn (never fail) -- they are flags, not gates.
_WEAK = """
SELECT 'weak' AS engine, rule_name, tier, enforcement, cik,
       'report_date' AS period_kind, report_date AS period,
       status, metric, 'weak_metric' AS metric_name, n_units,
       CAST(NULL AS VARCHAR) AS mechanism, CAST(NULL AS VARCHAR) AS src_confidence
FROM result_{name}
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

    # 4. weak field-validity (tier=weak, status pass|warn -- flags, never gates)
    wk.ensure_base(con)
    for r in wk.RULES:
        wk.run_rule(con, r)
        parts.append(_WEAK.format(name=r.name))
    logger.info("weak: %d rules", len(wk.RULES))

    # 5. adapters: ingest existing pipeline check outputs (oracle, validation_rules),
    #    tier-tagged, normalized into the same ledger schema (no re-coding).
    adapter_parts = adp.adapter_selects()
    parts.extend(adapter_parts)
    logger.info("adapters: %d existing-output sources ingested", len(adapter_parts))

    con.execute("CREATE TABLE ledger AS " + " UNION ALL ".join(parts))

    # Bootstrap confidence scoring (no truth set; see header).
    con.execute(
        f"""
        CREATE TABLE ledger_scored AS
        SELECT *, (confidence IN ('confirmed_impossible','tight_anchor','corroborated',
                                  'source_blocking_high','source_blocking_medium')) AS surface
        FROM (
            WITH tf AS (SELECT DISTINCT cik, period FROM ledger WHERE tier='tight' AND status='fail')
            SELECT l.*,
                CASE
                    WHEN l.status NOT IN ('fail','warn') THEN NULL
                    -- source_reconciliation classifies its own residuals (blocking_issue +
                    -- mechanism + confidence); defer to it rather than the bootstrap heuristic.
                    WHEN l.engine='source_recon' THEN 'source_blocking_' || COALESCE(l.src_confidence, 'na')
                    WHEN l.rule_name IN ({_sql_set(CONFIRMED_IMPOSSIBLE)}) THEN 'confirmed_impossible'
                    WHEN l.rule_name IN ({_sql_set(SCOPE_CAVEAT)}) THEN 'scope_caveat'
                    WHEN l.tier='tight' AND l.status='fail' THEN 'tight_anchor'
                    WHEN l.tier='weak' AND l.status='warn' AND tf.cik IS NOT NULL THEN 'corroborated'
                    WHEN l.tier='weak' AND l.status='warn' THEN 'lone_weak'
                    ELSE 'other'
                END AS confidence
            FROM ledger l LEFT JOIN tf ON l.cik=tf.cik AND l.period=tf.period
        )
        """
    )

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = SHADOW_DIR / "validation_results_ledger.csv"
    con.execute(
        f"""COPY (SELECT * FROM ledger_scored ORDER BY surface DESC, engine, rule_name, status, cik, period)
            TO '{ledger_path.as_posix()}' (HEADER, DELIMITER ',')"""
    )
    # Precision-proxy summary: per rule, how its flags break down by confidence.
    proxy_path = SHADOW_DIR / "validation_precision_proxy.csv"
    con.execute(
        f"""
        COPY (
            SELECT engine, rule_name, tier,
                   sum(CASE WHEN status IN ('fail','warn') THEN 1 ELSE 0 END) AS n_flagged,
                   sum(CASE WHEN surface THEN 1 ELSE 0 END) AS n_surfaced,
                   sum(CASE WHEN confidence='confirmed_impossible' THEN 1 ELSE 0 END) AS n_confirmed,
                   sum(CASE WHEN confidence='tight_anchor' THEN 1 ELSE 0 END) AS n_tight_anchor,
                   sum(CASE WHEN confidence='corroborated' THEN 1 ELSE 0 END) AS n_corroborated,
                   sum(CASE WHEN confidence='lone_weak' THEN 1 ELSE 0 END) AS n_lone_weak,
                   sum(CASE WHEN confidence='scope_caveat' THEN 1 ELSE 0 END) AS n_scope_caveat
            FROM ledger_scored GROUP BY 1,2,3
            HAVING sum(CASE WHEN status IN ('fail','warn') THEN 1 ELSE 0 END) > 0
            ORDER BY n_surfaced DESC, n_flagged DESC
        ) TO '{proxy_path.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    summary_path = SHADOW_DIR / "validation_results_summary.csv"
    con.execute(
        f"""
        COPY (
            SELECT engine, rule_name, tier, enforcement,
                   count(*) AS n_groups,
                   sum(CASE WHEN status='pass' THEN 1 ELSE 0 END) AS n_pass,
                   sum(CASE WHEN status='fail' THEN 1 ELSE 0 END) AS n_fail,
                   sum(CASE WHEN status='warn' THEN 1 ELSE 0 END) AS n_warn,
                   sum(CASE WHEN status='skip' THEN 1 ELSE 0 END) AS n_skip,
                   round(100.0*sum(CASE WHEN status='fail' THEN 1 ELSE 0 END)
                         /NULLIF(sum(CASE WHEN status IN ('pass','fail') THEN 1 ELSE 0 END),0), 2) AS fail_pct,
                   round(100.0*sum(CASE WHEN status='warn' THEN 1 ELSE 0 END)
                         /NULLIF(sum(CASE WHEN status IN ('pass','warn') THEN 1 ELSE 0 END),0), 2) AS warn_pct
            FROM ledger GROUP BY 1,2,3,4 ORDER BY engine, fail_pct DESC NULLS LAST
        ) TO '{summary_path.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    logger.info("wrote %s", ledger_path)
    logger.info("wrote %s", summary_path)

    total, n_checks = con.execute(
        "SELECT count(*), count(DISTINCT engine || '|' || rule_name) FROM ledger"
    ).fetchone()
    logger.info("ledger: %d check-results across %d distinct checks", total, n_checks)
    logger.info("wrote %s", proxy_path)
    logger.info("rollup by engine x tier x status:")
    for eng, tier, st, n in con.execute(
        "SELECT engine, tier, status, count(*) FROM ledger GROUP BY 1,2,3 ORDER BY 1,2,3"
    ).fetchall():
        logger.info("  %-16s %-5s %-5s : %6d", eng, tier, st, n)
    logger.info("bootstrap confidence (flagged rows only):")
    for conf, n in con.execute(
        "SELECT confidence, count(*) FROM ledger_scored WHERE confidence IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        logger.info("  %-22s : %6d", conf, n)
    surf, flagged = con.execute(
        "SELECT sum(CASE WHEN surface THEN 1 ELSE 0 END), "
        "sum(CASE WHEN confidence IS NOT NULL THEN 1 ELSE 0 END) FROM ledger_scored"
    ).fetchone()
    logger.info("surfaced (high-confidence) %d of %d flagged (%.0f%% suppressed as noise/scope)",
                surf or 0, flagged or 0, 100.0*(1-(surf or 0)/(flagged or 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
