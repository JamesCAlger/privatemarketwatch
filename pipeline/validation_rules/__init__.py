"""Report-only DuckDB validation rules for output CSV artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Iterable
from uuid import uuid4

import duckdb
import pandas as pd

from pipeline import config
from pipeline.index_returns import MIN_BEGIN_FV, MIN_CONSTITUENTS

logger = logging.getLogger(__name__)

AGGREGATE_COLUMNS = [
    "rule_id", "category", "title", "severity", "promoted", "status",
    "hit_count", "hit_rate", "affected_fair_value", "run_id",
    "run_timestamp", "skipped_reason",
]

DETAIL_COLUMNS = [
    "finding_key", "rule_id", "category", "severity", "granularity",
    "granularity_key", "cik", "quarter", "report_date", "issuer_name",
    "position_id", "source", "affected_fair_value", "denominator",
    "hit_rate", "priority_rank", "detail", "evidence_hint",
    "source_file", "run_id",
]

DETAIL_SELECT = """
    granularity, granularity_key, cik, quarter, report_date, issuer_name,
    position_id, source, affected_fair_value, denominator, hit_rate,
    priority_rank, detail, evidence_hint, source_file
"""


@dataclass(frozen=True)
class ValidationRule:
    rule_id: str
    category: str
    title: str
    severity: str
    promoted: bool
    required_tables: tuple[str, ...]
    sql: str


TABLE_PATHS = {
    "holdings": config.UNIFIED_HOLDINGS_FILE,
    "position_returns": config.POSITION_RETURNS_FILE,
    "index_returns": config.INDEX_RETURNS_FILE,
    "fee_uplift": config.FEE_UPLIFT_FILE,
    "fund_financials": config.FUND_FINANCIALS_FILE,
}

EXPECTED_COLUMNS = {
    "holdings": [
        "cik", "quarter", "report_date", "issuer_name", "position_id",
        "instrument_description", "cusip", "source", "fair_value", "cost",
        "pct_of_net_assets", "index_classification", "asset_category",
    ],
    "position_returns": [
        "cik", "entity_name", "source", "begin_quarter", "end_quarter",
        "issuer_name", "index_classification", "asset_category",
        "begin_fair_value", "end_fair_value", "begin_cost", "end_cost",
        "begin_principal_amount", "end_principal_amount",
        "begin_interest_rate", "begin_basis_spread", "income_rate",
        "income_return", "capital_return", "total_return",
        "quarterly_total_return", "position_id", "span_months",
    ],
    "index_returns": [
        "index_classification", "quarter", "fv_weighted_return",
        "equal_weighted_return", "cost_weighted_return",
        "constituent_count", "total_begin_fv", "total_end_fv",
        "index_level_fv", "index_level_equal", "index_level_cost",
    ],
    "fee_uplift": ["cik", "quarter", "effective_uplift"],
    "fund_financials": ["cik", "report_date", "quarter", "total_assets"],
}


def _detail_sql(
    granularity: str,
    key: str,
    cik: str = "NULL",
    quarter: str = "NULL",
    report_date: str = "NULL",
    issuer: str = "NULL",
    position_id: str = "NULL",
    source: str = "NULL",
    affected_fv: str = "0",
    denominator: str = "NULL",
    hit_rate: str = "NULL",
    priority: str = "1",
    detail: str = "''",
    evidence: str = "''",
    source_file: str = "''",
) -> str:
    return f"""
        '{granularity}' AS granularity,
        CAST({key} AS VARCHAR) AS granularity_key,
        CAST({cik} AS VARCHAR) AS cik,
        CAST({quarter} AS VARCHAR) AS quarter,
        CAST({report_date} AS VARCHAR) AS report_date,
        CAST({issuer} AS VARCHAR) AS issuer_name,
        CAST({position_id} AS VARCHAR) AS position_id,
        CAST({source} AS VARCHAR) AS source,
        CAST({affected_fv} AS DOUBLE) AS affected_fair_value,
        CAST({denominator} AS DOUBLE) AS denominator,
        CAST({hit_rate} AS DOUBLE) AS hit_rate,
        CAST({priority} AS BIGINT) AS priority_rank,
        CAST({detail} AS VARCHAR) AS detail,
        CAST({evidence} AS VARCHAR) AS evidence_hint,
        CAST({source_file} AS VARCHAR) AS source_file
    """


def _rules() -> list[ValidationRule]:
    excluded = ", ".join(f"'{c.zfill(10)}'" for c in config.NPORT_EXCLUDE_CIKS)
    consumer = ", ".join(
        f"'{c}'" for c in sorted({"0001678130", "0001644771", "0002041175"})
    )

    pc02_recon = f"""
    WITH valid AS (
        SELECT *
        FROM position_returns
        WHERE TRY_CAST(quarterly_total_return AS DOUBLE) IS NOT NULL
          AND COALESCE(index_classification, '') NOT IN ('', 'UNCLASSIFIED')
          AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
    ), recomputed AS (
        SELECT index_classification, end_quarter AS quarter,
               SUM(CASE WHEN TRY_CAST(begin_cost AS DOUBLE) > 0
                        THEN TRY_CAST(begin_cost AS DOUBLE)
                             * TRY_CAST(quarterly_total_return AS DOUBLE)
                        ELSE 0 END)
               / NULLIF(SUM(CASE WHEN TRY_CAST(begin_cost AS DOUBLE) > 0
                                  THEN TRY_CAST(begin_cost AS DOUBLE)
                                  ELSE 0 END), 0) AS expected_return
        FROM valid
        GROUP BY index_classification, end_quarter
        HAVING COUNT(*) >= {MIN_CONSTITUENTS}
    ), diff AS (
        SELECT i.*, r.expected_return,
               ABS(COALESCE(TRY_CAST(i.cost_weighted_return AS DOUBLE), 999999)
                   - COALESCE(r.expected_return, 999998)) AS delta
        FROM index_returns i
        JOIN recomputed r USING (index_classification, quarter)
        WHERE delta > 0.000001
    )
    SELECT {_detail_sql(
        "index_quarter",
        "index_classification || '|' || quarter",
        quarter="quarter",
        affected_fv="TRY_CAST(total_begin_fv AS DOUBLE)",
        hit_rate="delta",
        priority="ROW_NUMBER() OVER (ORDER BY delta DESC, index_classification, quarter)",
        detail="'cost_weighted_return differs from positive-cost recomputation'",
        evidence="'Recompute from eligible position_returns rows only'",
        source_file="'index_returns.csv;position_returns.csv'",
    )} FROM diff
    """

    pc03_recon = f"""
    WITH valid AS (
        SELECT *
        FROM position_returns
        WHERE TRY_CAST(quarterly_total_return AS DOUBLE) IS NOT NULL
          AND COALESCE(index_classification, '') NOT IN ('', 'UNCLASSIFIED')
          AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
    ), recomputed AS (
        SELECT index_classification, end_quarter AS quarter,
               SUM(TRY_CAST(begin_fair_value AS DOUBLE)
                   * TRY_CAST(quarterly_total_return AS DOUBLE))
                   / NULLIF(SUM(TRY_CAST(begin_fair_value AS DOUBLE)), 0)
                   AS fv_weighted_return,
               AVG(TRY_CAST(quarterly_total_return AS DOUBLE))
                   AS equal_weighted_return,
               COUNT(*) AS constituent_count,
               SUM(TRY_CAST(begin_fair_value AS DOUBLE)) AS total_begin_fv,
               SUM(TRY_CAST(end_fair_value AS DOUBLE)) AS total_end_fv
        FROM valid
        GROUP BY index_classification, end_quarter
        HAVING COUNT(*) >= {MIN_CONSTITUENTS}
    ), diff AS (
        SELECT i.*,
               GREATEST(
                 ABS(COALESCE(TRY_CAST(i.fv_weighted_return AS DOUBLE), 999999)
                     - COALESCE(r.fv_weighted_return, 999998)),
                 ABS(COALESCE(TRY_CAST(i.equal_weighted_return AS DOUBLE), 999999)
                     - COALESCE(r.equal_weighted_return, 999998)),
                 ABS(COALESCE(TRY_CAST(i.constituent_count AS DOUBLE), 999999)
                     - COALESCE(CAST(r.constituent_count AS DOUBLE), 999998)),
                 ABS(COALESCE(TRY_CAST(i.total_begin_fv AS DOUBLE), 999999)
                     - COALESCE(r.total_begin_fv, 999998)),
                 ABS(COALESCE(TRY_CAST(i.total_end_fv AS DOUBLE), 999999)
                     - COALESCE(r.total_end_fv, 999998))
               ) AS delta
        FROM index_returns i
        JOIN recomputed r USING (index_classification, quarter)
        WHERE delta > 0.000001
    )
    SELECT {_detail_sql(
        "index_quarter",
        "index_classification || '|' || quarter",
        quarter="quarter",
        affected_fv="TRY_CAST(total_begin_fv AS DOUBLE)",
        hit_rate="delta",
        priority="ROW_NUMBER() OVER (ORDER BY delta DESC, index_classification, quarter)",
        detail="'index aggregate fields differ from eligible row recomputation'",
        evidence="'Uses same valid-row guard as pipeline.index_returns'",
        source_file="'index_returns.csv;position_returns.csv'",
    )} FROM diff
    """

    rules = [
        ValidationRule("PC01", "PC", "Direct lending missing usable income rates", "WARN", False, ("position_returns",),
            f"""WITH g AS (
                SELECT end_quarter AS quarter,
                       COUNT(*) AS n,
                       SUM(CASE WHEN TRY_CAST(income_rate AS DOUBLE) > 0 THEN 0 ELSE 1 END) AS misses,
                       SUM(TRY_CAST(begin_fair_value AS DOUBLE)) AS fv
                FROM position_returns
                WHERE index_classification = 'DIRECT_LENDING'
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
                GROUP BY end_quarter
                HAVING n > 0 AND misses::DOUBLE / n > 0.05
            )
            SELECT {_detail_sql("quarter", "quarter", quarter="quarter",
            affected_fv="fv", denominator="n", hit_rate="misses::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY misses::DOUBLE / n DESC, quarter)",
            detail="'More than 5% of direct-lending positions lack usable income_rate'",
            evidence="'Inspect position_returns income_rate and upstream rate extraction'",
            source_file="'position_returns.csv'")} FROM g"""),
        ValidationRule("PC02", "PC", "Cost-weighted index return reconciles", "FAIL", True, ("position_returns", "index_returns"), pc02_recon),
        ValidationRule("PC03", "PC", "Index aggregate fields reconcile", "FAIL", True, ("position_returns", "index_returns"), pc03_recon),
        ValidationRule("PC04", "PC", "Sparse high-FV CIK-quarter holdings", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, COUNT(*) AS n,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings GROUP BY cik, q
                HAVING n < 10 AND fv > 1000000000
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fv", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, cik, q)",
            detail="'CIK-quarter has fewer than 10 holdings and more than $1B FV'",
            evidence="'Check subtotal leakage or incomplete extraction'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("PC05", "PC", "Cross-source duplicate holding candidate", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, report_date, lower(trim(issuer_name)) AS issuer,
                       TRY_CAST(fair_value AS DOUBLE) AS fv,
                       COUNT(DISTINCT lower(source)) AS srcs, COUNT(*) AS n
                FROM holdings
                WHERE issuer_name IS NOT NULL AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                GROUP BY cik, report_date, issuer, fv
                HAVING srcs > 1
            )
            SELECT {_detail_sql("holding_key", "cik || '|' || report_date || '|' || issuer || '|' || fv",
            cik="cik", report_date="report_date", issuer="issuer", affected_fv="fv",
            denominator="n", priority="ROW_NUMBER() OVER (ORDER BY fv DESC, cik)",
            detail="'Same CIK/date/issuer/FV appears from multiple sources'",
            evidence="'Potential BDC/N-PORT duplicate exposure'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("PC06", "PC", "Within-source duplicate holding candidate", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, report_date, source, lower(trim(issuer_name)) AS issuer,
                       lower(trim(COALESCE(instrument_description, ''))) AS instrument,
                       upper(trim(COALESCE(cusip, ''))) AS norm_cusip,
                       TRY_CAST(fair_value AS DOUBLE) AS fv, COUNT(*) AS n
                FROM holdings
                WHERE issuer_name IS NOT NULL AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                GROUP BY cik, report_date, source, issuer, instrument, norm_cusip, fv
                HAVING n > 1
            )
            SELECT {_detail_sql("holding_key", "cik || '|' || report_date || '|' || source || '|' || issuer || '|' || instrument || '|' || norm_cusip || '|' || fv",
            cik="cik", report_date="report_date", issuer="issuer", source="source",
            affected_fv="fv", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY n DESC, fv DESC, cik)",
            detail="'Same CIK/date/source/issuer/instrument/CUSIP/FV appears multiple times'",
            evidence="'Potential duplicated XBRL dimension path after tranche/CUSIP disambiguation'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("PC07", "PC", "CIK-quarter pct-of-net-assets sum high", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik,
                       LPAD(REGEXP_REPLACE(cik, '[^0-9]', '', 'g'), 10, '0') AS norm_cik,
                       COALESCE(quarter, report_date) AS q,
                       SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) AS pct_sum,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings GROUP BY cik, norm_cik, q HAVING pct_sum > 250
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fv", hit_rate="pct_sum",
            priority="ROW_NUMBER() OVER (ORDER BY pct_sum DESC, cik, q)",
            detail="'pct_of_net_assets sums above 250% for CIK-quarter'",
            evidence="CASE WHEN norm_cik IN ('0001786835', '0001825248', '0001551901') THEN 'Known multi-entity BDC residual pending fund financials population; do not exclude without reconciliation' ELSE 'Likely subtotal leakage or duplicate dimensions' END",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("PC08", "PC", "Loaded table schema and numeric casts", "WARN", False,
            ("holdings", "position_returns", "index_returns"),
            f"""WITH bad AS (
                SELECT 'holdings' AS tbl, 'fair_value' AS col, cik, COALESCE(quarter, report_date) AS q,
                       issuer_name, source, fair_value AS raw, TRY_CAST(fair_value AS DOUBLE) AS val
                FROM holdings WHERE COALESCE(fair_value, '') <> '' AND TRY_CAST(fair_value AS DOUBLE) IS NULL
                UNION ALL
                SELECT 'position_returns', 'begin_fair_value', cik, end_quarter, issuer_name, source,
                       begin_fair_value, TRY_CAST(begin_fair_value AS DOUBLE)
                FROM position_returns WHERE COALESCE(begin_fair_value, '') <> '' AND TRY_CAST(begin_fair_value AS DOUBLE) IS NULL
                UNION ALL
                SELECT 'index_returns', 'fv_weighted_return', NULL, quarter, index_classification, NULL,
                       fv_weighted_return, TRY_CAST(fv_weighted_return AS DOUBLE)
                FROM index_returns WHERE COALESCE(fv_weighted_return, '') <> '' AND TRY_CAST(fv_weighted_return AS DOUBLE) IS NULL
            )
            SELECT {_detail_sql("table_column", "tbl || '|' || col || '|' || COALESCE(cik, '') || '|' || COALESCE(q, '')",
            cik="cik", quarter="q", issuer="issuer_name", source="source",
            priority="ROW_NUMBER() OVER (ORDER BY tbl, col, cik, q)",
            detail="'Non-empty numeric contract field failed TRY_CAST'",
            evidence="'Check CSV schema and type normalization'",
            source_file="tbl || '.csv'")} FROM bad"""),
        ValidationRule("PC09", "PC", "Multi-quarter holdings missing position_id", "WARN", False, ("holdings",),
            f"""WITH multi AS (
                SELECT lower(trim(issuer_name)) AS issuer, cik, COUNT(DISTINCT report_date) AS periods
                FROM holdings WHERE issuer_name IS NOT NULL GROUP BY issuer, cik HAVING periods > 1
            ), g AS (
                SELECT h.cik, COUNT(*) AS n,
                       SUM(CASE WHEN COALESCE(h.position_id, '') = '' THEN 1 ELSE 0 END) AS missing,
                       SUM(TRY_CAST(h.fair_value AS DOUBLE)) AS fv
                FROM holdings h JOIN multi m ON h.cik = m.cik AND lower(trim(h.issuer_name)) = m.issuer
                GROUP BY h.cik HAVING n > 0 AND missing::DOUBLE / n > 0.25
            )
            SELECT {_detail_sql("cik", "cik", cik="cik", affected_fv="fv",
            denominator="n", hit_rate="missing::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY missing::DOUBLE / n DESC, cik)",
            detail="'High share of multi-quarter holdings missing position_id'",
            evidence="'Position matching may be under-linking repeat holdings'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("PC10", "PC", "Fee uplift exceeds 5 percentage points", "WARN", False, ("fee_uplift",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(effective_uplift AS DOUBLE) AS uplift
                FROM fee_uplift WHERE TRY_CAST(effective_uplift AS DOUBLE) > 5.0
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || quarter",
            cik="cik", quarter="quarter", hit_rate="uplift",
            priority="ROW_NUMBER() OVER (ORDER BY uplift DESC, cik, quarter)",
            detail="'effective_uplift exceeds 5 percentage points'",
            evidence="'Check fund income and fee uplift calculation'",
            source_file="'fee_uplift.csv'")} FROM g"""),
        ValidationRule("PC11", "PC", "Excluded N-PORT CIK in unified holdings", "FAIL", True, ("holdings",),
            f"""WITH g AS (
                SELECT LPAD(REGEXP_REPLACE(cik, '[^0-9]', '', 'g'), 10, '0') AS norm_cik,
                       COUNT(*) AS n, SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings GROUP BY norm_cik HAVING norm_cik IN ({excluded})
            )
            SELECT {_detail_sql("cik", "norm_cik", cik="norm_cik",
            affected_fv="fv", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, norm_cik)",
            detail="'CIK from NPORT_EXCLUDE_CIKS appears in unified holdings'",
            evidence="'Consumer/marketplace lending rows should be excluded from index-facing holdings'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("PC12", "PC", "Consumer-lending CIK in position returns", "FAIL", True, ("position_returns",),
            f"""WITH g AS (
                SELECT LPAD(REGEXP_REPLACE(cik, '[^0-9]', '', 'g'), 10, '0') AS norm_cik,
                       COUNT(*) AS n, SUM(TRY_CAST(begin_fair_value AS DOUBLE)) AS fv
                FROM position_returns GROUP BY norm_cik HAVING norm_cik IN ({consumer})
            )
            SELECT {_detail_sql("cik", "norm_cik", cik="norm_cik",
            affected_fv="fv", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, norm_cik)",
            detail="'Consumer-lending CIK appears in position_returns'",
            evidence="'Index-facing returns should exclude opaque consumer-loan funds'",
            source_file="'position_returns.csv'")} FROM g"""),
    ]

    idx_rules = [
        ("IDX01", "Index return absolute value exceeds 25%", "ABS(TRY_CAST(fv_weighted_return AS DOUBLE)) > 0.25", "ABS(TRY_CAST(fv_weighted_return AS DOUBLE))"),
        ("IDX02", "Index level is non-positive", "TRY_CAST(index_level_fv AS DOUBLE) <= 0", "TRY_CAST(index_level_fv AS DOUBLE)"),
        ("IDX03", "Equal-weighted and FV-weighted returns diverge", "ABS(TRY_CAST(equal_weighted_return AS DOUBLE) - TRY_CAST(fv_weighted_return AS DOUBLE)) > 0.15", "ABS(TRY_CAST(equal_weighted_return AS DOUBLE) - TRY_CAST(fv_weighted_return AS DOUBLE))"),
        ("IDX04", "Cost-weighted and FV-weighted returns diverge", "ABS(TRY_CAST(cost_weighted_return AS DOUBLE) - TRY_CAST(fv_weighted_return AS DOUBLE)) > 0.15", "ABS(TRY_CAST(cost_weighted_return AS DOUBLE) - TRY_CAST(fv_weighted_return AS DOUBLE))"),
        ("IDX05", "Index aggregate has non-positive count or FV", "TRY_CAST(constituent_count AS DOUBLE) <= 0 OR TRY_CAST(total_begin_fv AS DOUBLE) <= 0", "TRY_CAST(total_begin_fv AS DOUBLE)"),
    ]
    for rid, title, pred, metric in idx_rules:
        rules.append(ValidationRule(rid, "IDX", title, "WARN", True, ("index_returns",),
            f"""WITH g AS (SELECT *, {metric} AS metric FROM index_returns WHERE {pred})
            SELECT {_detail_sql("index_quarter", "index_classification || '|' || quarter",
            quarter="quarter", affected_fv="TRY_CAST(total_begin_fv AS DOUBLE)",
            hit_rate="metric", priority="ROW_NUMBER() OVER (ORDER BY metric DESC NULLS LAST, index_classification, quarter)",
            detail=f"'{title}'", evidence="'Inspect index_returns aggregate and source position rows'",
            source_file="'index_returns.csv'")} FROM g"""))

    rules.extend([
        ValidationRule("IDX06", "IDX", "Single-position concentration above 50%", "WARN", True, ("position_returns",),
            f"""WITH valid AS (
                SELECT *, TRY_CAST(begin_fair_value AS DOUBLE) AS bfv
                FROM position_returns
                WHERE TRY_CAST(quarterly_total_return AS DOUBLE) IS NOT NULL
                  AND COALESCE(index_classification, '') NOT IN ('', 'UNCLASSIFIED')
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
            ), g AS (
                SELECT *, bfv / NULLIF(SUM(bfv) OVER (PARTITION BY index_classification, end_quarter), 0) AS weight
                FROM valid
            )
            SELECT {_detail_sql("position", "index_classification || '|' || end_quarter || '|' || COALESCE(position_id, issuer_name)",
            cik="cik", quarter="end_quarter", issuer="issuer_name", position_id="position_id",
            source="source", affected_fv="bfv", hit_rate="weight",
            priority="ROW_NUMBER() OVER (ORDER BY weight DESC, bfv DESC)",
            detail="'Single eligible position exceeds 50% of index-quarter FV'",
            evidence="'Concentration may make index return fragile'",
            source_file="'position_returns.csv'")} FROM g WHERE weight > 0.50"""),
        ValidationRule("IDX07", "IDX", "Negative beginning FV eligible for index", "WARN", True, ("position_returns",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(begin_fair_value AS DOUBLE) AS bfv
                FROM position_returns
                WHERE TRY_CAST(quarterly_total_return AS DOUBLE) IS NOT NULL
                  AND COALESCE(index_classification, '') NOT IN ('', 'UNCLASSIFIED')
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
                  AND TRY_CAST(begin_fair_value AS DOUBLE) < 0
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || end_quarter)",
            cik="cik", quarter="end_quarter", issuer="issuer_name", position_id="position_id",
            source="source", affected_fv="bfv",
            priority="ROW_NUMBER() OVER (ORDER BY bfv ASC)",
            detail="'Eligible position has negative begin_fair_value'",
            evidence="'Negative weights would corrupt index aggregation'",
            source_file="'position_returns.csv'")} FROM g"""),
        ValidationRule("IDX08", "IDX", "High share of zero position returns", "WARN", True, ("position_returns",),
            f"""WITH g AS (
                SELECT index_classification, end_quarter AS quarter, COUNT(*) AS n,
                       SUM(CASE WHEN ABS(TRY_CAST(quarterly_total_return AS DOUBLE)) < 0.0000001 THEN 1 ELSE 0 END) AS zeros,
                       SUM(TRY_CAST(begin_fair_value AS DOUBLE)) AS fv
                FROM position_returns
                WHERE TRY_CAST(quarterly_total_return AS DOUBLE) IS NOT NULL
                  AND COALESCE(index_classification, '') NOT IN ('', 'UNCLASSIFIED')
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
                GROUP BY index_classification, end_quarter
                HAVING n >= {MIN_CONSTITUENTS} AND zeros::DOUBLE / n > 0.5
            )
            SELECT {_detail_sql("index_quarter", "index_classification || '|' || quarter",
            quarter="quarter", affected_fv="fv", denominator="n",
            hit_rate="zeros::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY zeros::DOUBLE / n DESC, index_classification, quarter)",
            detail="'More than half of eligible positions have zero quarterly return'",
            evidence="'May indicate stale marks or missing income/capital movement'",
            source_file="'position_returns.csv'")} FROM g"""),
        ValidationRule("IDX09", "IDX", "Direct lending income return unusually high", "WARN", True, ("position_returns",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(income_return AS DOUBLE)
                          * 3.0
                          / COALESCE(NULLIF(TRY_CAST(span_months AS DOUBLE), 0), 3) AS q_inc,
                       TRY_CAST(begin_fair_value AS DOUBLE) AS bfv
                FROM position_returns
                WHERE index_classification = 'DIRECT_LENDING'
                  AND TRY_CAST(quarterly_total_return AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(income_return AS DOUBLE)
                      * 3.0
                      / COALESCE(NULLIF(TRY_CAST(span_months AS DOUBLE), 0), 3) > 0.20
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || end_quarter)",
            cik="cik", quarter="end_quarter", issuer="issuer_name", position_id="position_id",
            source="source", affected_fv="bfv", hit_rate="q_inc",
            priority="ROW_NUMBER() OVER (ORDER BY q_inc DESC, bfv DESC)",
            detail="'Direct-lending quarter-equivalent income return exceeds 20%'",
            evidence="'Span-adjusted income screen; check rate scale, PIK, fee uplift, and period length'",
            source_file="'position_returns.csv'")} FROM g"""),
        ValidationRule("T01", "PC", "CIK position count changes more than 50% QoQ", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COUNT(*) AS n, SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings GROUP BY cik, q
            ), lagged AS (
                SELECT *, LAG(n) OVER (PARTITION BY cik ORDER BY q) AS prev_n
                FROM g
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fv", denominator="prev_n",
            hit_rate="ABS(n - prev_n)::DOUBLE / NULLIF(prev_n, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(n - prev_n)::DOUBLE / NULLIF(prev_n, 0) DESC, cik, q)",
            detail="'CIK position count changed by more than 50% versus prior observed quarter'",
            evidence="'Check extraction completeness, source period, and true portfolio turnover'",
            source_file="'private_markets_holdings.csv'")} FROM lagged
            WHERE prev_n > 0 AND ABS(n - prev_n)::DOUBLE / prev_n > 0.5"""),
        ValidationRule("T02", "PC", "CIK total FV jumps more than 3x or drops more than 70% QoQ", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings GROUP BY cik, q
            ), lagged AS (
                SELECT *, LAG(fv) OVER (PARTITION BY cik ORDER BY q) AS prev_fv
                FROM g
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fv", denominator="prev_fv",
            hit_rate="fv / NULLIF(prev_fv, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(fv / NULLIF(prev_fv, 0) - 1) DESC, cik, q)",
            detail="'CIK total FV jumped more than 3x or dropped more than 70% versus prior observed quarter'",
            evidence="'Check filing period, source completeness, and GAV reconciliation'",
            source_file="'private_markets_holdings.csv'")} FROM lagged
            WHERE prev_fv > 0 AND (fv / prev_fv > 3 OR fv / prev_fv < 0.3)"""),
        ValidationRule("R07", "PC", "Single position FV exceeds fund total assets", "WARN", False, ("holdings", "fund_financials"),
            f"""WITH ff AS (
                SELECT cik, COALESCE(report_date, quarter) AS d,
                       MAX(TRY_CAST(total_assets AS DOUBLE)) AS total_assets
                FROM fund_financials GROUP BY cik, d
            ), g AS (
                SELECT h.*, TRY_CAST(h.fair_value AS DOUBLE) AS fv, ff.total_assets
                FROM holdings h JOIN ff ON h.cik = ff.cik AND COALESCE(h.report_date, h.quarter) = ff.d
                WHERE TRY_CAST(h.fair_value AS DOUBLE) > ff.total_assets AND ff.total_assets > 0
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            denominator="total_assets", hit_rate="fv / total_assets",
            priority="ROW_NUMBER() OVER (ORDER BY fv / total_assets DESC, cik)",
            detail="'Single position fair value exceeds fund total_assets'",
            evidence="'Check FV scale, fund financial scale, and filing period alignment'",
            source_file="'private_markets_holdings.csv;fund_financials.csv'")} FROM g"""),
        ValidationRule("M02", "PC", "Matched-pair begin/end FV ratio extreme", "WARN", False, ("position_returns",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(begin_fair_value AS DOUBLE) AS bfv,
                       TRY_CAST(end_fair_value AS DOUBLE) AS efv
                FROM position_returns
                WHERE TRY_CAST(begin_fair_value AS DOUBLE) > 0
                  AND TRY_CAST(end_fair_value AS DOUBLE) > 0
                  AND (TRY_CAST(end_fair_value AS DOUBLE) / TRY_CAST(begin_fair_value AS DOUBLE) > 10
                       OR TRY_CAST(end_fair_value AS DOUBLE) / TRY_CAST(begin_fair_value AS DOUBLE) < 0.1)
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || end_quarter)",
            cik="cik", quarter="end_quarter", issuer="issuer_name", position_id="position_id",
            source="source", affected_fv="bfv", denominator="efv",
            hit_rate="efv / bfv",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(LOG(efv / bfv)) DESC, cik)",
            detail="'Matched pair begin/end FV ratio is above 10x or below 0.1x'",
            evidence="'Review match quality, corporate actions, and transaction effects'",
            source_file="'position_returns.csv'")} FROM g"""),
    ])
    return rules


RULE_REGISTRY = {rule.rule_id: rule for rule in _rules()}


def _empty_detail() -> pd.DataFrame:
    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _load_tables(
    con: duckdb.DuckDBPyConnection,
    categories: set[str],
    table_paths: dict[str, str | Path] | None,
) -> dict[str, str]:
    paths = {**TABLE_PATHS, **(table_paths or {})}
    needed = {
        table
        for rule in RULE_REGISTRY.values()
        if rule.category in categories
        for table in rule.required_tables
    }
    missing: dict[str, str] = {}
    for table in sorted(needed):
        path = Path(paths[table])
        if not path.exists():
            missing[table] = f"missing file: {path}"
            continue
        raw = f"_{table}_raw"
        csv_path = str(path).replace("'", "''")
        con.execute(
            f"""
            CREATE TEMP VIEW {raw} AS
            SELECT * FROM read_csv(
                '{csv_path}', header=true, all_varchar=true, ignore_errors=false
            )
            """
        )
        cols = {row[1].lower(): row[1] for row in con.execute(f"PRAGMA table_info('{raw}')").fetchall()}
        selects = []
        for col in EXPECTED_COLUMNS[table]:
            if col.lower() in cols:
                selects.append(f'CAST("{cols[col.lower()]}" AS VARCHAR) AS {col}')
            else:
                selects.append(f"CAST(NULL AS VARCHAR) AS {col}")
        con.execute(f"CREATE TEMP VIEW {table} AS SELECT {', '.join(selects)} FROM {raw}")
    return missing


def _skip_row(rule: ValidationRule, run_id: str, ts: str, reason: str) -> dict:
    return {
        "rule_id": rule.rule_id,
        "category": rule.category,
        "title": rule.title,
        "severity": rule.severity,
        "promoted": rule.promoted,
        "status": "SKIPPED",
        "hit_count": 0,
        "hit_rate": 0.0,
        "affected_fair_value": 0.0,
        "run_id": run_id,
        "run_timestamp": ts,
        "skipped_reason": reason,
    }


def _run_rule(
    con: duckdb.DuckDBPyConnection,
    rule: ValidationRule,
    run_id: str,
    ts: str,
) -> tuple[dict, pd.DataFrame]:
    detail = con.execute(rule.sql).fetchdf()
    for col in DETAIL_COLUMNS:
        if col not in detail.columns and col not in {"finding_key", "rule_id", "category", "severity", "run_id"}:
            detail[col] = None
    if detail.empty:
        capped = _empty_detail()
        hit_count = 0
        hit_rate = 0.0
        affected = 0.0
    else:
        hit_count = len(detail)
        hit_rate = float(pd.to_numeric(detail["hit_rate"], errors="coerce").mean(skipna=True) or 0.0)
        affected = float(pd.to_numeric(detail["affected_fair_value"], errors="coerce").fillna(0).sum())
        detail["rule_id"] = rule.rule_id
        detail["category"] = rule.category
        detail["severity"] = rule.severity
        detail["run_id"] = run_id
        natural = (
            rule.rule_id + "|"
            + detail["granularity_key"].fillna("").astype(str) + "|"
            + detail["cik"].fillna("").astype(str) + "|"
            + detail["quarter"].fillna("").astype(str) + "|"
            + detail["report_date"].fillna("").astype(str) + "|"
            + detail["issuer_name"].fillna("").astype(str) + "|"
            + detail["position_id"].fillna("").astype(str)
        )
        detail["finding_key"] = natural.map(lambda v: __import__("hashlib").md5(v.encode("utf-8")).hexdigest()[:16])
        detail = detail.sort_values(
            ["priority_rank", "finding_key"], kind="mergesort", na_position="last"
        )
        capped = detail.head(10000).loc[:, DETAIL_COLUMNS].reset_index(drop=True)

    status = "PASS"
    if hit_count:
        status = "FAIL" if rule.promoted and rule.severity == "FAIL" else "WARN"
        if status == "FAIL":
            logger.error("%s %s: %d promoted FAIL findings", rule.rule_id, rule.title, hit_count)

    aggregate = {
        "rule_id": rule.rule_id,
        "category": rule.category,
        "title": rule.title,
        "severity": rule.severity,
        "promoted": rule.promoted,
        "status": status,
        "hit_count": hit_count,
        "hit_rate": hit_rate,
        "affected_fair_value": affected,
        "run_id": run_id,
        "run_timestamp": ts,
        "skipped_reason": "",
    }
    return aggregate, capped


def run_all(
    categories: Iterable[str] | None = None,
    table_paths: dict[str, str | Path] | None = None,
    run_id: str | None = None,
    write: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = {c.upper() for c in (categories or ("PC", "IDX"))}
    run_id = run_id or uuid4().hex[:12]
    ts = datetime.now(timezone.utc).isoformat()

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    missing = _load_tables(con, selected, table_paths)

    aggregate_rows = []
    detail_frames = []
    for rule in RULE_REGISTRY.values():
        if rule.category not in selected:
            continue
        missing_for_rule = [missing[t] for t in rule.required_tables if t in missing]
        if missing_for_rule:
            aggregate_rows.append(_skip_row(rule, run_id, ts, "; ".join(missing_for_rule)))
            continue
        try:
            aggregate, detail = _run_rule(con, rule, run_id, ts)
        except Exception as exc:
            aggregate_rows.append(_skip_row(rule, run_id, ts, f"execution error: {exc}"))
            logger.exception("Validation rule %s failed", rule.rule_id)
            continue
        aggregate_rows.append(aggregate)
        if not detail.empty:
            detail_frames.append(detail)
    con.close()

    aggregate_df = pd.DataFrame(aggregate_rows, columns=AGGREGATE_COLUMNS)
    detail_df = (
        pd.concat(detail_frames, ignore_index=True)
        if detail_frames else _empty_detail()
    )
    detail_df = detail_df.loc[:, DETAIL_COLUMNS]

    if write:
        aggregate_path = config.VALIDATION_RULES_AGGREGATE_FILE
        detail_path = config.VALIDATION_RULES_DETAIL_FILE
        aggregate_path.parent.mkdir(parents=True, exist_ok=True)
        aggregate_df.to_csv(aggregate_path, index=False)
        detail_df.to_csv(detail_path, index=False)
        logger.info("Wrote validation rules aggregate: %s (%d rows)", aggregate_path, len(aggregate_df))
        logger.info("Wrote validation rules detail: %s (%d rows)", detail_path, len(detail_df))

    return aggregate_df, detail_df


def run_category(
    category: str,
    table_paths: dict[str, str | Path] | None = None,
    run_id: str | None = None,
    write: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return run_all(categories=[category], table_paths=table_paths, run_id=run_id, write=write)


__all__ = [
    "AGGREGATE_COLUMNS",
    "DETAIL_COLUMNS",
    "RULE_REGISTRY",
    "ValidationRule",
    "run_all",
    "run_category",
]
