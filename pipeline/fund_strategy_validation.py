"""Report-only fund strategy validation.

Compares independent fund-level strategy signals against the observed holdings
mix.  This module is diagnostic only: it writes review artifacts but does not
mutate unified holdings, classifications, frontend JSON, or index construction.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from pipeline import classification
from pipeline.config import (
    COMBINED_UNIVERSE_FILE,
    FUND_STRATEGY_CORRECTION_CANDIDATES_FILE,
    FUND_STRATEGY_HOLDINGS_MIX_FILE,
    FUND_STRATEGY_OVERRIDES_FILE,
    FUND_STRATEGY_REFERENCE_FILE,
    FUND_STRATEGY_REVIEW_QUEUE_FILE,
    FUND_STRATEGY_VALIDATION_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

ACCEPTED_STRATEGIES = {
    "PRIVATE_CREDIT",
    "PRIVATE_EQUITY",
    "REAL_ESTATE",
    "STRUCTURED_CREDIT",
    "HEDGE_FUND",
    "MULTI_STRATEGY",
    "UNKNOWN",
}

OVERRIDE_COLUMNS = [
    "cik",
    "strategy",
    "sub_strategy",
    "mechanism",
    "evidence_source",
    "evidence_accession_number",
    "evidence_text",
    "confidence",
    "effective_start_date",
    "effective_end_date",
    "review_status",
    "residual_risk",
]

REFERENCE_COLUMNS = [
    "cik",
    "entity_name",
    "fund_name",
    "vehicle_type",
    "strategy",
    "sub_strategy",
    "strategy_source",
    "confidence",
    "evidence",
    "review_status",
]

MIX_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "position_count",
    "total_fair_value",
    "private_credit_fair_value",
    "private_credit_share",
    "real_estate_fair_value",
    "real_estate_share",
    "fund_of_funds_fair_value",
    "fund_of_funds_share",
    "private_equity_fair_value",
    "private_equity_share",
    "structured_credit_fair_value",
    "structured_credit_share",
    "hedge_fund_fair_value",
    "hedge_fund_share",
    "dominant_observed_strategy",
]

VALIDATION_COLUMNS = [
    "cik",
    "entity_name",
    "report_date",
    "strategy",
    "sub_strategy",
    "strategy_source",
    "validation_status",
    "severity",
    "rule_ids",
    "affected_fair_value",
    "total_fair_value",
    "private_credit_share",
    "real_estate_share",
    "fund_of_funds_share",
    "dominant_observed_strategy",
    "evidence",
]

REVIEW_QUEUE_COLUMNS = VALIDATION_COLUMNS

CORRECTION_CANDIDATE_COLUMNS = [
    "correction_status",
    "rule_id",
    "mechanism",
    "confidence",
    "residual_risk",
    "cik",
    "entity_name",
    "report_date",
    "source",
    "accession_number",
    "bdc_investment_identifier",
    "nport_holding_id",
    "issuer_name",
    "instrument_description",
    "asset_category",
    "issuer_category",
    "nport_asset_cat",
    "nport_issuer_type",
    "current_index_classification",
    "current_asset_class",
    "proposed_index_classification",
    "proposed_asset_class",
    "fund_strategy",
    "fund_strategy_source",
    "fund_strategy_evidence",
    "row_source_evidence",
    "affected_fair_value",
    "before_metric",
    "after_metric",
]


def _normalize_cik(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if text == "" or text.lower() == "nan":
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(10) if digits else text


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _load_overrides(path: Path = FUND_STRATEGY_OVERRIDES_FILE) -> pd.DataFrame:
    if not path.exists():
        return _empty_frame(OVERRIDE_COLUMNS)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read fund strategy overrides %s: %s", path, exc)
        return _empty_frame(OVERRIDE_COLUMNS)

    records = payload.get("records", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        logger.warning("Fund strategy overrides must be a list or {'records': [...]}")
        return _empty_frame(OVERRIDE_COLUMNS)

    df = pd.DataFrame(records)
    for col in OVERRIDE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[OVERRIDE_COLUMNS].copy()
    df["cik"] = df["cik"].map(_normalize_cik)
    df["strategy"] = df["strategy"].astype(str).str.upper()
    df.loc[~df["strategy"].isin(ACCEPTED_STRATEGIES), "strategy"] = "UNKNOWN"
    df["review_status"] = df["review_status"].astype(str).str.upper()
    return df


def _load_optional_csv(path: Path, description: str) -> pd.DataFrame:
    if not path.exists():
        logger.warning("%s not found: %s", description, path)
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str)


def build_fund_strategy_reference(
    holdings_df: pd.DataFrame,
    universe_df: Optional[pd.DataFrame] = None,
    overrides_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build one strategy reference row per CIK.

    Precedence is approved override, strong vehicle-type default, weak fund-name
    signal, then UNKNOWN.  UNKNOWN is informational and does not create a
    mismatch warning.
    """
    if holdings_df.empty and (universe_df is None or universe_df.empty):
        return _empty_frame(REFERENCE_COLUMNS)

    holdings_base = holdings_df.copy()
    if "cik" not in holdings_base.columns:
        return _empty_frame(REFERENCE_COLUMNS)
    for col in ["entity_name"]:
        if col not in holdings_base.columns:
            holdings_base[col] = ""
    holdings_base["cik"] = holdings_base["cik"].map(_normalize_cik)

    if universe_df is None:
        universe_base = pd.DataFrame()
    else:
        universe_base = universe_df.copy()
    for col in ["cik", "entity_name", "fund_name", "vehicle_type"]:
        if col not in universe_base.columns:
            universe_base[col] = ""
    universe_base["cik"] = universe_base["cik"].map(_normalize_cik)

    if overrides_df is None:
        overrides_df = _load_overrides()
    else:
        overrides_df = overrides_df.copy()
        for col in OVERRIDE_COLUMNS:
            if col not in overrides_df.columns:
                overrides_df[col] = ""
        overrides_df = overrides_df[OVERRIDE_COLUMNS]
        overrides_df["cik"] = overrides_df["cik"].map(_normalize_cik)
        overrides_df["strategy"] = overrides_df["strategy"].astype(str).str.upper()
        overrides_df["review_status"] = overrides_df["review_status"].astype(str).str.upper()
    approved = overrides_df[
        overrides_df.get("review_status", pd.Series(dtype=str)).astype(str).str.upper()
        == "APPROVED"
    ].copy()

    con = duckdb.connect()
    con.register("holdings", holdings_base)
    con.register("universe", universe_base)
    con.register("overrides", approved)
    result = con.execute(
        """
        WITH holding_ciks AS (
            SELECT
                cik,
                any_value(CAST(entity_name AS VARCHAR)) AS holding_entity_name
            FROM holdings
            WHERE cik IS NOT NULL AND cik != ''
            GROUP BY cik
        ),
        universe_ciks AS (
            SELECT
                cik,
                any_value(CAST(entity_name AS VARCHAR)) AS universe_entity_name,
                any_value(CAST(fund_name AS VARCHAR)) AS fund_name,
                any_value(CAST(vehicle_type AS VARCHAR)) AS vehicle_type
            FROM universe
            WHERE cik IS NOT NULL AND cik != ''
            GROUP BY cik
        ),
        base AS (
            SELECT
                COALESCE(h.cik, u.cik) AS cik,
                COALESCE(h.holding_entity_name, u.universe_entity_name, '') AS entity_name,
                COALESCE(u.fund_name, '') AS fund_name,
                COALESCE(u.vehicle_type, '') AS vehicle_type
            FROM holding_ciks h
            FULL OUTER JOIN universe_ciks u USING (cik)
        ),
        ranked_overrides AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik
                    ORDER BY
                        NULLIF(effective_start_date, '') DESC NULLS LAST,
                        NULLIF(evidence_accession_number, '') DESC NULLS LAST
                ) AS rn
            FROM overrides
        )
        SELECT
            b.cik,
            b.entity_name,
            b.fund_name,
            b.vehicle_type,
            CASE
                WHEN o.cik IS NOT NULL THEN CAST(o.strategy AS VARCHAR)
                WHEN lower(COALESCE(b.vehicle_type, '')) = 'bdc' THEN 'PRIVATE_CREDIT'
                WHEN regexp_matches(lower(COALESCE(b.entity_name, '') || ' ' || COALESCE(b.fund_name, '')), '(real estate|\\breit\\b|\\breit|reit\\b)') THEN 'REAL_ESTATE'
                WHEN regexp_matches(lower(COALESCE(b.entity_name, '') || ' ' || COALESCE(b.fund_name, '')), '(private credit|direct lending|credit fund|income fund)') THEN 'PRIVATE_CREDIT'
                ELSE 'UNKNOWN'
            END AS strategy,
            CASE WHEN o.cik IS NOT NULL THEN COALESCE(CAST(o.sub_strategy AS VARCHAR), '') ELSE '' END AS sub_strategy,
            CASE
                WHEN o.cik IS NOT NULL THEN 'APPROVED_OVERRIDE'
                WHEN lower(COALESCE(b.vehicle_type, '')) = 'bdc' THEN 'VEHICLE_TYPE_BDC'
                WHEN regexp_matches(lower(COALESCE(b.entity_name, '') || ' ' || COALESCE(b.fund_name, '')), '(real estate|\\breit\\b|\\breit|reit\\b)') THEN 'FUND_NAME_SIGNAL'
                WHEN regexp_matches(lower(COALESCE(b.entity_name, '') || ' ' || COALESCE(b.fund_name, '')), '(private credit|direct lending|credit fund|income fund)') THEN 'FUND_NAME_SIGNAL'
                ELSE 'NO_REFERENCE'
            END AS strategy_source,
            CASE
                WHEN o.cik IS NOT NULL THEN COALESCE(CAST(o.confidence AS VARCHAR), '')
                WHEN lower(COALESCE(b.vehicle_type, '')) = 'bdc' THEN 'HIGH'
                WHEN regexp_matches(lower(COALESCE(b.entity_name, '') || ' ' || COALESCE(b.fund_name, '')), '(real estate|\\breit\\b|\\breit|reit\\b|private credit|direct lending|credit fund|income fund)') THEN 'LOW'
                ELSE 'UNKNOWN'
            END AS confidence,
            CASE
                WHEN o.cik IS NOT NULL THEN COALESCE(CAST(o.evidence_text AS VARCHAR), '')
                WHEN lower(COALESCE(b.vehicle_type, '')) = 'bdc' THEN 'vehicle_type=bdc'
                WHEN regexp_matches(lower(COALESCE(b.entity_name, '') || ' ' || COALESCE(b.fund_name, '')), '(real estate|\\breit\\b|\\breit|reit\\b|private credit|direct lending|credit fund|income fund)')
                    THEN 'name_signal=' || COALESCE(NULLIF(b.fund_name, ''), b.entity_name)
                ELSE ''
            END AS evidence,
            CASE WHEN o.cik IS NOT NULL THEN COALESCE(CAST(o.review_status AS VARCHAR), '') ELSE '' END AS review_status
        FROM base b
        LEFT JOIN ranked_overrides o ON b.cik = o.cik AND o.rn = 1
        ORDER BY b.cik
        """
    ).fetchdf()
    con.close()
    return result.reindex(columns=REFERENCE_COLUMNS).fillna("")


def build_fund_strategy_holdings_mix(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """Build FV-weighted holdings mix by CIK-report-date."""
    if holdings_df.empty or "cik" not in holdings_df.columns or "report_date" not in holdings_df.columns:
        return _empty_frame(MIX_COLUMNS)

    df = holdings_df.copy()
    for col in [
        "entity_name", "index_classification", "issuer_category",
        "asset_class", "fair_value",
    ]:
        if col not in df.columns:
            df[col] = ""
    df["cik"] = df["cik"].map(_normalize_cik)
    con = duckdb.connect()
    con.register("holdings", df)
    result = con.execute(
        """
        WITH base AS (
            SELECT
                cik,
                CAST(entity_name AS VARCHAR) AS entity_name,
                CAST(report_date AS VARCHAR) AS report_date,
                CAST(index_classification AS VARCHAR) AS index_classification,
                CAST(issuer_category AS VARCHAR) AS issuer_category,
                CAST(asset_class AS VARCHAR) AS asset_class,
                COALESCE(TRY_CAST(fair_value AS DOUBLE), 0.0) AS fair_value
            FROM holdings
            WHERE cik IS NOT NULL AND cik != ''
              AND report_date IS NOT NULL AND CAST(report_date AS VARCHAR) != ''
        ),
        grouped AS (
            SELECT
                cik,
                any_value(entity_name) AS entity_name,
                report_date,
                COUNT(*) AS position_count,
                SUM(fair_value) AS total_fair_value,
                SUM(CASE WHEN index_classification IN ('DIRECT_LENDING', 'PRIVATE_CREDIT_FUND') THEN fair_value ELSE 0 END) AS private_credit_fair_value,
                SUM(CASE WHEN index_classification IN ('DIRECT_REAL_ESTATE', 'REAL_ESTATE_FUND')
                          OR asset_class = 'REAL_ESTATE' THEN fair_value ELSE 0 END) AS real_estate_fair_value,
                SUM(CASE WHEN index_classification IN ('PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND', 'REAL_ESTATE_FUND', 'HEDGE_FUND')
                          OR issuer_category = 'FUND' THEN fair_value ELSE 0 END) AS fund_of_funds_fair_value,
                SUM(CASE WHEN index_classification IN ('COMMON_EQUITY', 'PREFERRED_EQUITY', 'PRIVATE_EQUITY_FUND') THEN fair_value ELSE 0 END) AS private_equity_fair_value,
                SUM(CASE WHEN index_classification = 'STRUCTURED_CREDIT' THEN fair_value ELSE 0 END) AS structured_credit_fair_value,
                SUM(CASE WHEN index_classification = 'HEDGE_FUND' THEN fair_value ELSE 0 END) AS hedge_fund_fair_value
            FROM base
            GROUP BY cik, report_date
        )
        SELECT
            *,
            CASE WHEN total_fair_value > 0 THEN private_credit_fair_value / total_fair_value ELSE NULL END AS private_credit_share,
            CASE WHEN total_fair_value > 0 THEN real_estate_fair_value / total_fair_value ELSE NULL END AS real_estate_share,
            CASE WHEN total_fair_value > 0 THEN fund_of_funds_fair_value / total_fair_value ELSE NULL END AS fund_of_funds_share,
            CASE WHEN total_fair_value > 0 THEN private_equity_fair_value / total_fair_value ELSE NULL END AS private_equity_share,
            CASE WHEN total_fair_value > 0 THEN structured_credit_fair_value / total_fair_value ELSE NULL END AS structured_credit_share,
            CASE WHEN total_fair_value > 0 THEN hedge_fund_fair_value / total_fair_value ELSE NULL END AS hedge_fund_share,
            CASE
                WHEN GREATEST(private_credit_fair_value, real_estate_fair_value, private_equity_fair_value, structured_credit_fair_value, hedge_fund_fair_value) = private_credit_fair_value THEN 'PRIVATE_CREDIT'
                WHEN GREATEST(private_credit_fair_value, real_estate_fair_value, private_equity_fair_value, structured_credit_fair_value, hedge_fund_fair_value) = real_estate_fair_value THEN 'REAL_ESTATE'
                WHEN GREATEST(private_credit_fair_value, real_estate_fair_value, private_equity_fair_value, structured_credit_fair_value, hedge_fund_fair_value) = private_equity_fair_value THEN 'PRIVATE_EQUITY'
                WHEN GREATEST(private_credit_fair_value, real_estate_fair_value, private_equity_fair_value, structured_credit_fair_value, hedge_fund_fair_value) = structured_credit_fair_value THEN 'STRUCTURED_CREDIT'
                WHEN GREATEST(private_credit_fair_value, real_estate_fair_value, private_equity_fair_value, structured_credit_fair_value, hedge_fund_fair_value) = hedge_fund_fair_value THEN 'HEDGE_FUND'
                ELSE 'UNKNOWN'
            END AS dominant_observed_strategy
        FROM grouped
        ORDER BY cik, report_date
        """
    ).fetchdf()
    con.close()
    return result.reindex(columns=MIX_COLUMNS)


def build_fund_strategy_validation(
    reference_df: pd.DataFrame,
    mix_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate report-only strategy rules and build the review queue."""
    if mix_df.empty:
        empty_validation = _empty_frame(VALIDATION_COLUMNS)
        return empty_validation, _empty_frame(REVIEW_QUEUE_COLUMNS)

    reference = reference_df.copy() if reference_df is not None else _empty_frame(REFERENCE_COLUMNS)
    for col in REFERENCE_COLUMNS:
        if col not in reference.columns:
            reference[col] = ""
    for col in MIX_COLUMNS:
        if col not in mix_df.columns:
            mix_df[col] = pd.NA

    con = duckdb.connect()
    con.register("reference", reference[REFERENCE_COLUMNS])
    con.register("mix", mix_df[MIX_COLUMNS])
    result = con.execute(
        """
        WITH joined AS (
            SELECT
                m.*,
                COALESCE(r.strategy, 'UNKNOWN') AS strategy,
                COALESCE(r.sub_strategy, '') AS sub_strategy,
                COALESCE(r.strategy_source, 'NO_REFERENCE') AS strategy_source,
                COALESCE(r.evidence, '') AS reference_evidence,
                COALESCE(r.review_status, '') AS review_status,
                LAG(m.dominant_observed_strategy) OVER (
                    PARTITION BY m.cik ORDER BY m.report_date
                ) AS prior_observed_strategy
            FROM mix m
            LEFT JOIN reference r USING (cik)
        ),
        evaluated AS (
            SELECT *,
                list_filter([
                    CASE WHEN strategy = 'REAL_ESTATE' AND COALESCE(real_estate_share, 0) < 0.50 THEN 'FS01' END,
                    CASE WHEN strategy = 'PRIVATE_CREDIT' AND COALESCE(private_credit_share, 0) < 0.50 THEN 'FS02' END,
                    CASE WHEN strategy = 'PRIVATE_CREDIT' AND COALESCE(fund_of_funds_share, 0) > 0.30 THEN 'FS03' END,
                    CASE WHEN strategy_source != 'APPROVED_OVERRIDE'
                           AND prior_observed_strategy IS NOT NULL
                           AND dominant_observed_strategy != prior_observed_strategy
                         THEN 'FS04' END
                ], x -> x IS NOT NULL) AS rules
            FROM joined
        )
        SELECT
            cik,
            entity_name,
            report_date,
            strategy,
            sub_strategy,
            strategy_source,
            CASE
                WHEN strategy = 'UNKNOWN' OR strategy_source = 'NO_REFERENCE' THEN 'NO_REFERENCE'
                WHEN len(rules) > 0 THEN 'UNDER_REVIEW'
                ELSE 'PASS'
            END AS validation_status,
            CASE
                WHEN strategy = 'UNKNOWN' OR strategy_source = 'NO_REFERENCE' THEN 'INFO'
                WHEN len(rules) > 0 THEN 'WARN'
                ELSE 'OK'
            END AS severity,
            array_to_string(rules, ';') AS rule_ids,
            CASE
                WHEN len(rules) = 0 THEN 0.0
                WHEN list_contains(rules, 'FS01') THEN total_fair_value * (0.50 - COALESCE(real_estate_share, 0))
                WHEN list_contains(rules, 'FS02') THEN total_fair_value * (0.50 - COALESCE(private_credit_share, 0))
                WHEN list_contains(rules, 'FS03') THEN total_fair_value * GREATEST(COALESCE(fund_of_funds_share, 0) - 0.30, 0)
                ELSE total_fair_value
            END AS affected_fair_value,
            total_fair_value,
            private_credit_share,
            real_estate_share,
            fund_of_funds_share,
            dominant_observed_strategy,
            concat_ws('; ',
                NULLIF(reference_evidence, ''),
                CASE WHEN list_contains(rules, 'FS01') THEN 'FS01: REAL_ESTATE strategy has real_estate_share=' || round(COALESCE(real_estate_share, 0), 4)::VARCHAR END,
                CASE WHEN list_contains(rules, 'FS02') THEN 'FS02: PRIVATE_CREDIT strategy has private_credit_share=' || round(COALESCE(private_credit_share, 0), 4)::VARCHAR END,
                CASE WHEN list_contains(rules, 'FS03') THEN 'FS03: PRIVATE_CREDIT vehicle has fund_of_funds_share=' || round(COALESCE(fund_of_funds_share, 0), 4)::VARCHAR END,
                CASE WHEN list_contains(rules, 'FS04') THEN 'FS04: observed strategy changed from ' || prior_observed_strategy || ' to ' || dominant_observed_strategy END
            ) AS evidence
        FROM evaluated
        ORDER BY cik, report_date
        """
    ).fetchdf()
    con.close()

    result = result.reindex(columns=VALIDATION_COLUMNS)
    for col in ["rule_ids", "evidence", "sub_strategy", "strategy_source"]:
        if col in result.columns:
            result[col] = result[col].fillna("")
    queue = result[result["validation_status"] == "UNDER_REVIEW"].copy()
    if len(queue) > 0:
        queue = queue.sort_values(
            ["affected_fair_value", "cik", "report_date"],
            ascending=[False, True, True],
            kind="mergesort",
        )
    return result, queue.reindex(columns=REVIEW_QUEUE_COLUMNS)


def build_fund_strategy_correction_candidates(
    holdings_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    review_queue_df: pd.DataFrame,
) -> pd.DataFrame:
    """Propose audited row-level corrections from strategy residuals.

    Fund strategy is only a bounded evidence source here.  A row is marked
    APPLY only when the row/source fields explain the classification mechanism.
    REVIEW rows remain diagnostic, and REJECT rows document explicit blockers.
    """
    if holdings_df.empty or review_queue_df.empty:
        return _empty_frame(CORRECTION_CANDIDATE_COLUMNS)

    holdings = holdings_df.copy()
    for col in [
        "cik", "entity_name", "report_date", "source", "accession_number",
        "bdc_investment_identifier", "nport_holding_id", "issuer_name",
        "instrument_description", "asset_category", "issuer_category",
        "nport_asset_cat", "nport_issuer_type", "index_classification",
        "asset_class", "fair_value",
    ]:
        if col not in holdings.columns:
            holdings[col] = ""
    holdings["cik"] = holdings["cik"].map(_normalize_cik)

    reference = reference_df.copy() if reference_df is not None else _empty_frame(REFERENCE_COLUMNS)
    for col in REFERENCE_COLUMNS:
        if col not in reference.columns:
            reference[col] = ""
    reference["cik"] = reference["cik"].map(_normalize_cik)

    queue = review_queue_df.copy()
    for col in REVIEW_QUEUE_COLUMNS:
        if col not in queue.columns:
            queue[col] = ""
    queue["cik"] = queue["cik"].map(_normalize_cik)
    queue = queue[queue["validation_status"].astype(str).str.upper() == "UNDER_REVIEW"]
    if queue.empty:
        return _empty_frame(CORRECTION_CANDIDATE_COLUMNS)

    re_kw = classification._sql_keyword_check(
        "_combined_fund_text",
        classification._REAL_ESTATE_KEYWORDS,
    )
    re_fund_kw = classification._sql_keyword_check(
        "_combined_fund_text",
        classification._REAL_ESTATE_FUND_KEYWORDS,
    )
    sc_kw = classification._sql_keyword_check(
        "_combined_fund_text",
        classification._STRUCTURED_CREDIT_KEYWORDS,
    )
    cash_kw = classification._sql_keyword_check(
        "_combined_fund_text",
        classification._CASH_KEYWORDS,
    )
    hedge_kw = classification._sql_keyword_check(
        "_combined_fund_text",
        classification._HEDGE_FUND_KEYWORDS,
    )

    con = duckdb.connect()
    con.register("holdings", holdings)
    con.register("reference", reference[REFERENCE_COLUMNS])
    con.register("queue", queue[REVIEW_QUEUE_COLUMNS])
    result = con.execute(
        f"""
        WITH queued_ciks AS (
            SELECT DISTINCT
                CAST(cik AS VARCHAR) AS cik,
                CAST(report_date AS VARCHAR) AS report_date,
                CAST(rule_ids AS VARCHAR) AS rule_ids
            FROM queue
        ),
        keyed AS (
            SELECT
                h.*,
                lower(
                    COALESCE(CAST(h.issuer_name AS VARCHAR), '') || ' ' ||
                    COALESCE(CAST(h.instrument_description AS VARCHAR), '')
                ) AS _combined_fund_text,
                COALESCE(TRY_CAST(h.fair_value AS DOUBLE), 0.0) AS _fair_value
            FROM holdings h
            JOIN queued_ciks q
              ON CAST(h.cik AS VARCHAR) = q.cik
             AND CAST(h.report_date AS VARCHAR) = q.report_date
        ),
        evaluated AS (
            SELECT
                k.cik,
                k.entity_name,
                k.report_date,
                k.source,
                k.accession_number,
                k.bdc_investment_identifier,
                k.nport_holding_id,
                k.issuer_name,
                k.instrument_description,
                k.asset_category,
                k.issuer_category,
                k.nport_asset_cat,
                k.nport_issuer_type,
                k.index_classification,
                k.asset_class,
                k._fair_value,
                k._combined_fund_text,
                r.strategy AS fund_strategy,
                r.strategy_source AS fund_strategy_source,
                r.evidence AS fund_strategy_evidence,
                q.rule_ids,
                ({re_kw} OR {re_fund_kw}
                 OR UPPER(TRIM(CAST(k.nport_asset_cat AS VARCHAR))) = 'RE') AS has_real_estate_row_evidence,
                (CAST(k.issuer_category AS VARCHAR) = 'FUND'
                 OR CAST(k.asset_category AS VARCHAR) = 'FUND'
                 OR UPPER(TRIM(CAST(k.nport_issuer_type AS VARCHAR))) IN ('PF', 'RF')) AS has_fund_row_evidence,
                ({sc_kw}
                 OR CAST(k.index_classification AS VARCHAR) = 'STRUCTURED_CREDIT'
                 OR CAST(k.asset_class AS VARCHAR) = 'STRUCTURED_CREDIT') AS has_structured_credit_evidence,
                ({cash_kw}
                 OR CAST(k.issuer_category AS VARCHAR) = 'GOVERNMENT'
                 OR CAST(k.index_classification AS VARCHAR) = 'CASH'
                 OR CAST(k.asset_class AS VARCHAR) = 'CASH') AS has_cash_evidence,
                ({hedge_kw}
                 OR CAST(k.index_classification AS VARCHAR) = 'HEDGE_FUND'
                 OR CAST(k.asset_class AS VARCHAR) = 'HEDGE_FUND') AS has_hedge_evidence
            FROM keyed k
            JOIN queued_ciks q
              ON CAST(k.cik AS VARCHAR) = q.cik
             AND CAST(k.report_date AS VARCHAR) = q.report_date
            LEFT JOIN reference r
              ON CAST(k.cik AS VARCHAR) = CAST(r.cik AS VARCHAR)
        ),
        proposed AS (
            SELECT *,
                CASE
                    WHEN fund_strategy = 'REAL_ESTATE'
                     AND NOT has_cash_evidence
                     AND NOT has_structured_credit_evidence
                     AND NOT has_hedge_evidence
                     AND has_fund_row_evidence
                    THEN 'REAL_ESTATE_FUND'
                    WHEN fund_strategy = 'REAL_ESTATE'
                     AND NOT has_cash_evidence
                     AND NOT has_structured_credit_evidence
                     AND NOT has_hedge_evidence
                     AND CAST(issuer_category AS VARCHAR) = 'CORPORATE'
                     AND CAST(asset_category AS VARCHAR) IN ('EQUITY_COMMON', 'EQUITY_PREFERRED')
                     AND has_real_estate_row_evidence
                    THEN 'DIRECT_REAL_ESTATE'
                    WHEN fund_strategy = 'PRIVATE_CREDIT'
                     AND NOT has_cash_evidence
                     AND NOT has_structured_credit_evidence
                     AND NOT has_hedge_evidence
                     AND has_fund_row_evidence
                    THEN 'PRIVATE_CREDIT_FUND'
                    WHEN fund_strategy = 'PRIVATE_EQUITY'
                     AND NOT has_cash_evidence
                     AND NOT has_structured_credit_evidence
                     AND NOT has_hedge_evidence
                     AND has_fund_row_evidence
                    THEN 'PRIVATE_EQUITY_FUND'
                    ELSE CAST(index_classification AS VARCHAR)
                END AS proposed_index_classification,
                CASE
                    WHEN fund_strategy = 'REAL_ESTATE'
                     AND NOT has_cash_evidence
                     AND NOT has_structured_credit_evidence
                     AND NOT has_hedge_evidence
                     AND (has_fund_row_evidence OR has_real_estate_row_evidence)
                    THEN 'REAL_ESTATE'
                    WHEN fund_strategy = 'PRIVATE_CREDIT'
                     AND NOT has_cash_evidence
                     AND NOT has_structured_credit_evidence
                     AND NOT has_hedge_evidence
                     AND has_fund_row_evidence
                    THEN 'PRIVATE_CREDIT'
                    WHEN fund_strategy = 'PRIVATE_EQUITY'
                     AND NOT has_cash_evidence
                     AND NOT has_structured_credit_evidence
                     AND NOT has_hedge_evidence
                     AND has_fund_row_evidence
                    THEN 'PRIVATE_EQUITY'
                    ELSE CAST(asset_class AS VARCHAR)
                END AS proposed_asset_class
            FROM evaluated
        )
        SELECT
            CASE
                WHEN has_cash_evidence OR has_structured_credit_evidence OR has_hedge_evidence THEN 'REJECT'
                WHEN proposed_index_classification != CAST(index_classification AS VARCHAR)
                  OR proposed_asset_class != CAST(asset_class AS VARCHAR) THEN 'APPLY'
                ELSE 'REVIEW'
            END AS correction_status,
            CASE
                WHEN contains(CAST(rule_ids AS VARCHAR), 'FS01') THEN 'FS01'
                WHEN contains(CAST(rule_ids AS VARCHAR), 'FS02') THEN 'FS02'
                WHEN contains(CAST(rule_ids AS VARCHAR), 'FS03') THEN 'FS03'
                WHEN contains(CAST(rule_ids AS VARCHAR), 'FS04') THEN 'FS04'
                ELSE CAST(rule_ids AS VARCHAR)
            END AS rule_id,
            CASE
                WHEN has_cash_evidence THEN 'explicit_cash_or_government_row_preserved'
                WHEN has_structured_credit_evidence THEN 'explicit_structured_credit_row_preserved'
                WHEN has_hedge_evidence THEN 'explicit_hedge_fund_row_preserved'
                WHEN fund_strategy = 'REAL_ESTATE' AND has_fund_row_evidence THEN 'fund_holding_strategy_alignment'
                WHEN fund_strategy = 'REAL_ESTATE' AND has_real_estate_row_evidence THEN 'direct_real_estate_row_evidence'
                WHEN fund_strategy IN ('PRIVATE_CREDIT', 'PRIVATE_EQUITY') AND has_fund_row_evidence THEN 'fund_holding_strategy_alignment'
                ELSE 'insufficient_row_evidence'
            END AS mechanism,
            CASE
                WHEN proposed_index_classification != CAST(index_classification AS VARCHAR)
                  OR proposed_asset_class != CAST(asset_class AS VARCHAR) THEN 'MEDIUM'
                ELSE 'LOW'
            END AS confidence,
            CASE
                WHEN has_cash_evidence OR has_structured_credit_evidence OR has_hedge_evidence THEN 'Conflicting explicit row evidence blocks strategy correction.'
                WHEN proposed_index_classification != CAST(index_classification AS VARCHAR)
                  OR proposed_asset_class != CAST(asset_class AS VARCHAR) THEN 'Fund strategy is independent evidence, but issuer/source fields remain the row-level mechanism.'
                ELSE 'No row-level mechanism strong enough to mutate classification.'
            END AS residual_risk,
            cik,
            entity_name,
            CAST(report_date AS VARCHAR) AS report_date,
            source,
            accession_number,
            bdc_investment_identifier,
            nport_holding_id,
            issuer_name,
            instrument_description,
            asset_category,
            issuer_category,
            nport_asset_cat,
            nport_issuer_type,
            CAST(index_classification AS VARCHAR) AS current_index_classification,
            CAST(asset_class AS VARCHAR) AS current_asset_class,
            proposed_index_classification,
            proposed_asset_class,
            fund_strategy,
            fund_strategy_source,
            fund_strategy_evidence,
            concat_ws('; ',
                CASE WHEN has_fund_row_evidence THEN 'fund_row_evidence=issuer_or_asset_category_or_nport_type' END,
                CASE WHEN has_real_estate_row_evidence THEN 'real_estate_row_evidence=name_or_nport_asset_cat' END,
                CASE WHEN has_cash_evidence THEN 'cash_or_government_row_evidence' END,
                CASE WHEN has_structured_credit_evidence THEN 'structured_credit_row_evidence' END,
                CASE WHEN has_hedge_evidence THEN 'hedge_fund_row_evidence' END
            ) AS row_source_evidence,
            _fair_value AS affected_fair_value,
            CAST(index_classification AS VARCHAR) || '|' || CAST(asset_class AS VARCHAR) AS before_metric,
            proposed_index_classification || '|' || proposed_asset_class AS after_metric
        FROM proposed
        WHERE correction_status != 'REVIEW'
           OR _fair_value > 0
        ORDER BY
            CASE correction_status WHEN 'APPLY' THEN 0 WHEN 'REVIEW' THEN 1 ELSE 2 END,
            _fair_value DESC,
            cik,
            report_date
        """
    ).fetchdf()
    con.close()
    return result.reindex(columns=CORRECTION_CANDIDATE_COLUMNS).fillna("")


# Transitions excluded from automatic application.  Spot-check found that
# RE_FUND -> PC_FUND corrections use the parent fund's credit strategy to
# override genuinely real-estate investees (EPIC Dallas, Sora Multifamily,
# Mavik RE Special Opportunities, Kennedy Lewis Residential Property, etc.).
_EXCLUDED_TRANSITIONS: set[tuple[str, str]] = {
    ("REAL_ESTATE_FUND", "PRIVATE_CREDIT_FUND"),
}

# CIKs excluded from fund strategy corrections.  The FUND_NAME_SIGNAL for
# these funds is wrong -- "Income" in the name does not imply private credit.
# abrdn Global Infrastructure Income Fund: infrastructure, not credit.
# Mexico Equity & Income Fund Inc: Mexican equity, not credit.
_EXCLUDED_CIKS: set[str] = {
    "0001793855",  # abrdn Global Infrastructure Income Fund
    "0000863900",  # Mexico Equity & Income Fund Inc
}


def apply_fund_strategy_correction_candidates(
    holdings_df: pd.DataFrame,
    candidates_df: pd.DataFrame,
) -> pd.DataFrame:
    """Apply only APPLY rows from a fund-strategy candidate report.

    This is deliberately separate from candidate generation so REVIEW/REJECT
    diagnostics cannot mutate data.  The key supports both BDC and N-PORT rows.
    Uses DuckDB for the join instead of row-level Python loops.

    Transitions listed in ``_EXCLUDED_TRANSITIONS`` are skipped (logged as
    excluded) because spot-check found them to be incorrect.
    """
    if holdings_df.empty or candidates_df is None or candidates_df.empty:
        return holdings_df

    required = {
        "correction_status", "cik", "report_date", "source",
        "accession_number", "bdc_investment_identifier", "nport_holding_id",
        "proposed_index_classification", "proposed_asset_class",
    }
    missing = required - set(candidates_df.columns)
    if missing:
        logger.warning(
            "fund strategy correction candidates missing columns: %s -- skipping",
            ", ".join(sorted(missing)),
        )
        return holdings_df

    # Filter to APPLY-only rows
    apply_rows = candidates_df[
        candidates_df["correction_status"].astype(str).str.upper() == "APPLY"
    ].copy()
    if apply_rows.empty:
        return holdings_df

    # Exclude known-bad transitions
    if "current_index_classification" in apply_rows.columns:
        excl_mask = apply_rows.apply(
            lambda r: (
                str(r.get("current_index_classification", "")),
                str(r.get("proposed_index_classification", "")),
            ) in _EXCLUDED_TRANSITIONS,
            axis=1,
        )
        n_excl_trans = int(excl_mask.sum())
        if n_excl_trans:
            logger.info(
                "Fund strategy corrections: excluded %d rows with bad transitions",
                n_excl_trans,
            )
            apply_rows = apply_rows[~excl_mask]

    # Exclude CIKs with known-bad FUND_NAME_SIGNAL strategy assignments
    if _EXCLUDED_CIKS:
        norm_ciks = apply_rows["cik"].map(_normalize_cik)
        cik_mask = norm_ciks.isin(_EXCLUDED_CIKS)
        n_excl_cik = int(cik_mask.sum())
        if n_excl_cik:
            logger.info(
                "Fund strategy corrections: excluded %d rows from %d bad-signal CIKs",
                n_excl_cik, int(norm_ciks[cik_mask].nunique()),
            )
            apply_rows = apply_rows[~cik_mask]

    if apply_rows.empty:
        logger.info("Fund strategy correction candidates: no eligible APPLY rows after exclusion")
        return holdings_df

    # Ensure required columns exist in holdings
    df = holdings_df.copy()
    for col in [
        "cik", "report_date", "source", "accession_number",
        "bdc_investment_identifier", "nport_holding_id",
        "index_classification", "asset_class",
    ]:
        if col not in df.columns:
            df[col] = ""

    # Prepare the patch table with only the columns we need
    patch = apply_rows[[
        "cik", "report_date", "source", "accession_number",
        "bdc_investment_identifier", "nport_holding_id",
        "proposed_index_classification", "proposed_asset_class",
    ]].copy()

    # DuckDB join to apply corrections vectorially
    con = duckdb.connect()
    con.register("h", df)
    con.register("p", patch)

    result = con.execute("""
        WITH h_keyed AS (
            SELECT h.*,
                ROW_NUMBER() OVER () AS _rn,
                lpad(regexp_replace(COALESCE(CAST(cik AS VARCHAR), ''), '[^0-9]', '', 'g'), 10, '0')
                    AS _norm_cik
            FROM h
        ),
        p_keyed AS (
            SELECT *,
                lpad(regexp_replace(COALESCE(CAST(cik AS VARCHAR), ''), '[^0-9]', '', 'g'), 10, '0')
                    AS _norm_cik
            FROM p
        ),
        matched AS (
            SELECT
                h._rn,
                p.proposed_index_classification,
                p.proposed_asset_class
            FROM h_keyed h
            JOIN p_keyed p
              ON h._norm_cik = p._norm_cik
             AND CAST(h.report_date AS VARCHAR) = CAST(p.report_date AS VARCHAR)
             AND CAST(h.source AS VARCHAR) = CAST(p.source AS VARCHAR)
             AND CAST(h.accession_number AS VARCHAR) = CAST(p.accession_number AS VARCHAR)
             AND CAST(h.bdc_investment_identifier AS VARCHAR) = CAST(p.bdc_investment_identifier AS VARCHAR)
             AND CAST(h.nport_holding_id AS VARCHAR) = CAST(p.nport_holding_id AS VARCHAR)
        )
        SELECT
            CASE WHEN m._rn IS NOT NULL AND m.proposed_index_classification != ''
                      AND m.proposed_index_classification != CAST(h.index_classification AS VARCHAR)
                 THEN m.proposed_index_classification
                 ELSE CAST(h.index_classification AS VARCHAR)
            END AS _new_ic,
            CASE WHEN m._rn IS NOT NULL AND m.proposed_asset_class != ''
                      AND m.proposed_asset_class != CAST(h.asset_class AS VARCHAR)
                 THEN m.proposed_asset_class
                 ELSE CAST(h.asset_class AS VARCHAR)
            END AS _new_ac,
            CASE WHEN m._rn IS NOT NULL THEN 1 ELSE 0 END AS _matched
        FROM h_keyed h
        LEFT JOIN matched m ON h._rn = m._rn
        ORDER BY h._rn
    """).fetchdf()
    con.close()

    n_matched = int(result["_matched"].sum())
    n_ic_changed = int((result["_new_ic"] != df["index_classification"].astype(str)).sum())
    n_ac_changed = int((result["_new_ac"] != df["asset_class"].astype(str)).sum())

    df["index_classification"] = result["_new_ic"].values
    df["asset_class"] = result["_new_ac"].values

    logger.info(
        "Fund strategy correction candidates: %d rows matched, "
        "%d index_classification updates, %d asset_class updates",
        n_matched, n_ic_changed, n_ac_changed,
    )
    return df


def run_fund_strategy_validation(
    unified_df: Optional[pd.DataFrame] = None,
    universe_df: Optional[pd.DataFrame] = None,
    output: bool = True,
) -> dict[str, pd.DataFrame]:
    """Run fund strategy validation and optionally write all artifacts."""
    if unified_df is None:
        unified_df = _load_optional_csv(UNIFIED_HOLDINGS_FILE, "Unified holdings file")
    if universe_df is None:
        universe_df = _load_optional_csv(COMBINED_UNIVERSE_FILE, "Combined universe file")

    if unified_df.empty:
        logger.warning("Fund strategy validation skipped: no unified holdings rows")

    overrides_df = _load_overrides()
    reference = build_fund_strategy_reference(unified_df, universe_df, overrides_df)
    mix = build_fund_strategy_holdings_mix(unified_df)
    validation, queue = build_fund_strategy_validation(reference, mix)
    candidates = build_fund_strategy_correction_candidates(
        unified_df,
        reference,
        queue,
    )

    reports = {
        "fund_strategy_reference": reference,
        "fund_strategy_holdings_mix": mix,
        "fund_strategy_validation": validation,
        "fund_strategy_review_queue": queue,
        "fund_strategy_correction_candidates": candidates,
    }

    if output:
        reference.to_csv(FUND_STRATEGY_REFERENCE_FILE, index=False)
        mix.to_csv(FUND_STRATEGY_HOLDINGS_MIX_FILE, index=False)
        validation.to_csv(FUND_STRATEGY_VALIDATION_FILE, index=False)
        queue.to_csv(FUND_STRATEGY_REVIEW_QUEUE_FILE, index=False)
        candidates.to_csv(FUND_STRATEGY_CORRECTION_CANDIDATES_FILE, index=False)
        logger.info("  Saved %s", FUND_STRATEGY_REFERENCE_FILE.name)
        logger.info("  Saved %s", FUND_STRATEGY_HOLDINGS_MIX_FILE.name)
        logger.info("  Saved %s", FUND_STRATEGY_VALIDATION_FILE.name)
        logger.info("  Saved %s", FUND_STRATEGY_REVIEW_QUEUE_FILE.name)
        logger.info("  Saved %s", FUND_STRATEGY_CORRECTION_CANDIDATES_FILE.name)

    return reports
