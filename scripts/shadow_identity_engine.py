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
    BDC_FUND_INCOME_FILE,
    BDC_IXBRL_FIELD_STATUS_FILE,
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


def _csv(path: Path) -> str:
    # all_varchar: dates stay 'YYYY-MM-DD' strings and CIKs keep their leading zeros
    return f"read_csv('{path.as_posix()}', header=true, all_varchar=true, sample_size=-1)"


def year_end_income_sql(financials_sql: str, income_sql: str) -> str:
    """One row per fund year-end quarter: the published income and the fourth quarter the filings imply.

    The income table stores a 10-K's twelve-month figure divided by four. The quarter itself is the
    annual figure less the three quarters filed in the 10-Qs of that year. A year-end without
    exactly three such quarters in the preceding twelve months has no expected value (no row).
    """
    return f"""(
        WITH inc AS (
            SELECT lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') AS cik,
                   TRY_CAST(CAST(report_date AS VARCHAR)[:10] AS DATE) AS day,
                   TRY_CAST(duration_months AS INTEGER) AS months,
                   max(TRY_CAST(total_investment_income AS DOUBLE)) AS income
            FROM {income_sql} GROUP BY 1, 2, 3),
        year_end AS (
            SELECT a.cik, a.day, 4.0*a.income AS annual, sum(q.income) AS three_quarters, count(q.income) AS quarters
            FROM inc a LEFT JOIN inc q ON q.cik = a.cik AND q.months BETWEEN 2 AND 4
                 AND q.day < a.day AND q.day > a.day - INTERVAL 11 MONTH
            WHERE a.months BETWEEN 11 AND 13 GROUP BY 1, 2, 3)
        SELECT f.cik, f.report_date, f.entity_name, f.total_investment_income,
               y.annual - y.three_quarters AS fourth_quarter_expected
        FROM (SELECT lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') AS cik,
                     CAST(report_date AS VARCHAR)[:10] AS report_date, entity_name, total_investment_income
              FROM {financials_sql} WHERE source = 'companyfacts') f
        JOIN year_end y ON y.cik = f.cik AND CAST(y.day AS VARCHAR) = f.report_date AND y.quarters = 3
    )"""


def printed_reference_sql(unified_sql: str, status_sql: str, ciks: list[str]) -> str:
    """Published loan rows whose reference rate can be compared with the filer's printed column.

    Only funds whose wrapper names that column (``reference_rate_columns``), only rows the page
    reader confirmed (status ``value``, or ``not_applicable`` where the column prints no
    reference rate) and only rows that publish a reference rate. The row is keyed to the page
    by filing, report date and the filed identifier member.
    ``reference_rate_agrees`` is 1 when the two are the same benchmark, 0 when they differ or
    the page prints none, and empty where no reference rate is published. ``printed_margin``
    is the total margin read from the page (empty where it was not read, or the artifact
    predates the column).
    """
    named = ", ".join("'%s'" % c for c in ciks) or "''"
    return f"""(
        SELECT lpad(regexp_replace(CAST(h.cik AS VARCHAR),'[^0-9]','','g'),10,'0') AS cik,
               CAST(h.report_date AS VARCHAR)[:10] AS report_date, h.bdc_investment_identifier,
               CASE WHEN nullif(trim(CAST(h.reference_rate_type AS VARCHAR)), '') IS NULL THEN NULL
                    WHEN s.reference_rate_status = 'value'
                         AND upper(trim(CAST(h.reference_rate_type AS VARCHAR))) = upper(trim(s.reference_rate_type))
                    THEN 1.0 ELSE 0.0 END AS reference_rate_agrees,
               h.basis_spread, s.printed_margin
        FROM {unified_sql} h
        JOIN (SELECT * FROM (SELECT * FROM {status_sql}
                             UNION ALL BY NAME SELECT CAST(NULL AS VARCHAR) AS printed_margin WHERE false)
              WHERE period_role = 'current' AND reference_rate_status IN ('value', 'not_applicable', 'unspecified')) s
          ON lpad(regexp_replace(CAST(s.cik AS VARCHAR),'[^0-9]','','g'),10,'0')
               = lpad(regexp_replace(CAST(h.cik AS VARCHAR),'[^0-9]','','g'),10,'0')
         AND s.accession_number = h.accession_number AND s.report_date = CAST(h.report_date AS VARCHAR)[:10]
         AND s.raw_id_lower = lower(trim(regexp_replace(regexp_replace(CAST(h.bdc_dimensions_raw AS VARCHAR),
               '^[^=]*=', ''), '[ ]+', ' ', 'g')))
        WHERE lpad(regexp_replace(CAST(h.cik AS VARCHAR),'[^0-9]','','g'),10,'0') IN ({named})
          AND coalesce(CAST(h.accounting_record_class AS VARCHAR), '') <> 'underlying_schedule'
    )"""


# Fields a published row of a given kind is expected to carry: (label, rows that count, rows that carry it).
COVERAGE_FIELDS = (
    ("principal on drawn loans", "asset_category = 'LOAN' AND fair_value > 0", "principal_amount IS NOT NULL"),
    ("rate or spread on drawn loans", "asset_category = 'LOAN' AND fair_value > 0",
     "(interest_rate IS NOT NULL OR basis_spread IS NOT NULL)"),
    ("maturity on loans", "asset_category = 'LOAN'", "maturity_date IS NOT NULL"),
    ("reference rate on floating loans", "asset_category = 'LOAN' AND basis_spread IS NOT NULL",
     "nullif(trim(CAST(reference_rate_type AS VARCHAR)), '') IS NOT NULL"),
    ("cost", "TRUE", "cost IS NOT NULL"),
    ("unit count on equity", "asset_category LIKE 'EQUITY%'", "shares_held IS NOT NULL"),
    ("percent of net assets", "TRUE", "pct_of_net_assets IS NOT NULL"),
    ("filer industry", "TRUE", "nullif(trim(CAST(extracted_industry AS VARCHAR)), '') IS NOT NULL"),
)
COVERAGE_MIN_ROWS = 20


def field_coverage_sql(unified_sql: str, cik_filter: str = "TRUE") -> str:
    """One row per fund, quarter and field: the share of published rows that carry the field, and
    the same share in the fund's previous quarter.

    HPS Corporate Lending tagged the par of its loans with the share-count concept in one filing:
    principal on drawn loans went from 100 pct to 16 pct and back, every row still had a value, a
    cost and a rate, totals tied, and no rule looked (2026-10-13). The check needs no knowledge of
    which field will break. Published rows only (a joint venture's own schedule is left out); a
    fund-quarter with fewer than COVERAGE_MIN_ROWS rows of the kind says nothing, and neither does
    a fund's first quarter. ``prior_coverage`` is the previous quarter the fund has such rows in.
    """
    parts = []
    for label, counted, carried in COVERAGE_FIELDS:
        parts.append(f"""
            SELECT cik, report_date, '{label}' AS field_name,
                   count(*) FILTER (WHERE {counted}) AS n_rows,
                   count(*) FILTER (WHERE ({counted}) AND {carried}) AS n_carried
            FROM h GROUP BY 1, 2""")
    return f"""(
        WITH h AS (
            SELECT lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') AS cik,
                   CAST(report_date AS VARCHAR)[:10] AS report_date,
                   CAST(asset_category AS VARCHAR) AS asset_category,
                   TRY_CAST(fair_value AS DOUBLE) AS fair_value, TRY_CAST(principal_amount AS DOUBLE) AS principal_amount,
                   TRY_CAST(interest_rate AS DOUBLE) AS interest_rate, TRY_CAST(basis_spread AS DOUBLE) AS basis_spread,
                   TRY_CAST(cost AS DOUBLE) AS cost, TRY_CAST(shares_held AS DOUBLE) AS shares_held,
                   TRY_CAST(pct_of_net_assets AS DOUBLE) AS pct_of_net_assets,
                   TRY_CAST(maturity_date AS DATE) AS maturity_date, reference_rate_type, extracted_industry
            FROM {unified_sql}
            WHERE source = 'bdc' AND ({cik_filter})
              AND coalesce(CAST(accounting_record_class AS VARCHAR), '') <> 'underlying_schedule'
        ), counted AS ({" UNION ALL ".join(parts)}
        ), shares AS (
            SELECT cik, report_date, field_name, n_rows, 1.0 * n_carried / n_rows AS coverage
            FROM counted WHERE n_rows >= {COVERAGE_MIN_ROWS}
        )
        SELECT cik, report_date, field_name, n_rows, coverage,
               lag(coverage) OVER (PARTITION BY cik, field_name ORDER BY report_date) AS prior_coverage
        FROM shares
    )"""


def _named_reference_column_ciks() -> list[str]:
    from pipeline.source_encodings import load_encodings
    return sorted(cik for cik, encoding in load_encodings().items() if encoding.get("reference_rate_columns"))


# Source config: (table_sql, where, cik_expr, report_date_expr, row_id_expr)
SOURCES = {
    # Derived sources. A missing input file makes the source unreadable; its rules are then skipped.
    "year_end_income": (year_end_income_sql(_ff(), _csv(BDC_FUND_INCOME_FILE)), "TRUE",
                        "cik", "report_date", "entity_name"),
    "printed_reference": (printed_reference_sql(_unified(), _csv(BDC_IXBRL_FIELD_STATUS_FILE),
                                                _named_reference_column_ciks()), "TRUE",
                          "cik", "report_date", "bdc_investment_identifier"),
    "field_coverage": (field_coverage_sql(_unified(), "CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped)"), "TRUE",
                       "cik", "report_date", "field_name"),
    # Published rows only: a JV's own schedule states percent of the JV's net assets, so its rows
    # cannot satisfy an identity against the fund's (2026-10-06, decision D-014).
    "unified": (_unified(), "bdc_dimensions_raw IS NOT NULL "
                "AND CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped) "
                "AND coalesce(CAST(accounting_record_class AS VARCHAR), '') <> 'underlying_schedule'",
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
    optional_cols: tuple[str, ...] = ()  # read when the source has them, NULL otherwise; never gated


RULES: list[IdentityRule] = [
    # position-level (unified)
    IdentityRule(
        name="pct_of_net_assets_identity", table="unified",
        needed_cols=("fair_value", "pct_of_net_assets"),
        scalar=("fund_financials", "net_assets"),
        row_filter="pct_of_net_assets > 0 AND _scalar > 0 AND fair_value <> 0",
        # 10 pct of fair value, or within 0.06 percentage points: filers state the percent to one
        # or two decimals, so a small position cannot meet a relative band (decision D-014).
        holds_sql="abs(fair_value - pct_of_net_assets/100.0*_scalar) <= 0.10*abs(fair_value) "
                  "OR abs(pct_of_net_assets - 100.0*fair_value/_scalar) <= 0.06",
        residual_sql="fair_value - pct_of_net_assets/100.0*_scalar",
        tol_note="FV = pct/100 * net_assets, 10% rel-to-FV or 0.06 pct points (pct rounding)",
    ),
    # RETIRED 2026-06-19 (B-trial evidence): "pik_le_interest_rate" was an unsound
    # invariant. Its row_filter (pik_rate>0 AND interest_rate>0) selects EXACTLY the
    # split "X% cash, Y% PIK" coupons, where the pipeline stores the CASH leg in
    # interest_rate and the PIK leg in pik_rate -- so PIK legitimately exceeds the
    # cash leg (e.g. "6.7% Cash, 7.6% PIK"; "3.65% cash / 7.25% PIK"). The sound
    # invariant compares PIK to the ALL-IN coupon (interest_rate + pik_rate), which
    # is vacuously true, so no useful per-row ordering check remains. The B pilot
    # adjudicated 15/15 of this rule's flags as false alarms (Wilson95 [80,100]),
    # all localized to legitimate split-coupon disclosures. Do NOT re-add without a
    # field that distinguishes cash-leg interest_rate from all-in interest_rate.
    # PIK magnitude plausibility is already covered by fmt_pik_rate (weak range).
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
        # Net investment income is after fee waivers; use the filed net expenses where there are any
        # (2026-10-06, decision D-025). Net above gross cannot be: in a 10-K quarter the income
        # table's figures are the annual amount divided by four while net_expenses is the true
        # fourth quarter, so the two are on different bases and the gross figure is compared.
        optional_cols=("net_expenses",),
        row_filter="total_investment_income <> 0",
        holds_sql="abs(net_investment_income - (total_investment_income - CASE WHEN net_expenses <= total_expenses THEN net_expenses ELSE total_expenses END)) "
                  "<= 0.05*abs(total_investment_income)",
        residual_sql="net_investment_income - (total_investment_income - CASE WHEN net_expenses <= total_expenses THEN net_expenses ELSE total_expenses END)",
        tol_note="NII ~ total_investment_income - expenses (net where filed, else total), 5%",
    ),
    IdentityRule(
        name="balance_sheet_identity", table="fund_financials",
        needed_cols=("total_assets", "total_liabilities", "net_assets"),
        row_filter="total_assets > 0",
        holds_sql="abs(total_assets - total_liabilities - net_assets) <= 0.01*abs(total_assets)",
        residual_sql="total_assets - total_liabilities - net_assets",
        tol_note="TA - TL ~ net_assets, 1% (companyfacts schema)",
    ),
    # A year-end quarter's income must be the annual figure less the three filed quarters, not the
    # annual figure divided by four (HPS 2023-12-31: published 223.3M, the filings imply 264.7M).
    IdentityRule(
        name="fourth_quarter_income", table="year_end_income",
        needed_cols=("total_investment_income", "fourth_quarter_expected"),
        row_filter="fourth_quarter_expected <> 0",
        holds_sql="abs(total_investment_income - fourth_quarter_expected) <= 0.02*abs(fourth_quarter_expected)",
        residual_sql="total_investment_income - fourth_quarter_expected",
        tol_note="year-end quarter income ~ annual - three filed quarters, 2%",
    ),
    # The published reference rate against the code printed in the filer's own column. Only for
    # funds whose wrapper names that column (Blue Owl: 780 of 6,414 rows disagree, most of them a
    # rate inferred from the report date).
    IdentityRule(
        name="reference_rate_printed", table="printed_reference",
        needed_cols=("reference_rate_agrees",),
        holds_sql="reference_rate_agrees = 1",
        residual_sql="1 - reference_rate_agrees",
        tol_note="published reference rate = code printed in the filer's reference-rate column",
    ),
    # The published spread against the total margin printed on the row (same funds). Catches a
    # spread tag that holds only the cash part of a cash-plus-PIK margin, or a mis-scaled spread.
    IdentityRule(
        name="spread_printed", table="printed_reference",
        needed_cols=("basis_spread", "printed_margin"),
        holds_sql="abs(basis_spread - printed_margin) <= 0.011",
        residual_sql="basis_spread - printed_margin",
        tol_note="published spread = total margin printed on the row, to the second decimal",
    ),
    # A field's coverage against the fund's own previous quarter (owner, 2026-10-13: "add the rule").
    # One violating row per fund, quarter and field; the row id is the field's label.
    IdentityRule(
        name="field_coverage_drop", table="field_coverage",
        needed_cols=("coverage", "prior_coverage"),
        holds_sql="prior_coverage - coverage < 0.20",
        residual_sql="coverage - prior_coverage",
        tol_note="share of rows carrying a field falls less than 20 points against the fund's previous quarter",
    ),
]


def wrapped_ciks() -> list[str]:
    return sorted(p.stem for p in WRAPPER_DIR.glob("*.json") if _CIK_RE.match(p.stem))


def _columns(con: duckdb.DuckDBPyConnection, source_sql: str) -> set[str]:
    try:
        rows = con.execute(f"DESCRIBE SELECT * FROM {source_sql} LIMIT 0").fetchall()
    except duckdb.IOException as exc:  # an input file of a derived source is absent
        logger.info("  source unreadable: %s", str(exc).splitlines()[0][:120])
        return set()
    return {r[0] for r in rows}


def run_rule(con: duckdb.DuckDBPyConnection, rule: IdentityRule,
             cols_cache: dict[str, set[str]]) -> bool:
    src_sql, where, cik_e, rd_e, id_e = SOURCES[rule.table]
    avail = cols_cache.setdefault(rule.table, _columns(con, src_sql))
    missing = [c for c in rule.needed_cols if c not in avail]
    if missing:
        logger.info("  SKIP %-26s missing columns: %s", rule.name, missing)
        return False

    col_casts = ", ".join(
        [f"TRY_CAST({c} AS DOUBLE) AS {c}" for c in rule.needed_cols]
        + [f"TRY_CAST({c} AS DOUBLE) AS {c}" if c in avail else f"CAST(NULL AS DOUBLE) AS {c}"
           for c in rule.optional_cols])
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
               {", ".join("b."+c for c in rule.needed_cols + rule.optional_cols)}, {scalar_sel}
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
