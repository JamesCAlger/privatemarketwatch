"""Parametric per-row identity gate engine (read-only shadow).

Sibling to scripts/shadow_conservation_engine.py. Where the conservation engine
reconciles an AGGREGATE (Sum over rows) against an EXTERNAL fund-level total, this
engine checks an ALGEBRAIC RELATIONSHIP AMONG FIELDS OF A SINGLE ROW (optionally
plus one per-quarter scalar). It is self-localizing -- the failing row is the
locus -- and catches per-field errors (mis-scaled rate, wrong pct, sign flip,
violated ordering) that an aggregate sum check is blind to.

A check is data: an IdentityRule names the table, the columns it needs, an
optional per-quarter scalar to join, and a SQL boolean that is TRUE when the
identity holds. The engine evaluates it per row and emits the violating rows.

Read-only; writes only to data/output/shadow/. Rules whose columns are absent in
the source are skipped (logged), so it is safe across schema variation.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
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
logger = logging.getLogger("shadow_identity_engine")

WRAPPER_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"
SHADOW_DIR = OUTPUT_DIR / "shadow"
_CIK_RE = re.compile(r"^\d{10}$")


def _unified() -> str:
    if UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{UNIFIED_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def _ff() -> str:
    return f"read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)"


# Source config: (table_sql, where, cik_expr, report_date_expr, row_id_expr)
SOURCES = {
    "unified": (_unified(), "bdc_dimensions_raw IS NOT NULL "
                "AND CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped)",
                "CAST(cik AS VARCHAR)", "CAST(report_date AS VARCHAR)",
                "bdc_investment_identifier"),
    "fund_financials": (_ff(), "source = 'companyfacts'",
                        "CAST(cik AS VARCHAR)", "CAST(report_date AS VARCHAR)",
                        "entity_name"),
}


@dataclass(frozen=True)
class IdentityRule:
    name: str
    table: str                       # key in SOURCES
    needed_cols: tuple[str, ...]     # columns required (existence + NOT NULL gated)
    holds_sql: str                   # boolean, TRUE when identity holds (col names + _scalar)
    residual_sql: str                # signed residual expression
    row_filter: str = "TRUE"         # extra WHERE (may reference _scalar)
    scalar: tuple[str, str] | None = None  # (source_key, column) joined as _scalar per cik+rd
    tol_note: str = ""
    tier: str = "tight"
    enforcement: str = "advisory"


RULES: list[IdentityRule] = [
    # position-level (unified)
    IdentityRule(
        name="pct_of_net_assets_identity", table="unified",
        needed_cols=("fair_value", "pct_of_net_assets"),
        scalar=("fund_financials", "net_assets"),
        row_filter="pct_of_net_assets > 0 AND _scalar > 0 AND fair_value <> 0",
        holds_sql="abs(fair_value - pct_of_net_assets/100.0*_scalar) <= 0.10*abs(fair_value)",
        residual_sql="fair_value - pct_of_net_assets/100.0*_scalar",
        tol_note="FV = pct/100 * net_assets, 10% rel-to-FV (pct rounding)",
    ),
    IdentityRule(
        name="pik_le_interest_rate", table="unified",
        needed_cols=("pik_rate", "interest_rate"),
        row_filter="pik_rate > 0 AND interest_rate > 0",
        holds_sql="pik_rate <= interest_rate + 0.001",
        residual_sql="pik_rate - interest_rate",
        tol_note="pik_rate <= interest_rate",
    ),
    # fund-level (fund_financials -- the reliable balance-sheet schema)
    IdentityRule(
        name="nav_identity", table="fund_financials",
        needed_cols=("nav_per_share", "shares_outstanding", "net_assets"),
        row_filter="net_assets <> 0",
        holds_sql="abs(nav_per_share*shares_outstanding - net_assets) <= 0.02*abs(net_assets)",
        residual_sql="nav_per_share*shares_outstanding - net_assets",
        tol_note="nav_per_share * shares ~ net_assets, 2%",
    ),
    IdentityRule(
        name="income_identity", table="fund_financials",
        needed_cols=("net_investment_income", "total_investment_income", "total_expenses"),
        row_filter="total_investment_income <> 0",
        holds_sql="abs(net_investment_income - (total_investment_income - total_expenses)) "
                  "<= 0.05*abs(total_investment_income)",
        residual_sql="net_investment_income - (total_investment_income - total_expenses)",
        tol_note="NII ~ total_investment_income - total_expenses, 5%",
    ),
    IdentityRule(
        name="balance_sheet_identity", table="fund_financials",
        needed_cols=("total_assets", "total_liabilities", "net_assets"),
        row_filter="total_assets > 0",
        holds_sql="abs(total_assets - total_liabilities - net_assets) <= 0.01*abs(total_assets)",
        residual_sql="total_assets - total_liabilities - net_assets",
        tol_note="TA - TL ~ net_assets, 1% (companyfacts schema)",
    ),
]


def wrapped_ciks() -> list[str]:
    return sorted(p.stem for p in WRAPPER_DIR.glob("*.json") if _CIK_RE.match(p.stem))


def _columns(con: duckdb.DuckDBPyConnection, source_sql: str) -> set[str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM {source_sql} LIMIT 0").fetchall()
    return {r[0] for r in rows}


def run_rule(con: duckdb.DuckDBPyConnection, rule: IdentityRule,
             cols_cache: dict[str, set[str]]) -> bool:
    src_sql, where, cik_e, rd_e, id_e = SOURCES[rule.table]
    avail = cols_cache.setdefault(rule.table, _columns(con, src_sql))
    missing = [c for c in rule.needed_cols if c not in avail]
    if missing:
        logger.info("  SKIP %-26s missing columns: %s", rule.name, missing)
        return False

    col_casts = ", ".join(f"TRY_CAST({c} AS DOUBLE) AS {c}" for c in rule.needed_cols)
    base = f"""
        SELECT {cik_e} AS cik, {rd_e} AS report_date, {id_e} AS row_id, {col_casts}
        FROM {src_sql} WHERE {where}
    """
    scalar_join, scalar_sel, scalar_gate = "", "", ""
    if rule.scalar:
        s_src_key, s_col = rule.scalar
        s_sql, s_where, s_cik, s_rd, _ = SOURCES[s_src_key]
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE _scalar_{rule.name} AS
                SELECT {s_cik} AS cik, {s_rd} AS report_date, max(TRY_CAST({s_col} AS DOUBLE)) AS _scalar
                FROM {s_sql} WHERE {s_where} GROUP BY 1, 2"""
        )
        scalar_join = f"LEFT JOIN _scalar_{rule.name} sc USING (cik, report_date)"
        scalar_sel = "sc._scalar,"
        scalar_gate = "AND sc._scalar IS NOT NULL"

    not_null = " AND ".join(f"b.{c} IS NOT NULL" for c in rule.needed_cols)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE result_{rule.name} AS
        SELECT '{rule.name}' AS rule_name, '{rule.tier}' AS tier,
               '{rule.enforcement}' AS enforcement, b.cik, b.report_date, b.row_id,
               {", ".join("b."+c for c in rule.needed_cols)}, {scalar_sel}
               ({rule.residual_sql.replace('_scalar','sc._scalar') if rule.scalar else rule.residual_sql}) AS residual,
               ({rule.holds_sql.replace('_scalar','sc._scalar') if rule.scalar else rule.holds_sql}) AS holds
        FROM ({base}) b
        {scalar_join}
        WHERE {not_null} {scalar_gate}
          AND ({rule.row_filter.replace('_scalar','sc._scalar') if rule.scalar else rule.row_filter})
        """
    )
    return True


def main(argv: list[str] | None = None) -> int:
    ciks = wrapped_ciks()
    if not ciks:
        logger.error("no wrapper CIK configs in %s", WRAPPER_DIR)
        return 1
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in ciks])
    logger.info("identity engine: cohort %d CIKs, %d rules", len(ciks), len(RULES))

    cols_cache: dict[str, set[str]] = {}
    ran = [r for r in RULES if run_rule(con, r, cols_cache)]

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    viol = SHADOW_DIR / "identity_gate_violations.csv"
    union = " UNION ALL ".join(
        f"SELECT rule_name, tier, enforcement, cik, report_date, row_id, residual "
        f"FROM result_{r.name} WHERE NOT holds" for r in ran
    )
    if union:
        con.execute(
            f"COPY (SELECT * FROM ({union}) ORDER BY rule_name, abs(residual) DESC) "
            f"TO '{viol.as_posix()}' (HEADER, DELIMITER ',')"
        )
        logger.info("wrote %s", viol)

    logger.info("identity gate (per-row):")
    for r in ran:
        n_eval, n_viol = con.execute(
            f"SELECT count(*), sum(CASE WHEN NOT holds THEN 1 ELSE 0 END) FROM result_{r.name}"
        ).fetchone()
        rate = (100.0 * (n_viol or 0) / n_eval) if n_eval else 0.0
        logger.info("  %-26s eval=%6d  violations=%5d (%.2f%%)   [%s]",
                    r.name, n_eval, n_viol or 0, rate, r.tol_note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
