"""Parametric field-validity WEAK gate engine (read-only shadow).

The weak counterpart to the three tight engines. Covers the simple field-validity
families from the validation inventory (column_validation C/X/FX-series, oracle
F-series): range / sign / enum / format / date / fill. These are NOT tight checks
-- they are plausibility flags, not reconciliations -- so they emit status `warn`
(never `fail`) and enforcement `flag` (never blocking). A weak warn is a signal
and a quality-tier input; it must never gate.

A check is data: a WeakRule names the table, kind, column(s), gate (rows to
evaluate) and the OK predicate (or fill threshold). The engine rolls up per
(cik, report_date) to status pass|warn.

Read-only; writes only to data/output/shadow/.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

from pipeline.config import (
    OUTPUT_DIR,
    OVERRIDES_DIR,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_weak_engine")

WRAPPER_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"
SHADOW_DIR = OUTPUT_DIR / "shadow"
_CIK_RE = re.compile(r"^\d{10}$")


@dataclass(frozen=True)
class WeakRule:
    name: str
    kind: str            # 'row' (per-row predicate, rolled up) | 'fill' (coverage)
    gate_sql: str        # which rows to evaluate (e.g. "interest_rate IS NOT NULL")
    # row kind: holds_sql is the OK predicate. fill kind: present_sql + threshold.
    holds_sql: str = "TRUE"
    present_sql: str = "TRUE"
    threshold: float = 0.0
    min_n: int = 1
    note: str = ""
    tier: str = "weak"
    enforcement: str = "flag"


RULES: list[WeakRule] = [
    WeakRule("interest_rate_range", "row", "interest_rate IS NOT NULL",
             holds_sql="interest_rate BETWEEN 0 AND 25", note="rate in [0,25]%"),
    WeakRule("basis_spread_range", "row", "basis_spread IS NOT NULL",
             holds_sql="basis_spread BETWEEN 0 AND 15", note="spread in [0,15]%"),
    WeakRule("pik_rate_range", "row", "pik_rate IS NOT NULL",
             holds_sql="pik_rate BETWEEN 0 AND 20", note="pik in [0,20]%"),
    WeakRule("pct_position_concentration", "row", "pct_of_net_assets IS NOT NULL",
             holds_sql="pct_of_net_assets BETWEEN 0 AND 25",
             note="per-position pct in [0,25]% (concentration flag)"),
    WeakRule("shares_held_sign", "row", "shares_held IS NOT NULL",
             holds_sql="shares_held >= 0", note="shares >= 0"),
    WeakRule("coupon_type_enum", "row", "coupon_type IS NOT NULL AND trim(coupon_type) <> ''",
             holds_sql="coupon_type IN ('Fixed','Floating','Variable')",
             note="coupon_type in {Fixed,Floating,Variable}"),
    WeakRule("issuer_name_length", "row", "issuer_name IS NOT NULL AND trim(issuer_name) <> ''",
             holds_sql="length(issuer_name) BETWEEN 3 AND 300", note="issuer length [3,300]"),
    WeakRule("maturity_not_past", "row",
             "index_classification = 'DIRECT_LENDING' AND maturity_date IS NOT NULL "
             "AND TRY_CAST(maturity_date AS DATE) IS NOT NULL "
             "AND CAST(maturity_date AS VARCHAR) <> '9999-12-31'",
             holds_sql="TRY_CAST(maturity_date AS DATE) >= TRY_CAST(report_date AS DATE)",
             note="DL maturity >= report_date"),
    WeakRule("dl_rate_fill", "fill", "index_classification = 'DIRECT_LENDING'",
             present_sql="interest_rate IS NOT NULL OR basis_spread IS NOT NULL",
             threshold=0.80, min_n=10, note="DL rows with rate/spread >= 80%"),
]


def _unified() -> str:
    if UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{UNIFIED_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def wrapped_ciks() -> list[str]:
    return sorted(p.stem for p in WRAPPER_DIR.glob("*.json") if _CIK_RE.match(p.stem))


def ensure_base(con: duckdb.DuckDBPyConnection) -> None:
    if con.execute("SELECT count(*) FROM information_schema.tables "
                   "WHERE table_name='weak_base'").fetchone()[0]:
        return
    con.execute(
        f"""
        CREATE TABLE weak_base AS
        SELECT CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date,
               TRY_CAST(interest_rate AS DOUBLE) AS interest_rate,
               TRY_CAST(basis_spread AS DOUBLE) AS basis_spread,
               TRY_CAST(pik_rate AS DOUBLE) AS pik_rate,
               TRY_CAST(pct_of_net_assets AS DOUBLE) AS pct_of_net_assets,
               TRY_CAST(shares_held AS DOUBLE) AS shares_held,
               coupon_type, issuer_name, maturity_date, index_classification
        FROM {_unified()}
        WHERE bdc_dimensions_raw IS NOT NULL
          AND CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped)
        """
    )


def run_rule(con: duckdb.DuckDBPyConnection, rule: WeakRule) -> None:
    if rule.kind == "row":
        con.execute(
            f"""
            CREATE OR REPLACE TABLE result_{rule.name} AS
            WITH e AS (
                SELECT cik, report_date, ({rule.holds_sql}) AS holds
                FROM weak_base WHERE ({rule.gate_sql})
            )
            SELECT '{rule.name}' AS rule_name, '{rule.tier}' AS tier,
                   '{rule.enforcement}' AS enforcement, cik, report_date,
                   count(*) AS n_units,
                   sum(CASE WHEN NOT holds THEN 1 ELSE 0 END) AS n_violate,
                   CASE WHEN sum(CASE WHEN NOT holds THEN 1 ELSE 0 END) > 0 THEN 'warn' ELSE 'pass' END AS status,
                   round(100.0*sum(CASE WHEN NOT holds THEN 1 ELSE 0 END)/count(*), 2) AS metric
            FROM e GROUP BY cik, report_date
            """
        )
    elif rule.kind == "fill":
        con.execute(
            f"""
            CREATE OR REPLACE TABLE result_{rule.name} AS
            WITH e AS (
                SELECT cik, report_date, ({rule.present_sql}) AS present
                FROM weak_base WHERE ({rule.gate_sql})
            )
            SELECT '{rule.name}' AS rule_name, '{rule.tier}' AS tier,
                   '{rule.enforcement}' AS enforcement, cik, report_date,
                   count(*) AS n_units,
                   sum(CASE WHEN NOT present THEN 1 ELSE 0 END) AS n_violate,
                   CASE WHEN avg(CASE WHEN present THEN 1.0 ELSE 0 END) < {rule.threshold} THEN 'warn' ELSE 'pass' END AS status,
                   round(100.0*avg(CASE WHEN present THEN 1.0 ELSE 0 END), 1) AS metric
            FROM e GROUP BY cik, report_date HAVING count(*) >= {rule.min_n}
            """
        )
    else:
        raise ValueError(f"unknown weak kind {rule.kind}")


def main(argv: list[str] | None = None) -> int:
    ciks = wrapped_ciks()
    if not ciks:
        logger.error("no wrapper CIK configs in %s", WRAPPER_DIR)
        return 1
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in ciks])
    ensure_base(con)
    logger.info("weak engine: cohort %d CIKs, %d rules", len(ciks), len(RULES))

    for r in RULES:
        run_rule(con, r)

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out = SHADOW_DIR / "weak_gate_results.csv"
    union = " UNION ALL ".join(
        f"SELECT rule_name, tier, enforcement, cik, report_date, status, metric, n_units, n_violate "
        f"FROM result_{r.name}" for r in RULES
    )
    con.execute(
        f"COPY (SELECT * FROM ({union}) ORDER BY rule_name, status DESC, metric DESC) "
        f"TO '{out.as_posix()}' (HEADER, DELIMITER ',')"
    )
    logger.info("wrote %s", out)

    logger.info("weak field-validity gate (per CIK-quarter; status pass|warn):")
    for r in RULES:
        row = con.execute(
            f"SELECT count(*), sum(CASE WHEN status='warn' THEN 1 ELSE 0 END), "
            f"sum(n_violate), sum(n_units) FROM result_{r.name}"
        ).fetchone()
        n_cq, n_warn, n_viol, n_units = (row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0)
        rate = (100.0 * n_warn / n_cq) if n_cq else 0.0
        logger.info("  %-28s cik-qtrs=%4d  warn=%4d (%.1f%%)  rows=%7d viol=%6d   [%s]",
                    r.name, n_cq, n_warn, rate, n_units, n_viol, r.note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
