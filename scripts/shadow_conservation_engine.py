"""Parametric conservation gate engine (read-only shadow).

Consolidates the ~12 scattered "Sum(component) reconciles to an independent
fund-level total" implementations (A04, E01, E02, V7, F20, GAV adapters, R07,
html aggregate_fv, the nonaccrual chart gate, the shadow FV gate, ...) AND the
cost variant into ONE engine. The RULE declares which column to reconcile and
which anchor(s) to reconcile it against; the engine is generic.

Add a column to validate by adding a ConservationRule -- no new code.

Read-only; writes only to data/output/shadow/.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from pipeline.config import (
    BDC_HOLDINGS_FILE,
    BDC_HOLDINGS_PARQUET_FILE,
    COMPANYFACTS_CACHE_DIR,
    FV_CONSERVATION_BAND_PCT,
    FUND_FINANCIALS_FILE,
    OUTPUT_DIR,
    OVERRIDES_DIR,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_conservation_engine")

WRAPPER_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"
SHADOW_DIR = OUTPUT_DIR / "shadow"
_CIK_RE = re.compile(r"^\d{10}$")

# Grand-total identifier family used for the schedule-total anchor. Excludes
# category/affiliation/cash subtotals so the anchor is the true grand total.
_SCHEDULE_TOTAL_SQL = (
    "(ident_l LIKE 'total %investment%' OR ident_l = 'total investment portfolio' "
    "OR ident_l LIKE 'total portfolio investment%') "
    "AND NOT regexp_matches(ident_l, "
    "'(debt|equity|short-?term|affiliat|controll|non-?control|secured|unsecured|"
    "clo|collateral|joint venture|cash|warrant|structured|senior|subordinat|"
    "first[- ]lien|second[- ]lien|preferred|note|loan|bond|derivative)')"
)


# --------------------------------------------------------------------------
# Rule spec: a conservation check is fully described by data.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Anchor:
    """Where to get the independent fund-level total for one CIK-quarter."""
    kind: str            # 'verified_override' | 'fund_financials' | 'fund_financials_plus_cash'
                         # | 'schedule_total' | 'companyfacts_concept'
    label: str           # tier label recorded in output (e.g. 'companyfacts_fv')
    column: str          # fund_financials column, OR the value column for a schedule total row
    # What the anchor INCLUDES (spec 2026-09-07 s.2): 'published_rows' = everything the schedule
    # lists incl. cash equivalents and look-through rows (directly comparable to the published
    # numerator); 'investments_ex_cash' = the balance-sheet investments line. For
    # verified_override this selects which leaves the anchor reads.
    basis: str = ""


@dataclass(frozen=True)
class ConservationRule:
    """Sum(value_column over unified BDC rows) must reconcile to one of the
    anchors (priority order). tolerance_pct sets the reconcile band."""
    name: str
    value_column: str            # column in unified/bdc_holdings to sum
    anchors: tuple[Anchor, ...]  # priority-ordered
    # default band = the shared FV-conservation constant (pct -> fraction)
    tolerance_pct: float = FV_CONSERVATION_BAND_PCT / 100.0
    tier: str = "tight"
    enforcement: str = "advisory"


RULES: list[ConservationRule] = [
    ConservationRule(
        name="fv_conservation",
        value_column="fair_value",
        anchors=(
            # Priority (spec s.2, plan deviation 1): a verified override exists precisely because
            # companyfacts was partial, so BOTH override bases outrank companyfacts. The
            # published_rows override is directly comparable to the published numerator; an
            # ex-cash override on a cash-holding fund flags an overshoot equal to its cash rows,
            # which is the honest signal that the anchor lane must upgrade its basis.
            Anchor("verified_override", "verified_override", "grand_total", basis="published_rows"),
            Anchor("verified_override", "verified_override_ex_cash", "grand_total",
                   basis="investments_ex_cash"),
            # Deterministic published-rows candidate: companyfacts FV + the filer's tagged cash
            # equivalents (fund_financials.cash_equivalents_at_fair_value), only for cik-quarters
            # that hold a CASH row in unified.
            Anchor("fund_financials_plus_cash", "companyfacts_fv_plus_cash",
                   "investments_at_fair_value", basis="published_rows"),
            Anchor("fund_financials", "companyfacts_fv", "investments_at_fair_value",
                   basis="investments_ex_cash"),
            Anchor("schedule_total", "schedule_total", "fair_value", basis="investments_ex_cash"),
        ),
    ),
    ConservationRule(
        name="cost_conservation",
        value_column="cost",
        anchors=(
            # PRIMARY: fund_financials.investments_at_cost -- the production column promoted
            # 2026-06-16 (path B), sourced from companyfacts InvestmentOwnedAtCost. Using it
            # closes the loop with production and removes the bespoke cache read as the main
            # path. FALLBACK: the direct companyfacts-cache read (ensure_companyfacts_cost),
            # in case fund_financials' quarterly-dedup dropped a report_date. LAST: schedule
            # total. (Was schedule-only at 0.5% before 2026-06-16; coverage 17% -> ~88%.)
            # Cost anchors are ex-cash by construction; the basis is informational here.
            Anchor("fund_financials", "ff_investments_at_cost", "investments_at_cost",
                   basis="investments_ex_cash"),
            Anchor("companyfacts_concept", "cf_cache_cost", "InvestmentOwnedAtCost",
                   basis="investments_ex_cash"),
            Anchor("schedule_total", "schedule_total_cost", "cost", basis="investments_ex_cash"),
        ),
        # 5% band: cost-vs-companyfacts has inherent scope/timing noise, and the unified cost
        # numerator includes ~13% cost-proxy fills (cost==fair_value). 0.5% is unrealistic.
        tolerance_pct=0.05,
    ),
]


def _unified() -> str:
    if UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{UNIFIED_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def _bdc() -> str:
    if BDC_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{BDC_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{BDC_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def wrapped_ciks() -> list[str]:
    return sorted(p.stem for p in WRAPPER_DIR.glob("*.json") if _CIK_RE.match(p.stem))


_CF_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")


def ensure_companyfacts_cost(con: duckdb.DuckDBPyConnection) -> int:
    """Build TEMP TABLE _cf_cost(cik, report_date, anchor_value) from the cached
    companyfacts InvestmentOwnedAtCost (undimensioned fund-level total). Cache-only,
    no network. Must be called (with a `wrapped` table present) before running any
    rule that uses a companyfacts_concept anchor.
    """
    ciks = [r[0] for r in con.execute("SELECT cik FROM wrapped").fetchall()]
    rows: list[tuple[str, str, float]] = []
    for cik in ciks:
        p = COMPANYFACTS_CACHE_DIR / f"{cik}.json"
        if not p.exists():
            continue
        try:
            node = json.loads(p.read_text()).get("facts", {}).get("us-gaap", {}).get("InvestmentOwnedAtCost")
        except Exception:
            continue
        if not node:
            continue
        best: dict[str, float] = {}
        for v in node.get("units", {}).get("USD", []):
            if v.get("form") not in _CF_FORMS:
                continue
            end, val = v.get("end"), v.get("val")
            if end and val is not None:
                best[end] = max(best.get(end, 0.0), float(val))
        rows.extend((cik, end, val) for end, val in best.items())
    con.execute("CREATE OR REPLACE TEMP TABLE _cf_cost(cik VARCHAR, report_date VARCHAR, anchor_value DOUBLE)")
    if rows:
        con.executemany("INSERT INTO _cf_cost VALUES (?, ?, ?)", rows)
    return len(rows)


def ensure_anchor_overrides(con: duckdb.DuckDBPyConnection) -> int:
    """TEMP TABLE _anchor_override(cik, report_date, anchor_value, basis) from the promoted
    Anchor-Adjudicator leaves that declare a basis (leaves without one are ignored upstream)."""
    from pipeline.agent_promoted import load_anchor_overrides
    rows = [(o["cik"], o["report_date"], o["anchor_value"], o["basis"])
            for o in load_anchor_overrides()]
    con.execute("CREATE OR REPLACE TEMP TABLE _anchor_override("
                "cik VARCHAR, report_date VARCHAR, anchor_value DOUBLE, basis VARCHAR)")
    if rows:
        con.executemany("INSERT INTO _anchor_override VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def _anchor_table_sql(anchor: Anchor) -> str:
    """SQL returning (cik, report_date, anchor_value) for one anchor kind."""
    if anchor.kind == "verified_override":
        # Reads the table built by ensure_anchor_overrides() (promoted adjudications).
        b = anchor.basis.replace("'", "''")
        return f"SELECT cik, report_date, anchor_value FROM _anchor_override WHERE basis = '{b}'"
    if anchor.kind == "fund_financials_plus_cash":
        # Column probe: fund_financials.cash_equivalents_at_fair_value lands with Task 6; an
        # older CSV simply yields no rows for this anchor (falls through to the next).
        cols = {r[0].lower() for r in duckdb.connect().execute(
            f"DESCRIBE SELECT * FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1) LIMIT 0"
        ).fetchall()}
        if "cash_equivalents_at_fair_value" not in cols:
            return "SELECT CAST(NULL AS VARCHAR) AS cik, CAST(NULL AS VARCHAR) AS report_date, CAST(NULL AS DOUBLE) AS anchor_value WHERE false"
        return f"""
            SELECT f.cik, f.report_date, f.ifv + f.cash AS anchor_value
            FROM (
                -- substr(...,1,10): _cash_rows and _sum_<rule> normalise report_date the same
                -- way, so keep the join key 10 chars even if the column parses as TIMESTAMP.
                SELECT CAST(cik AS VARCHAR) AS cik,
                       substr(CAST(report_date AS VARCHAR), 1, 10) AS report_date,
                       max(TRY_CAST({anchor.column} AS DOUBLE)) AS ifv,
                       max(TRY_CAST(cash_equivalents_at_fair_value AS DOUBLE)) AS cash
                FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
                WHERE source='companyfacts'
                GROUP BY 1, 2
            ) f
            JOIN _cash_rows c USING (cik, report_date)
            WHERE f.ifv IS NOT NULL AND f.cash IS NOT NULL
        """
    if anchor.kind == "fund_financials":
        return f"""
            SELECT CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date,
                   max(TRY_CAST({anchor.column} AS DOUBLE)) AS anchor_value
            FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
            WHERE source='companyfacts' AND {anchor.column} IS NOT NULL
            GROUP BY 1, 2
        """
    if anchor.kind == "schedule_total":
        return f"""
            SELECT CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date,
                   max(TRY_CAST({anchor.column} AS DOUBLE)) AS anchor_value
            FROM (
                SELECT cik, report_date, {anchor.column},
                       lower(trim(COALESCE(investment_identifier,''))) AS ident_l
                FROM {_bdc()}
                WHERE CAST(period AS VARCHAR) = CAST(report_date AS VARCHAR)
                  AND {anchor.column} IS NOT NULL
            )
            WHERE {_SCHEDULE_TOTAL_SQL}
            GROUP BY 1, 2
        """
    if anchor.kind == "companyfacts_concept":
        # Reads the table built by ensure_companyfacts_cost() (cache-only extraction).
        return "SELECT cik, report_date, anchor_value FROM _cf_cost"
    raise ValueError(f"unknown anchor kind: {anchor.kind}")


def run_rule(con: duckdb.DuckDBPyConnection, rule: ConservationRule) -> None:
    """Run one conservation rule into result_<rule>: the PUBLISHED-basis sum of value_column
    over every unified row of each wrapped CIK-quarter (spec 2026-09-07 s.1 -- no cash,
    subsidiary, or dimension filter; what the headline sums is what the gate sums) against
    the first available anchor in priority order."""
    from pipeline.published_basis import published_fv_sum_sql
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE _sum_{rule.name} AS "
        + published_fv_sum_sql(_unified(),
                               f"lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') "
                               f"IN (SELECT cik FROM wrapped)")
        .replace("TRY_CAST(fair_value AS DOUBLE)", f"TRY_CAST({rule.value_column} AS DOUBLE)")
    )
    # cik-quarters holding at least one CASH row (gates the companyfacts_fv_plus_cash anchor)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _cash_rows AS
        SELECT DISTINCT lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
               substr(CAST(report_date AS VARCHAR), 1, 10) AS report_date
        FROM {_unified()}
        WHERE upper(COALESCE(CAST(asset_category AS VARCHAR), '')) = 'CASH'
        """
    )
    anchor_ctes, coalesce_val, coalesce_label, coalesce_basis = [], [], [], []
    for i, a in enumerate(rule.anchors):
        con.execute(f"CREATE OR REPLACE TEMP TABLE _a{i}_{rule.name} AS {_anchor_table_sql(a)}")
        anchor_ctes.append(f"LEFT JOIN _a{i}_{rule.name} a{i} USING (cik, report_date)")
        coalesce_val.append(f"a{i}.anchor_value")
        coalesce_label.append(f"WHEN a{i}.anchor_value IS NOT NULL THEN '{a.label}'")
        coalesce_basis.append(f"WHEN a{i}.anchor_value IS NOT NULL THEN '{a.basis}'")
    val_expr = "COALESCE(" + ", ".join(coalesce_val) + ")"
    label_expr = "CASE " + " ".join(coalesce_label) + " ELSE 'none' END"
    basis_expr = "CASE " + " ".join(coalesce_basis) + " ELSE '' END"
    tol = rule.tolerance_pct
    con.execute(
        f"""
        CREATE OR REPLACE TABLE result_{rule.name} AS
        SELECT
            '{rule.name}' AS rule_name,
            '{rule.value_column}' AS value_column,
            '{rule.tier}' AS tier,
            '{rule.enforcement}' AS enforcement,
            s.cik, s.report_date, s.n_rows,
            s.value_sum,
            {val_expr} AS anchor_value,
            {label_expr} AS anchor_used,
            {basis_expr} AS anchor_basis,
            CASE WHEN {val_expr} IS NOT NULL AND {val_expr} <> 0
                 THEN round(100.0*(s.value_sum - {val_expr})/{val_expr}, 3) END AS residual_pct,
            CASE
                WHEN {val_expr} IS NULL THEN 'no_anchor'
                WHEN abs(s.value_sum - {val_expr}) <= {tol}*abs({val_expr}) THEN 'reconciles'
                WHEN s.value_sum > {val_expr} THEN 'overshoot'
                ELSE 'undershoot'
            END AS status
        FROM _sum_{rule.name} s
        {' '.join(anchor_ctes)}
        """
    )


def main(argv: list[str] | None = None) -> int:
    ciks = wrapped_ciks()
    if not ciks:
        logger.error("no wrapper CIK configs in %s", WRAPPER_DIR)
        return 1
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in ciks])
    n_cf = ensure_companyfacts_cost(con)
    n_ov = ensure_anchor_overrides(con)
    logger.info("conservation engine: cohort %d CIKs, %d rules, %d companyfacts cost facts, "
                "%d verified anchor overrides",
                len(ciks), len(RULES), n_cf, n_ov)

    for rule in RULES:
        run_rule(con, rule)

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out = SHADOW_DIR / "conservation_gate_results.csv"
    union = " UNION ALL ".join(f"SELECT * FROM result_{r.name}" for r in RULES)
    con.execute(
        f"""
        COPY (
            SELECT * FROM ({union})
            ORDER BY rule_name, status, abs(COALESCE(residual_pct, 0)) DESC
        )
        TO '{out.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    logger.info("wrote %s", out)

    for rule in RULES:
        logger.info("[%s] (column=%s, tier=%s) status:", rule.name, rule.value_column, rule.tier)
        for st, n in con.execute(
            f"SELECT status, count(*) FROM result_{rule.name} GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall():
            logger.info("    %-12s : %4d", st, n)
        med = con.execute(
            f"SELECT round(median(value_sum/anchor_value), 4) FROM result_{rule.name} "
            "WHERE anchor_value IS NOT NULL AND anchor_value > 0"
        ).fetchone()[0]
        logger.info("    median value_sum/anchor = %s (want ~1.0)", med)
    return 0


if __name__ == "__main__":
    sys.exit(main())
