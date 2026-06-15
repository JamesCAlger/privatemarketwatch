"""Parametric cross-source agreement gate engine (read-only shadow).

Third shape (after conservation = aggregate-vs-external-total, and identity =
per-row algebraic relation): two INDEPENDENT sources must agree on the same
quantity, joined on a shared key. Disagreement means at least one extraction is
wrong -- a genuinely independent check (neither side can satisfy it by self-edit).

A check is data: a CrossSourceRule names a left and right (source, column) and a
comparator + tolerance. The engine joins the two sources per key and emits
disagreements. Rules whose columns/sources are absent are skipped (logged).

Scope here = fund-level financials across three independent BDC extractions:
  - bdc_fund_highlights  (financial-highlights statement XBRL)
  - bdc_fund_income      (income-statement XBRL)
  - fund_financials      (companyfacts API)
joined on (cik, report_quarter).

NOTE: the classic BDC<->N-PORT same-CUSIP agreement (XS01-06 in validation_rules)
is STRUCTURALLY EMPTY in this dataset -- BDC rows carry no CUSIP (0 of 574K) and
BDC CIKs do not overlap N-PORT CIKs, so 0 shared-CUSIP CIK-quarters exist. It is
documented here as a no-op rather than shipped.

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
    BDC_FUND_HIGHLIGHTS_FILE,
    FUND_FINANCIALS_FILE,
    OUTPUT_DIR,
    OVERRIDES_DIR,
)
from pipeline.config import OUTPUT_DIR as _OUT

BDC_FUND_INCOME_FILE = _OUT / "bdc_fund_income.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_cross_source_engine")

WRAPPER_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"
SHADOW_DIR = OUTPUT_DIR / "shadow"
_CIK_RE = re.compile(r"^\d{10}$")

# Each source: (sql, where, cik_expr, quarter_expr). Aggregated to one value per
# (cik, report_quarter) via max() in the engine.
SOURCES = {
    "highlights": (
        f"read_csv_auto('{BDC_FUND_HIGHLIGHTS_FILE.as_posix()}', sample_size=-1)",
        "(share_class IS NULL OR trim(share_class) = '')",  # entity-level rows
        "CAST(cik AS VARCHAR)", "CAST(report_quarter AS VARCHAR)",
    ),
    "bdc_fund_income": (
        f"read_csv_auto('{BDC_FUND_INCOME_FILE.as_posix()}', sample_size=-1)",
        "TRUE",
        "CAST(cik AS VARCHAR)", "CAST(report_quarter AS VARCHAR)",
    ),
    "fund_financials": (
        f"read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)",
        "source = 'companyfacts'",
        "CAST(cik AS VARCHAR)", "CAST(report_quarter AS VARCHAR)",
    ),
}


@dataclass(frozen=True)
class CrossSourceRule:
    name: str
    left: tuple[str, str]    # (source_key, column)
    right: tuple[str, str]   # (source_key, column)
    comparator: str = "numeric_pct"   # numeric_pct only for now
    tol: float = 0.05
    tier: str = "tight"
    enforcement: str = "advisory"


RULES: list[CrossSourceRule] = [
    # highlights <-> bdc_fund_income (two independent income-statement extractions)
    CrossSourceRule("xs_nii_highlights_vs_income",
                    ("highlights", "net_investment_income"), ("bdc_fund_income", "net_investment_income")),
    CrossSourceRule("xs_tii_highlights_vs_income",
                    ("highlights", "total_investment_income"), ("bdc_fund_income", "total_investment_income")),
    CrossSourceRule("xs_expenses_highlights_vs_income",
                    ("highlights", "total_expenses"), ("bdc_fund_income", "total_expenses")),
    CrossSourceRule("xs_mgmt_fee_highlights_vs_income",
                    ("highlights", "management_fee_expense"), ("bdc_fund_income", "management_fee")),
    # fund_financials <-> bdc_fund_income
    CrossSourceRule("xs_tii_companyfacts_vs_income",
                    ("fund_financials", "total_investment_income"), ("bdc_fund_income", "total_investment_income")),
    CrossSourceRule("xs_nii_companyfacts_vs_income",
                    ("fund_financials", "net_investment_income"), ("bdc_fund_income", "net_investment_income")),
    # highlights <-> fund_financials (NAV / shares)
    CrossSourceRule("xs_nav_highlights_vs_companyfacts",
                    ("highlights", "nav_per_share"), ("fund_financials", "nav_per_share")),
    CrossSourceRule("xs_shares_highlights_vs_companyfacts",
                    ("highlights", "shares_outstanding"), ("fund_financials", "shares_outstanding")),
]


def wrapped_ciks() -> list[str]:
    return sorted(p.stem for p in WRAPPER_DIR.glob("*.json") if _CIK_RE.match(p.stem))


def _columns(con: duckdb.DuckDBPyConnection, sql: str) -> set[str]:
    return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {sql} LIMIT 0").fetchall()}


def _side_agg(con: duckdb.DuckDBPyConnection, source_key: str, col: str, tag: str) -> str | None:
    sql, where, cik_e, q_e = SOURCES[source_key]
    if col not in _columns(con, sql):
        logger.info("    column %s absent in %s", col, source_key)
        return None
    name = f"_{tag}"
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE {name} AS
            SELECT {cik_e} AS cik, {q_e} AS report_quarter,
                   max(TRY_CAST({col} AS DOUBLE)) AS val
            FROM {sql}
            WHERE {where} AND {col} IS NOT NULL
              AND {cik_e} IN (SELECT cik FROM wrapped)
            GROUP BY 1, 2"""
    )
    return name


def run_rule(con: duckdb.DuckDBPyConnection, rule: CrossSourceRule) -> bool:
    lkey, lcol = rule.left
    rkey, rcol = rule.right
    lt = _side_agg(con, lkey, lcol, f"L_{rule.name}")
    rt = _side_agg(con, rkey, rcol, f"R_{rule.name}")
    if lt is None or rt is None:
        logger.info("  SKIP %s", rule.name)
        return False
    con.execute(
        f"""
        CREATE OR REPLACE TABLE result_{rule.name} AS
        SELECT '{rule.name}' AS rule_name, '{rule.tier}' AS tier,
               '{rule.enforcement}' AS enforcement,
               '{lkey}.{lcol}' AS left_src, '{rkey}.{rcol}' AS right_src,
               l.cik, l.report_quarter, l.val AS left_val, r.val AS right_val,
               (l.val - r.val) AS diff,
               CASE WHEN greatest(abs(l.val), abs(r.val)) > 0
                    THEN round(100.0*abs(l.val - r.val)/greatest(abs(l.val), abs(r.val)), 2) END AS pct_diff,
               CASE
                   WHEN abs(l.val - r.val) <= {rule.tol}*greatest(abs(l.val), abs(r.val)) THEN 'agree'
                   ELSE 'disagree'
               END AS status
        FROM {lt} l JOIN {rt} r USING (cik, report_quarter)
        WHERE greatest(abs(l.val), abs(r.val)) > 0
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
    logger.info("cross-source engine: cohort %d CIKs, %d rules (join key cik+report_quarter)",
                len(ciks), len(RULES))

    ran = [r for r in RULES if run_rule(con, r)]
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out = SHADOW_DIR / "cross_source_gate_results.csv"
    union = " UNION ALL ".join(f"SELECT * FROM result_{r.name}" for r in ran)
    if union:
        con.execute(
            f"COPY (SELECT * FROM ({union}) ORDER BY rule_name, status, pct_diff DESC NULLS LAST) "
            f"TO '{out.as_posix()}' (HEADER, DELIMITER ',')"
        )
        logger.info("wrote %s", out)

    logger.info("cross-source agreement (per CIK-quarter, both sources present):")
    for r in ran:
        n, dis, med = con.execute(
            f"SELECT count(*), sum(CASE WHEN status='disagree' THEN 1 ELSE 0 END), "
            f"round(median(pct_diff),2) FROM result_{r.name}"
        ).fetchone()
        rate = (100.0 * (dis or 0) / n) if n else 0.0
        logger.info("  %-36s n=%5d  disagree=%4d (%.1f%%)  median|diff|=%s%%",
                    r.name, n, dis or 0, rate, med)
    return 0


if __name__ == "__main__":
    sys.exit(main())
