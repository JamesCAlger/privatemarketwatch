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
from pipeline.companyfacts_store import companyfacts_path
from pipeline.published_basis import CIK10_SQL, PUBLISHED_ROWS_WHERE_SQL, REPORT_DATE_KEY_SQL

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
        p = companyfacts_path(cik, COMPANYFACTS_CACHE_DIR)
        if p is None:
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


def _anchor_table_sql(anchor: Anchor, sum_table: str | None = None) -> str:
    """SQL returning (cik, report_date, anchor_value) for one anchor kind. sum_table: the rule's
    published-sum table (cik, report_date, value_sum), read by the plus-cash anchor."""
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
        band = FV_CONSERVATION_BAND_PCT / 100.0
        # No double add (owner ruling 2026-11-04, conservation-anchor-adds-stale-cash-
        # equivalents-already-in-investments): where the published total, cash rows included,
        # already equals the filed investments line and the line plus the filed cash figure does
        # not, the line holds the cash rows; adding the filed cash counts them twice. The anchor
        # then gives way to the next (companyfacts_fv). Barings Private Credit Corp II from
        # 2025-06-30: published 3,160,570,000 = filed investments, which hold the BlackRock
        # T-Fund row; the filed cash-equivalents figure 62,915,000 is the 2024-12-31 value the
        # filer re-tags each quarter. Not applied to a filer whose wrapper says the line leaves
        # the cash rows out.
        no_double_add = "" if not sum_table else f"""
              AND NOT (f.cik NOT IN (SELECT cik FROM _cash_outside_total)
                       AND abs(t.value_sum - f.ifv) <= {band} * abs(f.ifv)
                       AND abs(t.value_sum - (f.ifv + f.cash)) > {band} * abs(f.ifv + f.cash))"""
        sum_join = f"JOIN {sum_table} t USING (cik, report_date)" if sum_table else ""
        return f"""
            SELECT f.cik, f.report_date, f.ifv + f.cash AS anchor_value
            FROM (
                -- Join keys come from pipeline.published_basis so this anchor, _cash_rows and
                -- _sum_<rule> normalise cik and report_date identically even if the column
                -- parses as TIMESTAMP or the cik loses its leading zeros.
                -- The filed concepts a wrapper says the cash rows also hold
                -- (cash_rows_include_concepts, e.g. restricted cash equivalents) are added to the
                -- filed cash figure; _filed_cash_extra is built by run_rule.
                SELECT ff.cik, ff.report_date, ff.ifv, ff.cash + coalesce(e.extra, 0) AS cash
                FROM (
                    SELECT {CIK10_SQL} AS cik,
                           {REPORT_DATE_KEY_SQL} AS report_date,
                           max(TRY_CAST({anchor.column} AS DOUBLE)) AS ifv,
                           max(TRY_CAST(cash_equivalents_at_fair_value AS DOUBLE)) AS cash
                    FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
                    WHERE source='companyfacts'
                    GROUP BY 1, 2
                ) ff
                LEFT JOIN _filed_cash_extra e USING (cik, report_date)
            ) f
            JOIN _cash_rows c USING (cik, report_date)
            JOIN _cash_sum s USING (cik, report_date)
            {sum_join}
            WHERE f.ifv IS NOT NULL AND f.cash IS NOT NULL{no_double_add}
              -- For a filer whose wrapper says its investments total leaves the cash rows out:
              -- comparable only when the filed figure IS the schedule's cash rows. A
              -- balance-sheet figure that also holds deposits (Oaktree 2025-06-30: filed 471.3M,
              -- schedule row 100.7M) cannot anchor the rows; the ex-cash anchor takes the quarter.
              AND (f.cik NOT IN (SELECT cik FROM _cash_outside_total)
                   OR abs(s.cash_sum - f.cash) <= {FV_CONSERVATION_BAND_PCT / 100.0} * (f.ifv + f.cash))
        """
    if anchor.kind == "fund_financials":
        # Same published-basis join keys as the plus_cash branch above: without them a
        # TIMESTAMP-typed report_date would silently match nothing in _sum_<rule>.
        return f"""
            SELECT {CIK10_SQL} AS cik, {REPORT_DATE_KEY_SQL} AS report_date,
                   max(TRY_CAST({anchor.column} AS DOUBLE)) AS anchor_value
            FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
            WHERE source='companyfacts' AND {anchor.column} IS NOT NULL
            GROUP BY 1, 2
        """
    if anchor.kind == "schedule_total":
        # Same published-basis join keys as the fund_financials branches; the inner
        # period = report_date filter stays on the raw columns (one table, one type).
        return f"""
            SELECT {CIK10_SQL} AS cik, {REPORT_DATE_KEY_SQL} AS report_date,
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
    # Published cash rows of each cik-quarter, in the rule's value column, and the filed
    # cash-equivalents figure where fund_financials has one.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _cash_sum AS
        SELECT lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
               substr(CAST(report_date AS VARCHAR), 1, 10) AS report_date,
               coalesce(sum(TRY_CAST({rule.value_column} AS DOUBLE)), 0) AS cash_sum
        FROM {_unified()}
        WHERE upper(COALESCE(CAST(asset_category AS VARCHAR), '')) = 'CASH' AND ({PUBLISHED_ROWS_WHERE_SQL})
        GROUP BY 1, 2
        """
    )
    # Filed figures the schedule's cash rows also hold, per the wrapper's cash_rows_include_concepts
    # (Silver Point: restricted cash equivalents). Added to the filed cash-equivalents figure
    # where one is filed for the date; never a value the pipeline derived.
    con.execute("CREATE OR REPLACE TEMP TABLE _filed_cash_extra(cik VARCHAR, report_date VARCHAR, extra DOUBLE)")
    extra_rows = filed_cash_addend_rows()
    if extra_rows:
        con.executemany("INSERT INTO _filed_cash_extra VALUES (?, ?, ?)", extra_rows)
    con.execute(f"CREATE OR REPLACE TEMP TABLE _filed_cash AS {_filed_cash_sql()}")
    con.execute("UPDATE _filed_cash SET filed_cash = filed_cash + e.extra FROM _filed_cash_extra e "
                "WHERE _filed_cash.cik = e.cik AND _filed_cash.report_date = e.report_date")
    con.execute("CREATE OR REPLACE TEMP TABLE _cash_outside_total(cik VARCHAR)")
    declared = cash_outside_total_ciks()
    if declared:
        con.executemany("INSERT INTO _cash_outside_total VALUES (?)", [(c,) for c in declared])
    con.execute("CREATE OR REPLACE TEMP TABLE _cost_cash_split(cik VARCHAR)")
    cost_split = cost_split_ciks()
    if cost_split:
        con.executemany("INSERT INTO _cost_cash_split VALUES (?)", [(c,) for c in cost_split])
    anchor_ctes, coalesce_val, coalesce_label, coalesce_basis = [], [], [], []
    sum_table = f"_sum_{rule.name}"
    for i, a in enumerate(rule.anchors):
        con.execute(f"CREATE OR REPLACE TEMP TABLE _a{i}_{rule.name} AS {_anchor_table_sql(a, sum_table=sum_table)}")
        anchor_ctes.append(f"LEFT JOIN _a{i}_{rule.name} a{i} USING (cik, report_date)")
        coalesce_val.append(f"a{i}.anchor_value")
        coalesce_label.append(f"WHEN a{i}.anchor_value IS NOT NULL THEN '{a.label}'")
        coalesce_basis.append(f"WHEN a{i}.anchor_value IS NOT NULL THEN '{a.basis}'")
    val_expr = "COALESCE(" + ", ".join(coalesce_val) + ")"
    label_expr = "CASE " + " ".join(coalesce_label) + " ELSE 'none' END"
    basis_expr = "CASE " + " ".join(coalesce_basis) + " ELSE '' END"
    tol = rule.tolerance_pct
    # Like with like (owner ruling 2026-10-09), for filers whose wrapper declares
    # source_encodings.investments_total_excludes = ["cash_rows"]. Cash rows stay in value_sum,
    # the published total. Such a filer's investments line holds no cash, so it is compared
    # with the published rows that are not cash; the cash rows are then checked against the
    # filed cash-equivalents figure, which they may not exceed. Where no such figure is filed
    # the cash rows are not anchored and cash_status says so. Before this, an ex-cash anchor on
    # such a fund failed by exactly its cash row (Goldman Sachs 2025-06-30: 233.3M of 9,630.9M).
    # Not the default: on the published build of 2026-10-01 it would move 49 fund-quarters, and
    # about 20 of them from reconciled to short, because other filers count their cash funds
    # inside the investments line. Fair value by default; the cost rule splits too for a filer
    # whose wrapper also sets cost_total_excludes = ["cash_rows"] (Silver Point 2023-06-30: cost
    # with cash 948.4M against filed 863.2M, non-cash 863.8M). The cash rows' own status
    # (cash_status) is read from the fair-value rule only: the filed cash figure is a fair value.
    # Detected cost basis (owner ruling 2026-11-04, cost-conservation-cash-rows-against-ex-cash-
    # cost-total): without cost_total_excludes the cost rule compared cost with the cash rows
    # against a filed cost total that leaves them out (Silver Capital 2025-09-30: 485.0M against
    # 357.4M; the money fund's cost 127.6M; non-cash cost equals the filed cost). The cash rows'
    # cost is now taken out also when (1) with them the cost fails, (2) without them it ties,
    # and (3) there is evidence the filer reports the cash rows outside its investments: the
    # wrapper declares investments_total_excludes, or the cash rows' fair value equals the filed
    # cash-equivalents figure (within the 0.5 pct fair-value band of the anchor, not the cost
    # rule's 5 pct). Never for a filer declaring investments_total_includes_cash.
    con.execute("CREATE OR REPLACE TEMP TABLE _cash_inside_total(cik VARCHAR)")
    inside = cash_inside_total_ciks()
    if inside:
        con.executemany("INSERT INTO _cash_inside_total VALUES (?)", [(c,) for c in inside])
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _cash_fv_sum AS
        SELECT lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
               substr(CAST(report_date AS VARCHAR), 1, 10) AS report_date,
               coalesce(sum(TRY_CAST(fair_value AS DOUBLE)), 0) AS cash_fv
        FROM {_unified()}
        WHERE upper(COALESCE(CAST(asset_category AS VARCHAR), '')) = 'CASH' AND ({PUBLISHED_ROWS_WHERE_SQL})
        GROUP BY 1, 2
        """
    )
    detected = f"""(anchor_basis = 'investments_ex_cash' AND cash_sum <> 0 AND anchor_value IS NOT NULL
                    AND cik NOT IN (SELECT cik FROM _cash_inside_total)
                    AND abs(value_sum - anchor_value) > {tol} * abs(anchor_value)
                    AND abs(value_sum - cash_sum - anchor_value) <= {tol} * abs(anchor_value)
                    AND (declared OR (filed_cash IS NOT NULL
                                      AND abs(cash_fv - filed_cash)
                                          <= {FV_CONSERVATION_BAND_PCT / 100.0} * abs(anchor_value))))"""
    declared_split = "(declared AND anchor_basis = 'investments_ex_cash')"
    if rule.value_column == "fair_value":
        split, split_status = declared_split, "true"
    elif rule.value_column == "cost":
        split = f"((cik IN (SELECT cik FROM _cost_cash_split) AND {declared_split}) OR {detected})"
        split_status = "false"
    else:
        split, split_status = "false", "false"
    con.execute(
        f"""
        CREATE OR REPLACE TABLE result_{rule.name} AS
        WITH joined AS (
            SELECT s.cik, s.report_date, s.n_rows, s.value_sum,
                   {val_expr} AS anchor_value, {label_expr} AS anchor_used, {basis_expr} AS anchor_basis,
                   coalesce(cs.cash_sum, 0) AS cash_sum, fc.filed_cash, coalesce(cf.cash_fv, 0) AS cash_fv,
                   s.cik IN (SELECT cik FROM _cash_outside_total) AS declared
            FROM _sum_{rule.name} s
            {' '.join(anchor_ctes)}
            LEFT JOIN _cash_sum cs USING (cik, report_date)
            LEFT JOIN _filed_cash fc USING (cik, report_date)
            LEFT JOIN _cash_fv_sum cf USING (cik, report_date)
        ), compared AS (
            SELECT *,
                   CASE WHEN {split} THEN value_sum - cash_sum
                        ELSE value_sum END AS compared_sum,
                   CASE WHEN NOT ({split_status}) OR NOT declared OR anchor_basis <> 'investments_ex_cash' OR cash_sum = 0 THEN ''
                        WHEN filed_cash IS NULL THEN 'no_filed_figure'
                        WHEN cash_sum > filed_cash + {tol} * abs(anchor_value) THEN 'exceeds_filed'
                        ELSE 'within_filed' END AS cash_status
            FROM joined
        )
        SELECT
            '{rule.name}' AS rule_name,
            '{rule.value_column}' AS value_column,
            '{rule.tier}' AS tier,
            '{rule.enforcement}' AS enforcement,
            cik, report_date, n_rows,
            value_sum,
            anchor_value,
            anchor_used,
            anchor_basis,
            CASE WHEN anchor_value IS NULL OR anchor_value = 0 THEN NULL
                 WHEN cash_status = 'exceeds_filed' AND abs(compared_sum - anchor_value) <= {tol}*abs(anchor_value)
                 THEN round(100.0*(cash_sum - filed_cash)/anchor_value, 3)
                 ELSE round(100.0*(compared_sum - anchor_value)/anchor_value, 3) END AS residual_pct,
            CASE
                WHEN anchor_value IS NULL THEN 'no_anchor'
                WHEN abs(compared_sum - anchor_value) <= {tol}*abs(anchor_value)
                     THEN CASE WHEN cash_status = 'exceeds_filed' THEN 'overshoot' ELSE 'reconciles' END
                WHEN compared_sum > anchor_value THEN 'overshoot'
                ELSE 'undershoot'
            END AS status,
            compared_sum, cash_sum, filed_cash, cash_status
        FROM compared
        """
    )


def cash_outside_total_ciks() -> list[str]:
    """Filers whose wrapper says the filed investments total leaves the schedule's cash rows out."""
    from pipeline.source_encodings import load_encodings
    return sorted(cik for cik, encoding in load_encodings().items()
                  if encoding.get("investments_total_excludes") == ["cash_rows"])


def cash_inside_total_ciks() -> list[str]:
    """Filers whose wrapper says the filed investments total holds the schedule's cash rows."""
    from pipeline.source_encodings import load_encodings
    return sorted(cik for cik, encoding in load_encodings().items()
                  if encoding.get("investments_total_includes_cash"))


def cost_split_ciks() -> list[str]:
    """Filers whose wrapper says the filed cost total also leaves the cash rows out."""
    from pipeline.source_encodings import cost_cash_split_ciks
    return cost_cash_split_ciks()


def filed_cash_addend_rows() -> list[tuple[str, str, float]]:
    """(cik, report_date, amount) of the filed concepts a wrapper says the cash rows also hold."""
    from pipeline.source_encodings import cash_rows_filed_addends
    return cash_rows_filed_addends()


def _filed_cash_sql() -> str:
    """(cik, report_date, filed_cash): fund_financials.cash_equivalents_at_fair_value, no rows
    when the file predates the column."""
    cols = {r[0].lower() for r in duckdb.connect().execute(
        f"DESCRIBE SELECT * FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1) LIMIT 0"
    ).fetchall()}
    if "cash_equivalents_at_fair_value" not in cols:
        return ("SELECT CAST(NULL AS VARCHAR) AS cik, CAST(NULL AS VARCHAR) AS report_date, "
                "CAST(NULL AS DOUBLE) AS filed_cash WHERE false")
    return f"""
        SELECT {CIK10_SQL} AS cik, {REPORT_DATE_KEY_SQL} AS report_date,
               max(TRY_CAST(cash_equivalents_at_fair_value AS DOUBLE)) AS filed_cash
        FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
        WHERE source='companyfacts' AND cash_equivalents_at_fair_value IS NOT NULL
        GROUP BY 1, 2
    """

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
