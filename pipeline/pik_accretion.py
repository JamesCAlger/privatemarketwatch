"""Is PIK being capitalized, and a filings-only version of Lincoln International's bad-PIK test.

Three artifacts, all on the published basis, BDC/N-PORT direct-lending rows only:

pik_accretion.csv (one row per position and quarter with PIK terms, pik_rate > 0)
    payment_evidence: confirmed_tagged (position-level PIK income fact), accreting (principal
    grew by about pik_rate x elapsed time since the fund's previous filed quarter, or over two
    quarters after a flat one: semi-annual capitalization), flat, not_paying_tagged, or
    undetermined (undetermined_reason says why). paying_now = confirmed_tagged or accreting.
    pik_timing: what the position looked like before PIK appeared.
      started_after_cash             an earlier funded quarter in this fund had no PIK terms
      at_origination                 PIK at the first observation, within 183 days of the filed
                                     acquisition date
      pik_seen_earlier_elsewhere     another filer held the same loan (borrower name + maturity
                                     month) with PIK before this fund first reported it
      started_after_cash_cross_filer another filer held it cash-only before this fund did
      left_censored                  first seen in the fund's first filed quarter
      origin_unknown                 none of the above
    lincoln_class (paying_now only): bad (started_after_cash*), good (at_origination), unknown.

pik_lincoln_summary.csv (per fund and quarter, plus cik = 'ALL')
    Lincoln's universe is senior and unitranche term loans, counted per loan. Ours is
    first-lien rows with positive fair value (revolvers cannot be separated reliably: the
    instrument type is mostly blank), counted per position and FV-weighted. Shares are in
    percent. *_max variants count every unknown-origin payer as bad: the upper bound.

pik_reconciliation.csv (per fund and quarter)
    Implied PIK from terms (prior principal x pik_rate x elapsed time), observed accretion on
    accreting positions, and the fund's reported quarterly PIK income (undimensioned facts
    only; a three-month fact, else the difference of year-to-date facts). The reported figure
    also covers PIK dividends, equity and positions outside the published debt rows, so the
    ratio is a measurement, not a gate.

Lincoln's definition: "an instance where a security was paying only cash interest at close,
even if a PIK toggle was present, but has implemented any level of PIK interest as of each
respective quarter-end" (Private Market Perspectives Q1 2026). Filings cannot show the state at
close for a loan first reported after origination, nor why PIK started (amendment or toggle);
the unknown bucket carries that. This is a public-filing proxy, not confirmed bad PIK.
ASCII-only logging.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.config import (
    BDC_POSITION_PIK_EVIDENCE_FILE,
    PIK_ACCRETION_FILE,
    PIK_LINCOLN_SUMMARY_FILE,
    PIK_RECONCILIATION_FILE,
    POSITION_PIK_STATUS_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.published_basis import CIK10_SQL, PUBLISHED_ROWS_WHERE_SQL

logger = logging.getLogger(__name__)

# Accretion tolerance, as a multiple of the growth the PIK rate implies.
ACCRETE_LOW = 0.5
ACCRETE_HIGH = 1.6
FLAT_MAX = 0.1
PRINCIPAL_DOWN = -0.0005
ORIGINATION_DAYS = 183

HOLDING_COLUMNS = [
    "source", "cik", "entity_name", "report_date", "position_id", "issuer_name", "canonical_name",
    "lien_position", "index_classification", "accounting_record_class", "fair_value", "cost",
    "principal_amount", "principal_amount_currency", "pik_rate", "maturity_date",
    "bdc_acquisition_date", "nonaccrual_status", "nport_is_paid_in_kind",
]

ACCRETION_COLUMNS = [
    "source", "cik", "entity_name", "position_id", "issuer_name", "report_date", "prior_report_date",
    "lien_position", "fair_value", "principal_amount", "prior_principal_amount", "pik_rate",
    "expected_growth", "actual_growth", "payment_evidence", "accretion_window", "undetermined_reason",
    "paying_now", "flat_quarters", "first_observed", "first_pik_observed", "pik_timing",
    "lincoln_class", "stress_nonaccrual", "stress_mark_below_90", "stress_mark_drop_5pt",
]

# Fund-level PIK income concepts, best first. Anything else naming PIK income ranks last.
REPORTED_CONCEPT_RANK = {
    "interestincomeoperatingpaidinkind": 1,
    "paidinkindinterestincome": 2,
    "interestanddividendincomeoperatingpaidinkind": 3,
    "paidinkindinterest": 4,
    "paidinkindinterestnoncash": 5,
}


def _date_sql(col: str) -> str:
    return f"TRY_CAST(substr(CAST({col} AS VARCHAR), 1, 10) AS DATE)"


def _num_sql(col: str) -> str:
    return f"TRY_CAST(CAST({col} AS VARCHAR) AS DOUBLE)"


def _txt_sql(col: str) -> str:
    return f"coalesce(trim(CAST({col} AS VARCHAR)), '')"


def _normalized_sql(table: str) -> str:
    """Published direct-lending rows with typed columns."""
    return f"""
        SELECT lower({_txt_sql('source')}) AS source,
               {CIK10_SQL} AS cik,
               {_txt_sql('entity_name')} AS entity_name,
               {_date_sql('report_date')} AS report_date,
               {_txt_sql('position_id')} AS position_id,
               {_txt_sql('issuer_name')} AS issuer_name,
               lower(coalesce(nullif({_txt_sql('canonical_name')}, ''), {_txt_sql('issuer_name')})) AS name_key,
               {_txt_sql('lien_position')} AS lien_position,
               {_num_sql('fair_value')} AS fair_value,
               {_num_sql('principal_amount')} AS principal_amount,
               upper({_txt_sql('principal_amount_currency')}) AS currency,
               coalesce({_num_sql('pik_rate')}, 0) AS pik_rate,
               substr(CAST({_date_sql('maturity_date')} AS VARCHAR), 1, 7) AS maturity_month,
               {_date_sql('bdc_acquisition_date')} AS acquisition_date,
               lower({_txt_sql('nonaccrual_status')}) = 'nonaccrual' AS nonaccrual,
               upper({_txt_sql('nport_is_paid_in_kind')}) IN ('Y', 'TRUE') AS nport_pik
        FROM {table}
        WHERE ({PUBLISHED_ROWS_WHERE_SQL})
          AND {_txt_sql('index_classification')} = 'DIRECT_LENDING'
    """


def _connect(holdings: pd.DataFrame, status_df: pd.DataFrame | None,
             reference_df: pd.DataFrame | None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("h_raw", _with_columns(holdings, HOLDING_COLUMNS))
    con.execute(f"CREATE TEMP TABLE h AS {_normalized_sql('h_raw')}")
    if reference_df is not None and not reference_df.empty:
        con.register("ref_raw", _with_columns(reference_df, HOLDING_COLUMNS))
        con.execute(f"CREATE TEMP TABLE ref AS {_normalized_sql('ref_raw')}")
        # The run's own funds come from the run's holdings, not the (older) reference.
        con.execute("DELETE FROM ref WHERE cik IN (SELECT DISTINCT cik FROM h)")
        con.execute("INSERT INTO ref SELECT * FROM h")
    else:
        con.execute("CREATE TEMP TABLE ref AS SELECT * FROM h")
    status_cols = ["cik", "position_id", "report_date", "pik_current_status"]
    status = _with_columns(status_df if status_df is not None else pd.DataFrame(), status_cols)
    con.register("status_raw", status)
    con.execute(f"""
        CREATE TEMP TABLE tagged AS
        SELECT {CIK10_SQL} AS cik, {_txt_sql('position_id')} AS position_id,
               {_date_sql('report_date')} AS report_date,
               bool_or(pik_current_status = 'paying') AS any_paying,
               bool_and(pik_current_status = 'not_paying') AS all_not_paying
        FROM status_raw
        WHERE pik_current_status IN ('paying', 'not_paying')
        GROUP BY 1, 2, 3
    """)
    return con


def _with_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = None
    return out[cols].astype(object).where(out[cols].notna(), None)


def build_pik_accretion(holdings: pd.DataFrame, status_df: pd.DataFrame | None = None,
                        reference_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per position and quarter with PIK terms; see the module docstring."""
    con = _connect(holdings, status_df, reference_df)
    try:
        return _accretion(con)
    finally:
        con.close()


def _accretion(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    con.execute("""
        CREATE TEMP TABLE pq AS
        SELECT cik, position_id, report_date,
               any_value(source) AS source, any_value(entity_name) AS entity_name,
               any_value(issuer_name) AS issuer_name, any_value(name_key) AS name_key,
               any_value(lien_position) AS lien_position, max(maturity_month) AS maturity_month,
               sum(fair_value) AS fair_value, sum(principal_amount) AS principal_amount,
               max(pik_rate) AS pik_rate, min(acquisition_date) AS acquisition_date,
               bool_or(currency NOT IN ('', 'USD')) AS non_usd, bool_or(nonaccrual) AS nonaccrual
        FROM h WHERE position_id <> '' AND report_date IS NOT NULL
        GROUP BY 1, 2, 3
    """)
    con.execute("""
        CREATE TEMP TABLE fd AS
        SELECT cik, report_date,
               lag(report_date) OVER (PARTITION BY cik ORDER BY report_date) AS prev_date,
               lag(report_date, 2) OVER (PARTITION BY cik ORDER BY report_date) AS prev2_date,
               min(report_date) OVER (PARTITION BY cik) AS fund_first_date
        FROM (SELECT DISTINCT cik, report_date FROM pq)
    """)
    con.execute(f"""
        CREATE TEMP TABLE g AS
        SELECT p.*, fd.prev_date, fd.prev2_date, fd.fund_first_date,
               a.principal_amount AS prior_principal, a.fair_value AS prior_fv, a.non_usd AS prior_non_usd,
               b.principal_amount AS prior2_principal,
               p.principal_amount / nullif(a.principal_amount, 0) - 1 AS actual_growth,
               p.pik_rate / 100 * date_diff('day', fd.prev_date, p.report_date) / 365.25 AS expected_growth,
               p.principal_amount / nullif(b.principal_amount, 0) - 1 AS growth2,
               p.pik_rate / 100 * date_diff('day', fd.prev2_date, p.report_date) / 365.25 AS expected2,
               a.position_id IS NOT NULL AS has_prior
        FROM pq p JOIN fd USING (cik, report_date)
        LEFT JOIN pq a ON a.cik = p.cik AND a.position_id = p.position_id AND a.report_date = fd.prev_date
        LEFT JOIN pq b ON b.cik = p.cik AND b.position_id = p.position_id AND b.report_date = fd.prev2_date
    """)
    # growth of the prior quarter, for the two-quarter (semi-annual) window
    con.execute("""
        CREATE TEMP TABLE g2 AS
        SELECT g.*, pg.actual_growth AS prior_growth, pg.expected_growth AS prior_expected
        FROM g LEFT JOIN g pg ON pg.cik = g.cik AND pg.position_id = g.position_id
                             AND pg.report_date = g.prev_date
    """)
    con.execute(f"""
        CREATE TEMP TABLE cls AS
        SELECT g2.*, t.any_paying, t.all_not_paying,
          CASE
            WHEN t.any_paying THEN 'confirmed_tagged'
            WHEN t.all_not_paying THEN 'not_paying_tagged'
            WHEN NOT has_prior THEN 'undetermined'
            WHEN non_usd OR prior_non_usd THEN 'undetermined'
            WHEN principal_amount IS NULL OR coalesce(prior_principal, 0) <= 0 THEN 'undetermined'
            WHEN actual_growth BETWEEN {ACCRETE_LOW} * expected_growth AND {ACCRETE_HIGH} * expected_growth
              THEN 'accreting'
            WHEN actual_growth > {ACCRETE_HIGH} * expected_growth
                 AND prior_growth BETWEEN {PRINCIPAL_DOWN} AND {FLAT_MAX} * prior_expected
                 AND growth2 BETWEEN {ACCRETE_LOW} * expected2 AND {ACCRETE_HIGH} * expected2
              THEN 'accreting'
            WHEN actual_growth > {ACCRETE_HIGH} * expected_growth THEN 'undetermined'
            WHEN actual_growth < {PRINCIPAL_DOWN} THEN 'undetermined'
            WHEN actual_growth < {FLAT_MAX} * expected_growth THEN 'flat'
            ELSE 'undetermined'
          END AS payment_evidence,
          CASE
            WHEN t.any_paying OR t.all_not_paying THEN ''
            WHEN NOT has_prior THEN 'no_prior_quarter'
            WHEN non_usd OR prior_non_usd THEN 'non_usd_principal'
            WHEN principal_amount IS NULL OR coalesce(prior_principal, 0) <= 0 THEN 'no_principal'
            WHEN actual_growth BETWEEN {ACCRETE_LOW} * expected_growth AND {ACCRETE_HIGH} * expected_growth THEN ''
            WHEN actual_growth > {ACCRETE_HIGH} * expected_growth
                 AND prior_growth BETWEEN {PRINCIPAL_DOWN} AND {FLAT_MAX} * prior_expected
                 AND growth2 BETWEEN {ACCRETE_LOW} * expected2 AND {ACCRETE_HIGH} * expected2 THEN ''
            WHEN actual_growth > {ACCRETE_HIGH} * expected_growth THEN 'principal_jump'
            WHEN actual_growth < {PRINCIPAL_DOWN} THEN 'principal_down'
            WHEN actual_growth < {FLAT_MAX} * expected_growth THEN ''
            ELSE 'partial_accretion'
          END AS undetermined_reason
        FROM g2 LEFT JOIN tagged t USING (cik, position_id, report_date)
        WHERE g2.pik_rate > 0
    """)
    con.execute("""
        CREATE TEMP TABLE hist AS
        SELECT cik, position_id,
               min(report_date) FILTER (WHERE coalesce(fair_value, 0) > 0 OR coalesce(principal_amount, 0) > 0) AS first_obs,
               min(report_date) FILTER (WHERE pik_rate > 0) AS first_pik,
               min(acquisition_date) AS acquisition_date,
               any_value(name_key) AS name_key, max(maturity_month) AS maturity_month
        FROM pq GROUP BY 1, 2
    """)
    con.execute("""
        CREATE TEMP TABLE xf AS
        SELECT hs.cik, hs.position_id,
               bool_or(r.pik_rate > 0 OR r.nport_pik) AS earlier_pik,
               bool_or(NOT (r.pik_rate > 0 OR r.nport_pik)) AS earlier_cash
        FROM hist hs JOIN ref r
          ON r.name_key = hs.name_key AND r.maturity_month = hs.maturity_month
         AND r.cik <> hs.cik AND r.report_date < hs.first_obs
        WHERE hs.name_key <> '' AND hs.maturity_month IS NOT NULL
        GROUP BY 1, 2
    """)
    df = con.execute(f"""
        WITH t AS (
          SELECT c.*, hs.first_obs, hs.first_pik,
            CASE
              WHEN hs.first_pik > hs.first_obs THEN 'started_after_cash'
              WHEN hs.acquisition_date IS NOT NULL
                   AND hs.first_pik <= hs.acquisition_date + INTERVAL {ORIGINATION_DAYS} DAY THEN 'at_origination'
              WHEN xf.earlier_pik THEN 'pik_seen_earlier_elsewhere'
              WHEN xf.earlier_cash THEN 'started_after_cash_cross_filer'
              WHEN hs.first_obs = c.fund_first_date THEN 'left_censored'
              ELSE 'origin_unknown'
            END AS pik_timing,
            sum(CASE WHEN c.payment_evidence = 'flat' THEN 0 ELSE 1 END)
              OVER (PARTITION BY c.cik, c.position_id ORDER BY c.report_date ROWS UNBOUNDED PRECEDING) AS run_grp
          FROM cls c JOIN hist hs USING (cik, position_id)
          LEFT JOIN xf USING (cik, position_id)
        )
        SELECT source, cik, entity_name, position_id, issuer_name,
               strftime(report_date, '%Y-%m-%d') AS report_date,
               CASE WHEN has_prior THEN strftime(prev_date, '%Y-%m-%d') END AS prior_report_date,
               lien_position, fair_value, principal_amount, prior_principal AS prior_principal_amount,
               pik_rate, expected_growth, actual_growth, payment_evidence,
               CASE WHEN payment_evidence = 'accreting' AND NOT (actual_growth BETWEEN {ACCRETE_LOW} * expected_growth
                    AND {ACCRETE_HIGH} * expected_growth) THEN 'two_quarter'
                    WHEN payment_evidence = 'accreting' THEN 'one_quarter' ELSE '' END AS accretion_window,
               undetermined_reason,
               payment_evidence IN ('confirmed_tagged', 'accreting') AS paying_now,
               CASE WHEN payment_evidence = 'flat'
                    THEN row_number() OVER (PARTITION BY cik, position_id, run_grp ORDER BY report_date)
                         - CASE WHEN run_grp > 0 THEN 1 ELSE 0 END
                    ELSE 0 END AS flat_quarters,
               strftime(first_obs, '%Y-%m-%d') AS first_observed,
               strftime(first_pik, '%Y-%m-%d') AS first_pik_observed,
               pik_timing,
               CASE WHEN payment_evidence NOT IN ('confirmed_tagged', 'accreting') THEN ''
                    WHEN pik_timing IN ('started_after_cash', 'started_after_cash_cross_filer') THEN 'bad'
                    WHEN pik_timing = 'at_origination' THEN 'good'
                    ELSE 'unknown' END AS lincoln_class,
               coalesce(nonaccrual, false) AS stress_nonaccrual,
               coalesce(fair_value / nullif(principal_amount, 0) < 0.9, false) AS stress_mark_below_90,
               coalesce(prior_fv / nullif(prior_principal, 0) - fair_value / nullif(principal_amount, 0) >= 0.05,
                        false) AS stress_mark_drop_5pt
        FROM t
        ORDER BY cik, position_id, report_date
    """).df()
    return df[ACCRETION_COLUMNS]


def build_lincoln_summary(accretion: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    """Lincoln-style shares per fund and quarter and for the whole run (cik = 'ALL')."""
    con = _connect(holdings, None, None)
    try:
        con.register("acc", accretion)
        return con.execute("""
            WITH u AS (
              SELECT cik, position_id, report_date, sum(fair_value) AS fv
              FROM h WHERE lien_position = 'First Lien' AND position_id <> ''
              GROUP BY 1, 2, 3 HAVING sum(fair_value) > 0
            ),
            j AS (
              SELECT u.cik, strftime(u.report_date, '%Y-%m-%d') AS report_date, u.fv,
                     a.payment_evidence, coalesce(a.paying_now, false) AS paying, coalesce(a.lincoln_class, '') AS cls,
                     a.position_id IS NOT NULL AS pik_terms
              FROM u LEFT JOIN acc a ON a.cik = u.cik AND a.position_id = u.position_id
                                    AND a.report_date = strftime(u.report_date, '%Y-%m-%d')
            ),
            both_levels AS (SELECT * FROM j UNION ALL SELECT 'ALL' AS cik, report_date, fv, payment_evidence,
                                                              paying, cls, pik_terms FROM j),
            s AS (
              SELECT cik, report_date,
                count(*) AS n_loans, sum(fv) AS fv_loans,
                count(*) FILTER (WHERE pik_terms) AS n_pik_terms, coalesce(sum(fv) FILTER (WHERE pik_terms), 0) AS fv_pik_terms,
                count(*) FILTER (WHERE paying) AS n_paying_pik, coalesce(sum(fv) FILTER (WHERE paying), 0) AS fv_paying_pik,
                count(*) FILTER (WHERE payment_evidence = 'flat') AS n_flat,
                coalesce(sum(fv) FILTER (WHERE payment_evidence = 'flat'), 0) AS fv_flat,
                count(*) FILTER (WHERE payment_evidence = 'undetermined') AS n_payment_undetermined,
                coalesce(sum(fv) FILTER (WHERE payment_evidence = 'undetermined'), 0) AS fv_payment_undetermined,
                count(*) FILTER (WHERE cls = 'bad') AS n_bad, coalesce(sum(fv) FILTER (WHERE cls = 'bad'), 0) AS fv_bad,
                count(*) FILTER (WHERE cls = 'good') AS n_good, coalesce(sum(fv) FILTER (WHERE cls = 'good'), 0) AS fv_good,
                count(*) FILTER (WHERE cls = 'unknown') AS n_unknown_origin,
                coalesce(sum(fv) FILTER (WHERE cls = 'unknown'), 0) AS fv_unknown_origin
              FROM both_levels GROUP BY 1, 2
            )
            SELECT *,
              100.0 * n_paying_pik / n_loans AS pct_paying_pik_count,
              100.0 * fv_paying_pik / nullif(fv_loans, 0) AS pct_paying_pik_fv,
              100.0 * n_bad / nullif(n_paying_pik, 0) AS bad_share_count,
              100.0 * fv_bad / nullif(fv_paying_pik, 0) AS bad_share_fv,
              100.0 * (n_bad + n_unknown_origin) / nullif(n_paying_pik, 0) AS bad_share_count_max,
              100.0 * n_bad / n_loans AS shadow_default_count,
              100.0 * fv_bad / nullif(fv_loans, 0) AS shadow_default_fv,
              100.0 * (n_bad + n_unknown_origin) / n_loans AS shadow_default_count_max
            FROM s ORDER BY cik = 'ALL', cik, report_date
        """).df()
    finally:
        con.close()


def reported_quarterly_pik(evidence: pd.DataFrame) -> pd.DataFrame:
    """The fund's own quarterly PIK income from undimensioned fund-level facts."""
    cols = ["cik", "report_date", "period", "period_start", "concept", "amount", "dimensions_raw",
            "position_level"]
    con = duckdb.connect()
    try:
        con.register("ev_raw", _with_columns(evidence, cols))
        con.execute(f"""
            CREATE TEMP TABLE ev AS
            SELECT DISTINCT {CIK10_SQL} AS cik, {_date_sql('report_date')} AS report_date,
                   {_date_sql('period_start')} AS period_start, {_date_sql('period')} AS period_end,
                   lower(regexp_replace(CAST(concept AS VARCHAR), '[^A-Za-z]', '', 'g')) AS concept,
                   {_num_sql('amount')} AS amount
            FROM ev_raw
            WHERE lower({_txt_sql('position_level')}) NOT IN ('true', '1')
              AND {_txt_sql('dimensions_raw')} IN ('', 'None', 'nan')
        """)
        rank_case = " ".join(f"WHEN '{c}' THEN {r}" for c, r in REPORTED_CONCEPT_RANK.items())
        con.execute(f"""
            CREATE TEMP TABLE f AS
            SELECT cik, period_start, period_end, concept, max(amount) AS amount,
                   CASE concept {rank_case} ELSE 9 END AS concept_rank,
                   round(date_diff('day', period_start, period_end) / 30.44) AS months
            FROM ev
            WHERE period_start IS NOT NULL AND period_end = report_date AND amount IS NOT NULL
              AND regexp_matches(concept, '(paidinkind|paymentinkind|pik)')
              AND NOT regexp_matches(concept, '(paidincash|excluding|receivable|increasedecrease|fairvaluemeasurement)')
              AND (NOT regexp_matches(concept, 'dividend') OR regexp_matches(concept, 'interestanddividend'))
            GROUP BY cik, period_start, period_end, concept
        """)
        return con.execute("""
            WITH q AS (
              SELECT cik, period_end, concept, concept_rank, amount AS reported, 'three_month_fact' AS method
              FROM f WHERE months = 3
            ),
            ytd AS (
              SELECT cur.cik, cur.period_end, cur.concept, cur.concept_rank,
                     cur.amount - prv.amount AS reported, 'ytd_difference' AS method
              FROM f cur JOIN f prv
                ON prv.cik = cur.cik AND prv.concept = cur.concept AND prv.period_start = cur.period_start
               AND prv.months = cur.months - 3
              WHERE cur.months > 3
            ),
            ranked AS (
              SELECT *, row_number() OVER (PARTITION BY cik, period_end
                                           ORDER BY method = 'ytd_difference', concept_rank, concept) AS rk
              FROM (SELECT * FROM q UNION ALL SELECT * FROM ytd)
            )
            SELECT cik, strftime(period_end, '%Y-%m-%d') AS report_date, reported AS reported_pik,
                   method AS reported_method, concept AS reported_concept
            FROM ranked WHERE rk = 1 ORDER BY cik, report_date
        """).df()
    finally:
        con.close()


def build_pik_reconciliation(accretion: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    """Implied and observed PIK from positions against the fund's reported PIK income."""
    reported = reported_quarterly_pik(evidence)
    con = duckdb.connect()
    try:
        con.register("acc", accretion)
        con.register("rep", reported)
        return con.execute("""
            WITH a AS (
              SELECT cik, report_date,
                count(*) FILTER (WHERE prior_report_date IS NOT NULL) AS n_pik_positions_with_prior,
                sum(prior_principal_amount * pik_rate / 100
                    * date_diff('day', CAST(prior_report_date AS DATE), CAST(report_date AS DATE)) / 365.25)
                  FILTER (WHERE prior_report_date IS NOT NULL AND undetermined_reason <> 'non_usd_principal')
                  AS implied_pik_terms,
                sum(principal_amount - prior_principal_amount) FILTER (WHERE payment_evidence = 'accreting')
                  AS observed_accretion,
                coalesce(sum(fair_value) FILTER (WHERE undetermined_reason = 'non_usd_principal'), 0)
                  AS non_usd_pik_fv_excluded
              FROM acc GROUP BY 1, 2
            )
            SELECT coalesce(a.cik, rep.cik) AS cik, coalesce(a.report_date, rep.report_date) AS report_date,
                   a.n_pik_positions_with_prior, a.implied_pik_terms, a.observed_accretion,
                   a.non_usd_pik_fv_excluded, rep.reported_pik, rep.reported_method, rep.reported_concept,
                   a.implied_pik_terms / nullif(rep.reported_pik, 0) AS implied_to_reported,
                   a.observed_accretion / nullif(rep.reported_pik, 0) AS observed_to_reported
            FROM a FULL OUTER JOIN rep ON rep.cik = a.cik AND rep.report_date = a.report_date
            ORDER BY 1, 2
        """).df()
    finally:
        con.close()


def _read_holdings(path: Path) -> pd.DataFrame:
    """Only the columns this module needs; the typed parquet companion when it exists."""
    parquet = path.with_suffix(".parquet")
    src = (f"read_parquet('{parquet.as_posix()}')" if parquet.exists()
           else f"read_csv('{path.as_posix()}', header=true, all_varchar=true, sample_size=-1)")
    con = duckdb.connect()
    try:
        present = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}
        select = ", ".join(c if c in present else f"NULL AS {c}" for c in HOLDING_COLUMNS)
        return con.execute(f"SELECT {select} FROM {src}").df()
    finally:
        con.close()


def build_pik_accretion_outputs(
    holdings_path: Path = UNIFIED_HOLDINGS_FILE,
    status_path: Path = POSITION_PIK_STATUS_FILE,
    evidence_path: Path = BDC_POSITION_PIK_EVIDENCE_FILE,
    reference_path: Path | None = None,
    accretion_path: Path = PIK_ACCRETION_FILE,
    summary_path: Path = PIK_LINCOLN_SUMMARY_FILE,
    reconciliation_path: Path = PIK_RECONCILIATION_FILE,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    t0 = time.time()
    holdings = _read_holdings(holdings_path)
    status = (pd.read_csv(status_path, dtype=str, usecols=["cik", "position_id", "report_date", "pik_current_status"])
              if status_path.exists() else None)
    reference = _read_holdings(reference_path) if reference_path else None
    evidence = pd.read_csv(evidence_path, dtype=str) if evidence_path.exists() else pd.DataFrame()
    if not evidence.empty and "period_start" not in evidence.columns:
        logger.warning("PIK evidence has no period_start column (built before 2026-10-14): re-run --pik-status")
    accretion = build_pik_accretion(holdings, status, reference)
    summary = build_lincoln_summary(accretion, holdings)
    reconciliation = build_pik_reconciliation(accretion, evidence)
    for frame, path in ((accretion, accretion_path), (summary, summary_path), (reconciliation, reconciliation_path)):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    logger.info("PIK accretion: %d position-quarters, %d summary rows, %d reconciliation rows in %.1f s",
                len(accretion), len(summary), len(reconciliation), time.time() - t0)
    return accretion, summary, reconciliation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-status", action="store_true",
                        help="first re-extract PIK evidence and rebuild position_pik_status")
    parser.add_argument("--reference-holdings", type=Path,
                        help="holdings of other filers for the cross-filer history (read only)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.with_status:
        from pipeline.bdc_position_pik import extract_bdc_position_pik_evidence
        from pipeline.pik_status import build_pik_schedule_proxy_outputs, build_position_pik_status
        evidence = extract_bdc_position_pik_evidence()
        status, _ = build_position_pik_status(bdc_evidence_df=evidence)
        build_pik_schedule_proxy_outputs(status_df=status)
    build_pik_accretion_outputs(reference_path=args.reference_holdings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
