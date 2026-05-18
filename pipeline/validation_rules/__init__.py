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
    "hit_count", "hit_rate", "affected_fair_value", "affected_outputs",
    "run_id", "run_timestamp", "skipped_reason",
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
    depends_on: tuple[str, ...] = ()
    affected_outputs: tuple[str, ...] = ()


TABLE_PATHS = {
    "holdings": config.UNIFIED_HOLDINGS_FILE,
    "bdc_holdings": config.BDC_HOLDINGS_FILE,
    "bdc_fund_income": config.BDC_FUND_INCOME_FILE,
    "position_returns": config.POSITION_RETURNS_FILE,
    "index_returns": config.INDEX_RETURNS_FILE,
    "fee_uplift": config.FEE_UPLIFT_FILE,
    "fund_financials": config.FUND_FINANCIALS_FILE,
    "fund_financials_cross_level": config.FUND_FINANCIALS_CROSS_LEVEL_FILE,
    "combined_universe": config.COMBINED_UNIVERSE_FILE,
    "position_matches": config.POSITION_MATCHES_FILE,
    "bdc_filings_index": config.BDC_FILINGS_INDEX_FILE,
    "entity_lookup": config.ENTITY_LOOKUP_FILE,
}

EXPECTED_COLUMNS = {
    "holdings": [
        "cik", "quarter", "report_date", "issuer_name", "position_id",
        "instrument_description", "cusip", "source", "fair_value", "cost",
        "pct_of_net_assets", "index_classification", "asset_category",
        "interest_rate", "basis_spread", "pik_rate", "maturity_date",
        "coupon_type", "principal_amount", "shares_held",
        "exposure_type", "asset_class", "entity_id",
        "gics_sub_industry", "entity_name",
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
    "bdc_holdings": [
        "cik", "quarter", "report_date", "issuer_name", "fair_value",
        "accession_number", "source",
    ],
    "bdc_fund_income": [
        "cik", "quarter", "report_date", "investment_income",
        "interest_income", "total_investment_income", "source",
    ],
    "index_returns": [
        "index_classification", "quarter", "fv_weighted_return",
        "equal_weighted_return", "cost_weighted_return",
        "constituent_count", "total_begin_fv", "total_end_fv",
        "index_level_fv", "index_level_equal", "index_level_cost",
    ],
    "fee_uplift": ["cik", "quarter", "effective_uplift"],
    "fund_financials": ["cik", "report_date", "quarter", "report_quarter", "total_assets"],
    "fund_financials_cross_level": [
        "cik", "quarter", "report_quarter", "report_date", "metric",
        "source_value", "fund_financials_value", "status",
    ],
    "combined_universe": [
        "cik", "entity_name", "vehicle_type", "status",
    ],
    "position_matches": [
        "cik", "source", "begin_quarter", "end_quarter",
        "begin_issuer_name", "end_issuer_name",
        "begin_fair_value", "end_fair_value",
        "match_method", "position_id",
    ],
    "bdc_filings_index": [
        "cik", "entity_name", "form_type", "filing_date", "report_date",
    ],
    "entity_lookup": [
        "entity_id", "canonical_name", "issuer_name_variant", "cusip",
    ],
}


def _affected_outputs(rule: ValidationRule) -> tuple[str, ...]:
    """Return explicit or inferred downstream outputs affected by a rule."""
    if rule.affected_outputs:
        return tuple(dict.fromkeys((*rule.affected_outputs, "data_quality_dashboard")))
    outputs: list[str] = []
    required = set(rule.required_tables)
    if "holdings" in required:
        outputs.extend(["private_markets_holdings", "frontend_fund_detail"])
    if required.intersection({"position_returns", "position_matches"}):
        outputs.extend(["position_returns", "frontend_index"])
    if "index_returns" in required:
        outputs.extend(["index_returns", "frontend_index"])
    outputs.append("data_quality_dashboard")
    return tuple(dict.fromkeys(outputs))


def _affected_outputs_text(rule: ValidationRule) -> str:
    return ";".join(_affected_outputs(rule))


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


def _pc_and_existing_rules() -> list[ValidationRule]:
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
        ValidationRule("PC02", "PC", "Cost-weighted index return reconciles", "FAIL", True, ("position_returns", "index_returns"), pc02_recon, ("RI04",)),
        ValidationRule("PC03", "PC", "Index aggregate fields reconcile", "FAIL", True, ("position_returns", "index_returns"), pc03_recon, ("RI04",)),
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
                WHERE issuer_name IS NOT NULL AND TRY_CAST(fair_value AS DOUBLE) > 0
                GROUP BY cik, report_date, source, issuer, instrument, norm_cusip, fv
                HAVING n > 1
            )
            SELECT {_detail_sql("holding_key", "cik || '|' || report_date || '|' || source || '|' || issuer || '|' || instrument || '|' || norm_cusip || '|' || fv",
            cik="cik", report_date="report_date", issuer="issuer", source="source",
            affected_fv="(n - 1) * fv", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY n DESC, fv DESC, cik)",
            detail="'Same CIK/date/source/issuer/instrument/CUSIP/FV appears multiple times'",
            evidence="'duplicate_count=' || n || ' source=' || source || ' key=' || issuer || '|' || instrument || '|' || norm_cusip || '|' || fv",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("PC07", "PC", "CIK-quarter pct-of-net-assets sum high", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik,
                       LPAD(REGEXP_REPLACE(cik, '[^0-9]', '', 'g'), 10, '0') AS norm_cik,
                       COALESCE(quarter, report_date) AS q,
                       SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) AS pct_sum,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv,
                       COUNT(*) AS n
                FROM holdings GROUP BY cik, norm_cik, q HAVING pct_sum > 250
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fv", hit_rate="pct_sum",
            denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY pct_sum DESC, cik, q)",
            detail="'pct_of_net_assets sums above 250% for CIK-quarter'",
            evidence="'pct_sum=' || ROUND(pct_sum, 2) || ' row_count=' || n || CASE WHEN norm_cik IN ('0001786835', '0001825248', '0001551901') THEN ' Known multi-entity BDC residual pending fund financials population; do not exclude without reconciliation' ELSE ' Likely subtotal leakage or duplicate dimensions' END",
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
            source_file="tbl || '.csv'")} FROM bad""", ("RI04",)),
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
                SELECT *,
                    bfv / NULLIF(SUM(bfv) OVER (PARTITION BY index_classification, end_quarter), 0) AS weight,
                    COUNT(*) OVER (PARTITION BY index_classification, end_quarter) AS n_constituents
                FROM valid
            )
            SELECT {_detail_sql("position", "index_classification || '|' || end_quarter || '|' || COALESCE(position_id, issuer_name)",
            cik="cik", quarter="end_quarter", issuer="issuer_name", position_id="position_id",
            source="source", affected_fv="bfv", hit_rate="weight",
            priority="ROW_NUMBER() OVER (ORDER BY weight DESC, bfv DESC)",
            detail="'Single eligible position exceeds 50% of index-quarter FV'",
            evidence="'Concentration may make index return fragile'",
            source_file="'position_returns.csv'")} FROM g WHERE weight > 0.50 AND n_constituents >= 20"""),
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
        ValidationRule("T01", "T", "CIK position count changes more than 50% QoQ", "WARN", False, ("holdings",),
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
        ValidationRule("T02", "T", "CIK total FV jumps more than 3x or drops more than 70% QoQ", "WARN", False, ("holdings",),
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
        ValidationRule("R07", "R", "Single position FV exceeds fund total assets", "WARN", False, ("holdings", "fund_financials"),
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
        ValidationRule("M02", "M", "Matched-pair begin/end FV ratio extreme", "WARN", False, ("position_returns",),
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



def _temporal_rules() -> list[ValidationRule]:
    """Temporal coherence rules (T03-T10)."""
    return [
        ValidationRule("T03", "T", "Disappearance without exit", "WARN", False, ("holdings",),
            f"""WITH presence AS (
                SELECT cik, position_id, COALESCE(quarter, report_date) AS q,
                       TRY_CAST(fair_value AS DOUBLE) AS fv,
                       COUNT(*) OVER (PARTITION BY cik, position_id) AS appearances
                FROM holdings
                WHERE COALESCE(position_id, '') <> ''
            ), last_seen AS (
                SELECT cik, position_id, MAX(q) AS last_q,
                       MAX(fv) AS last_fv, MAX(appearances) AS apps
                FROM presence GROUP BY cik, position_id
                HAVING apps >= 3
            ), latest_q AS (
                SELECT cik, MAX(COALESCE(quarter, report_date)) AS max_q
                FROM holdings GROUP BY cik
            )
            SELECT {_detail_sql("position", "g.cik || '|' || g.position_id",
            cik="g.cik", quarter="g.last_q", position_id="g.position_id",
            affected_fv="g.last_fv",
            priority="ROW_NUMBER() OVER (ORDER BY g.last_fv DESC, g.cik)",
            detail="'Position present 3+ quarters vanished with last FV > $100K'",
            evidence="'No paydown signal detected; check if exited or extraction gap'",
            source_file="'private_markets_holdings.csv'")}
            FROM last_seen g JOIN latest_q lq ON g.cik = lq.cik
            WHERE g.last_q < lq.max_q AND g.last_fv > 100000"""),
        ValidationRule("T04", "T", "Classification shift", "WARN", False, ("holdings",),
            f"""WITH classified AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, position_id,
                       issuer_name, source, TRY_CAST(fair_value AS DOUBLE) AS fv,
                       index_classification
                FROM holdings
                WHERE COALESCE(position_id, '') <> ''
                  AND COALESCE(index_classification, '') <> ''
            ), paired AS (
                SELECT a.cik, a.q AS q2, b.q AS q1, a.position_id,
                       a.issuer_name, a.source, a.fv,
                       b.index_classification AS prior_classification,
                       a.index_classification AS current_classification
                FROM classified a
                JOIN classified b ON a.cik = b.cik AND a.position_id = b.position_id AND a.q > b.q
                WHERE NOT EXISTS (
                    SELECT 1 FROM classified c
                    WHERE c.cik = a.cik AND c.position_id = a.position_id AND c.q > b.q AND c.q < a.q
                )
            ), flagged AS (
                SELECT cik, q2, q1, COUNT(*) AS total,
                       SUM(CASE WHEN current_classification <> prior_classification THEN 1 ELSE 0 END) AS shifted
                FROM paired
                GROUP BY cik, q2, q1
                HAVING total > 10 AND shifted::DOUBLE / total > 0.15
            ), shifted_positions AS (
                SELECT p.*, f.total, f.shifted, f.shifted::DOUBLE / f.total AS shift_rate
                FROM paired p
                JOIN flagged f ON p.cik = f.cik AND p.q2 = f.q2 AND p.q1 = f.q1
                WHERE p.current_classification <> p.prior_classification
            )
            SELECT {_detail_sql("position", "cik || '|' || q2 || '|' || position_id",
            cik="cik", quarter="q2", issuer="issuer_name", position_id="position_id",
            source="source", affected_fv="fv", denominator="total",
            hit_rate="shift_rate",
            priority="ROW_NUMBER() OVER (ORDER BY shift_rate DESC, fv DESC, cik, q2, position_id)",
            detail="'Position classification changed in CIK-quarter where >15% of matched positions shifted'",
            evidence="'prior_quarter=' || q1 || ' prior_classification=' || prior_classification || ' current_quarter=' || q2 || ' current_classification=' || current_classification || ' shift_rate=' || ROUND(shift_rate * 100, 1) || '%'",
            source_file="'private_markets_holdings.csv'")} FROM shifted_positions"""),
        ValidationRule("T05", "T", "Rate population regression", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN TRY_CAST(interest_rate AS DOUBLE) > 0
                                  OR TRY_CAST(basis_spread AS DOUBLE) > 0 THEN 1 ELSE 0 END) AS has_rate,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                GROUP BY cik, q
                HAVING n >= 10
            ), lagged AS (
                SELECT *, has_rate::DOUBLE / n AS fill,
                       LAG(q) OVER (PARTITION BY cik ORDER BY q) AS prev_q,
                       LAG(n) OVER (PARTITION BY cik ORDER BY q) AS prev_n,
                       LAG(has_rate) OVER (PARTITION BY cik ORDER BY q) AS prev_has_rate,
                       LAG(has_rate::DOUBLE / n) OVER (PARTITION BY cik ORDER BY q) AS prev_fill
                FROM g
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fv", denominator="n", hit_rate="fill",
            priority="ROW_NUMBER() OVER (ORDER BY prev_fill - fill DESC, cik, q)",
            detail="'Rate fill dropped from >80% to <30% in one quarter'",
            evidence="'prior_quarter=' || prev_q || ' prior_fill=' || ROUND(prev_fill * 100, 1) || '% current_fill=' || ROUND(fill * 100, 1) || '% prior_count=' || prev_n || ' current_count=' || n || ' prior_rate_count=' || prev_has_rate || ' current_rate_count=' || has_rate || ' current_direct_lending_fv=' || COALESCE(fv, 0)",
            source_file="'private_markets_holdings.csv'")} FROM lagged
            WHERE prev_fill > 0.8 AND fill < 0.3"""),
        ValidationRule("T06", "T", "New position without origination", "WARN", False, ("holdings",),
            f"""WITH first_seen AS (
                SELECT cik, position_id, MIN(COALESCE(quarter, report_date)) AS first_q,
                       MIN(TRY_CAST(cost AS DOUBLE)) AS first_cost
                FROM holdings
                WHERE COALESCE(position_id, '') <> ''
                GROUP BY cik, position_id
            ), not_first_q AS (
                SELECT cik, MIN(COALESCE(quarter, report_date)) AS min_q
                FROM holdings GROUP BY cik
            )
            SELECT {_detail_sql("position", "g.cik || '|' || g.position_id",
            cik="g.cik", quarter="g.first_q", position_id="g.position_id",
            affected_fv="g.first_cost",
            priority="ROW_NUMBER() OVER (ORDER BY g.first_cost DESC, g.cik)",
            detail="'Position appears for first time with cost > 0 but fund had prior data'",
            evidence="'Expected for new originations; flag for review if unexpected'",
            source_file="'private_markets_holdings.csv'")}
            FROM first_seen g JOIN not_first_q nfq ON g.cik = nfq.cik
            WHERE g.first_q > nfq.min_q AND g.first_cost > 1000000"""),
        ValidationRule("T07", "T", "Maturity cliff", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN TRY_CAST(maturity_date AS DATE) <= TRY_CAST(report_date AS DATE)
                                 AND TRY_CAST(fair_value AS DOUBLE) > 0 THEN 1 ELSE 0 END) AS past_mat,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                  AND maturity_date IS NOT NULL AND maturity_date <> ''
                GROUP BY cik, q
                HAVING n >= 10 AND past_mat::DOUBLE / n > 0.20
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fv", denominator="n",
            hit_rate="past_mat::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY past_mat::DOUBLE / n DESC, cik, q)",
            detail="'More than 20% of positions have maturity_date <= report_date at full FV'",
            evidence="'Past-maturity positions may indicate stale data or extensions'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("T08", "T", "Issuer name drift", "WARN", False, ("position_matches",),
            f"""WITH g AS (
                SELECT *,
                       LENGTH(begin_issuer_name) AS len_b,
                       LENGTH(end_issuer_name) AS len_e,
                       levenshtein(LOWER(begin_issuer_name), LOWER(end_issuer_name)) AS dist
                FROM position_matches
                WHERE begin_issuer_name IS NOT NULL AND end_issuer_name IS NOT NULL
                  AND LENGTH(begin_issuer_name) > 5 AND LENGTH(end_issuer_name) > 5
            )
            SELECT {_detail_sql("position", "cik || '|' || position_id || '|' || end_quarter",
            cik="cik", quarter="end_quarter", position_id="position_id",
            issuer="end_issuer_name",
            hit_rate="dist::DOUBLE / GREATEST(len_b, len_e)",
            priority="ROW_NUMBER() OVER (ORDER BY dist::DOUBLE / GREATEST(len_b, len_e) DESC, cik)",
            detail="'Matched position has large name drift between quarters'",
            evidence="'levenshtein > 40% of name length; possible mismatch'",
            source_file="'position_matches.csv'")} FROM g
            WHERE dist::DOUBLE / GREATEST(len_b, len_e) > 0.4"""),
        ValidationRule("T09", "T", "Sector composition stability", "WARN", False, ("holdings",),
            f"""WITH sector_share AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COALESCE(gics_sub_industry, 'Unknown') AS sector,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS sector_fv,
                       SUM(SUM(TRY_CAST(fair_value AS DOUBLE))) OVER (PARTITION BY cik, COALESCE(quarter, report_date)) AS total_fv
                FROM holdings GROUP BY cik, q, sector
            ), shares AS (
                SELECT *, sector_fv / NULLIF(total_fv, 0) AS share
                FROM sector_share WHERE total_fv > 0
            ), lagged AS (
                SELECT a.cik, a.q, a.sector, a.share,
                       b.share AS prev_share, a.share - b.share AS delta
                FROM shares a
                JOIN shares b ON a.cik = b.cik AND a.sector = b.sector AND a.q > b.q
                WHERE NOT EXISTS (
                    SELECT 1 FROM shares c WHERE c.cik = a.cik AND c.sector = a.sector AND c.q > b.q AND c.q < a.q
                )
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q || '|' || sector",
            cik="cik", quarter="q", hit_rate="ABS(delta)",
            detail="'Top sector share shifted more than 25pp QoQ'",
            evidence="'Sector: ' || sector || '; prior=' || ROUND(prev_share*100,1) || '% now=' || ROUND(share*100,1) || '%'",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(delta) DESC, cik, q)",
            source_file="'private_markets_holdings.csv'")} FROM lagged
            WHERE ABS(delta) > 0.25"""),
        ValidationRule("T10", "T", "Average position size shift", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       MEDIAN(TRY_CAST(fair_value AS DOUBLE)) AS med_fv
                FROM holdings
                WHERE TRY_CAST(fair_value AS DOUBLE) > 0
                GROUP BY cik, q
            ), lagged AS (
                SELECT *, LAG(med_fv) OVER (PARTITION BY cik ORDER BY q) AS prev_med
                FROM g
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="med_fv", denominator="prev_med",
            hit_rate="med_fv / NULLIF(prev_med, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(LOG(med_fv / NULLIF(prev_med, 0))) DESC, cik, q)",
            detail="'Median FV per CIK changed more than 3x QoQ'",
            evidence="'Check extraction completeness or aggregation change'",
            source_file="'private_markets_holdings.csv'")} FROM lagged
            WHERE prev_med > 0 AND (med_fv / prev_med > 3 OR med_fv / prev_med < 0.333)"""),
    ]


def _strategy_rules() -> list[ValidationRule]:
    """Strategy vs holdings rules (S01-S10)."""
    return [
        ValidationRule("S01", "S", "Strategy-classification mismatch", "WARN", False, ("holdings", "combined_universe"),
            f"""WITH fund_class AS (
                SELECT h.cik, COALESCE(h.quarter, h.report_date) AS q,
                       SUM(CASE WHEN h.asset_class = 'REAL_ESTATE' THEN TRY_CAST(h.fair_value AS DOUBLE) ELSE 0 END) AS re_fv,
                       SUM(TRY_CAST(h.fair_value AS DOUBLE)) AS total_fv
                FROM holdings h
                GROUP BY h.cik, q
            ), re_funds AS (
                SELECT u.cik
                FROM combined_universe u
                WHERE LOWER(COALESCE(u.entity_name, '')) LIKE '%real estate%'
                   OR LOWER(COALESCE(u.vehicle_type, '')) LIKE '%real estate%'
            )
            SELECT {_detail_sql("cik_quarter", "fc.cik || '|' || fc.q",
            cik="fc.cik", quarter="fc.q", affected_fv="fc.total_fv",
            hit_rate="fc.re_fv / NULLIF(fc.total_fv, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY fc.re_fv / NULLIF(fc.total_fv, 0) ASC, fc.cik)",
            detail="'Fund with real estate in name has <30% RE classification'",
            evidence="'Strategy label vs actual portfolio composition diverges'",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")}
            FROM fund_class fc JOIN re_funds rf ON fc.cik = rf.cik
            WHERE fc.total_fv > 0 AND fc.re_fv / fc.total_fv < 0.30"""),
        ValidationRule("S02", "S", "BDC equity overweight", "WARN", False, ("holdings", "combined_universe"),
            f"""WITH g AS (
                SELECT h.cik, COALESCE(h.quarter, h.report_date) AS q,
                       SUM(CASE WHEN h.index_classification = 'COMMON_EQUITY' THEN TRY_CAST(h.fair_value AS DOUBLE) ELSE 0 END) AS eq_fv,
                       SUM(TRY_CAST(h.fair_value AS DOUBLE)) AS total_fv
                FROM holdings h
                JOIN combined_universe u ON h.cik = u.cik
                WHERE LOWER(COALESCE(u.vehicle_type, '')) LIKE '%bdc%'
                GROUP BY h.cik, q
                HAVING total_fv > 0 AND eq_fv / total_fv > 0.40
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="eq_fv",
            hit_rate="eq_fv / NULLIF(total_fv, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY eq_fv / NULLIF(total_fv, 0) DESC, cik, q)",
            detail="'BDC with >40% COMMON_EQUITY by FV'",
            evidence="'Unusual for a credit-focused BDC; verify classification'",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")} FROM g"""),
        ValidationRule("S03", "S", "Credit fund with majority fund-of-funds", "WARN", False, ("holdings", "combined_universe"),
            f"""WITH g AS (
                SELECT h.cik, COALESCE(h.quarter, h.report_date) AS q,
                       SUM(CASE WHEN h.index_classification IN ('PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND')
                            THEN TRY_CAST(h.fair_value AS DOUBLE) ELSE 0 END) AS fund_fv,
                       SUM(TRY_CAST(h.fair_value AS DOUBLE)) AS total_fv
                FROM holdings h
                JOIN combined_universe u ON h.cik = u.cik
                WHERE LOWER(COALESCE(u.vehicle_type, '')) LIKE '%bdc%'
                GROUP BY h.cik, q
                HAVING total_fv > 0 AND fund_fv / total_fv > 0.30
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fund_fv",
            hit_rate="fund_fv / NULLIF(total_fv, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY fund_fv / NULLIF(total_fv, 0) DESC, cik, q)",
            detail="'BDC with >30% fund-of-funds exposure'",
            evidence="'Check if this is a holding company or fund-of-funds structure'",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")} FROM g"""),
        ValidationRule("S04", "S", "Sector concentration", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COALESCE(gics_sub_industry, 'Unknown') AS sector,
                       COUNT(*) AS sector_n,
                       SUM(COUNT(*)) OVER (PARTITION BY cik, COALESCE(quarter, report_date)) AS total_n
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                GROUP BY cik, q, sector
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q || '|' || sector",
            cik="cik", quarter="q", hit_rate="sector_n::DOUBLE / total_n",
            priority="ROW_NUMBER() OVER (ORDER BY sector_n::DOUBLE / total_n DESC, cik, q)",
            detail="'Fund with >80% of positions in single GICS sector'",
            evidence="'Sector: ' || sector",
            source_file="'private_markets_holdings.csv'")} FROM g
            WHERE total_n >= 20 AND sector_n::DOUBLE / total_n > 0.80"""),
        ValidationRule("S05", "S", "Vehicle type vs exposure type", "WARN", False, ("holdings", "combined_universe"),
            f"""WITH g AS (
                SELECT h.cik, COALESCE(h.quarter, h.report_date) AS q,
                       SUM(CASE WHEN h.exposure_type = 'LIQUID' THEN TRY_CAST(h.fair_value AS DOUBLE) ELSE 0 END) AS liq_fv,
                       SUM(TRY_CAST(h.fair_value AS DOUBLE)) AS total_fv
                FROM holdings h
                JOIN combined_universe u ON h.cik = u.cik
                WHERE LOWER(COALESCE(u.vehicle_type, '')) LIKE '%bdc%'
                GROUP BY h.cik, q
                HAVING total_fv > 0 AND liq_fv / total_fv > 0.20
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="liq_fv",
            hit_rate="liq_fv / NULLIF(total_fv, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY liq_fv / NULLIF(total_fv, 0) DESC, cik, q)",
            detail="'BDC with >20% LIQUID exposure'",
            evidence="'Check if liquid holdings are correctly classified'",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")} FROM g"""),
        ValidationRule("S06", "S", "Interval fund with majority direct lending", "WARN", False, ("holdings", "combined_universe"),
            f"""WITH g AS (
                SELECT h.cik, COALESCE(h.quarter, h.report_date) AS q,
                       SUM(CASE WHEN h.index_classification = 'DIRECT_LENDING' THEN TRY_CAST(h.fair_value AS DOUBLE) ELSE 0 END) AS dl_fv,
                       SUM(TRY_CAST(h.fair_value AS DOUBLE)) AS total_fv
                FROM holdings h
                JOIN combined_universe u ON h.cik = u.cik
                WHERE LOWER(COALESCE(u.vehicle_type, '')) IN ('interval_fund', 'tender_offer_fund')
                GROUP BY h.cik, q
                HAVING total_fv > 0 AND dl_fv / total_fv > 0.70
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="dl_fv",
            hit_rate="dl_fv / NULLIF(total_fv, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY dl_fv / NULLIF(total_fv, 0) DESC, cik, q)",
            detail="'Interval/tender fund has >70% DIRECT_LENDING'",
            evidence="'Unusual for registered fund; verify classification accuracy'",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")} FROM g"""),
        ValidationRule("S07", "S", "Fund size vs position count sparse", "WARN", False, ("holdings", "fund_financials"),
            f"""WITH h_agg AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, COUNT(*) AS n
                FROM holdings GROUP BY cik, q
            ), ff AS (
                SELECT cik, COALESCE(report_date, quarter) AS d,
                       MAX(TRY_CAST(total_assets AS DOUBLE)) AS ta
                FROM fund_financials GROUP BY cik, d
            )
            SELECT {_detail_sql("cik_quarter", "h.cik || '|' || h.q",
            cik="h.cik", quarter="h.q", affected_fv="ff.ta", denominator="h.n",
            priority="ROW_NUMBER() OVER (ORDER BY ff.ta DESC, h.cik, h.q)",
            detail="'Fund with >$5B total assets but <50 positions'",
            evidence="'May indicate incomplete extraction'",
            source_file="'private_markets_holdings.csv;fund_financials.csv'")}
            FROM h_agg h JOIN ff ON h.cik = ff.cik AND h.q = ff.d
            WHERE ff.ta > 5000000000 AND h.n < 50"""),
        ValidationRule("S08", "S", "Fund size vs position count dense", "WARN", False, ("holdings", "fund_financials"),
            f"""WITH h_agg AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, COUNT(*) AS n
                FROM holdings GROUP BY cik, q
            ), ff AS (
                SELECT cik, COALESCE(report_date, quarter) AS d,
                       MAX(TRY_CAST(total_assets AS DOUBLE)) AS ta
                FROM fund_financials GROUP BY cik, d
            )
            SELECT {_detail_sql("cik_quarter", "h.cik || '|' || h.q",
            cik="h.cik", quarter="h.q", affected_fv="ff.ta", denominator="h.n",
            priority="ROW_NUMBER() OVER (ORDER BY h.n DESC, h.cik, h.q)",
            detail="'Fund with <$100M total assets but >500 positions'",
            evidence="'May indicate consumer lending or granular loan pool'",
            source_file="'private_markets_holdings.csv;fund_financials.csv'")}
            FROM h_agg h JOIN ff ON h.cik = ff.cik AND h.q = ff.d
            WHERE ff.ta < 100000000 AND ff.ta > 0 AND h.n > 500"""),
        ValidationRule("S09", "S", "Tender offer fund with public securities", "WARN", False, ("holdings", "combined_universe"),
            f"""WITH g AS (
                SELECT h.cik, COALESCE(h.quarter, h.report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN COALESCE(h.cusip, '') <> '' THEN 1 ELSE 0 END) AS has_cusip
                FROM holdings h
                JOIN combined_universe u ON h.cik = u.cik
                WHERE LOWER(COALESCE(u.vehicle_type, '')) = 'tender_offer_fund'
                GROUP BY h.cik, q
                HAVING n >= 10 AND has_cusip::DOUBLE / n > 0.50
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", denominator="n",
            hit_rate="has_cusip::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY has_cusip::DOUBLE / n DESC, cik, q)",
            detail="'Tender offer fund has >50% positions with CUSIP'",
            evidence="'High CUSIP density suggests public market exposure'",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")} FROM g"""),
        ValidationRule("S10", "S", "Income fund without rate data", "WARN", False, ("holdings", "combined_universe"),
            f"""WITH g AS (
                SELECT h.cik, COALESCE(h.quarter, h.report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN TRY_CAST(h.interest_rate AS DOUBLE) > 0
                                  OR TRY_CAST(h.basis_spread AS DOUBLE) > 0
                                  OR TRY_CAST(h.pik_rate AS DOUBLE) > 0 THEN 1 ELSE 0 END) AS has_rate
                FROM holdings h
                JOIN combined_universe u ON h.cik = u.cik
                WHERE LOWER(COALESCE(u.vehicle_type, '')) LIKE '%bdc%'
                GROUP BY h.cik, q
                HAVING n >= 10 AND has_rate::DOUBLE / n < 0.50
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", denominator="n",
            hit_rate="has_rate::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY has_rate::DOUBLE / n ASC, cik, q)",
            detail="'BDC has <50% positions with any rate data'",
            evidence="'Income fund should have rate data for income estimation'",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")} FROM g"""),
    ]


def _relational_rules() -> list[ValidationRule]:
    """Relational integrity rules (R01-R06, R08-R15)."""
    return [
        ValidationRule("R01", "R", "Maturity before origination", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv
                FROM holdings
                WHERE TRY_CAST(fair_value AS DOUBLE) > 0
                  AND maturity_date IS NOT NULL AND maturity_date <> ''
                  AND report_date IS NOT NULL
                  AND TRY_CAST(maturity_date AS DATE) < TRY_CAST(report_date AS DATE) - INTERVAL 5 YEAR
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, cik)",
            detail="'maturity_date is more than 5 years before report_date'",
            evidence="'Likely data error in maturity parsing'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R02", "R", "Rate change for fixed coupon", "WARN", False, ("position_matches",),
            f"""WITH g AS (
                SELECT pm.*,
                       TRY_CAST(pm.begin_fair_value AS DOUBLE) AS bfv
                FROM position_matches pm
                WHERE pm.match_method IS NOT NULL
            )
            SELECT {_detail_sql("position", "cik || '|' || position_id || '|' || end_quarter",
            cik="cik", quarter="end_quarter", position_id="position_id",
            affected_fv="bfv",
            priority="ROW_NUMBER() OVER (ORDER BY bfv DESC, cik)",
            detail="'Matched position rate data needs review (placeholder)'",
            evidence="'Rate change detection requires coupon_type in position_matches'",
            source_file="'position_matches.csv'")} FROM g WHERE 1=0"""),
        ValidationRule("R03", "R", "Cost/FV ratio extreme", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS c
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                  AND TRY_CAST(fair_value AS DOUBLE) > 100000
                  AND TRY_CAST(cost AS DOUBLE) > 100000
                  AND (TRY_CAST(cost AS DOUBLE) / TRY_CAST(fair_value AS DOUBLE) > 3
                       OR TRY_CAST(cost AS DOUBLE) / TRY_CAST(fair_value AS DOUBLE) < 0.2)
                  AND LOWER(COALESCE(source, '')) != 'nport'
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            hit_rate="c / fv",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(LOG(c / fv)) DESC, cik)",
            detail="'DIRECT_LENDING cost/FV ratio > 3 or < 0.2 (excludes N-PORT proxy cost)'",
            evidence="'Extreme cost/FV divergence for a loan position'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R04", "R", "Principal on equity", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv,
                       TRY_CAST(principal_amount AS DOUBLE) AS pa
                FROM holdings
                WHERE index_classification = 'COMMON_EQUITY'
                  AND TRY_CAST(principal_amount AS DOUBLE) > 0
                  AND TRY_CAST(fair_value AS DOUBLE) > 0
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            hit_rate="pa",
            priority="ROW_NUMBER() OVER (ORDER BY pa DESC, cik)",
            detail="'COMMON_EQUITY position has principal_amount populated'",
            evidence="'Equity should not have principal; check classification'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R05", "R", "Spread without floating type", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv
                FROM holdings
                WHERE TRY_CAST(basis_spread AS DOUBLE) > 0
                  AND coupon_type IS NOT NULL AND coupon_type <> ''
                  AND LOWER(coupon_type) <> 'floating'
                  AND TRY_CAST(fair_value AS DOUBLE) > 0
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, cik)",
            detail="'basis_spread > 0 but coupon_type is not Floating'",
            evidence="'coupon_type=' || coupon_type",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R06", "R", "Zero rate for credit", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                  AND COALESCE(interest_rate, '') <> '' AND TRY_CAST(interest_rate AS DOUBLE) = 0
                  AND COALESCE(basis_spread, '') <> '' AND TRY_CAST(basis_spread AS DOUBLE) = 0
                  AND COALESCE(pik_rate, '') <> '' AND TRY_CAST(pik_rate AS DOUBLE) = 0
                  AND TRY_CAST(fair_value AS DOUBLE) > 0
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, cik)",
            detail="'DIRECT_LENDING with all rate fields explicitly zero'",
            evidence="'Loan with zero interest unlikely; check rate extraction'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R08", "R", "Negative shares", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv
                FROM holdings
                WHERE TRY_CAST(shares_held AS DOUBLE) < 0
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(TRY_CAST(shares_held AS DOUBLE)) DESC, cik)",
            detail="'shares_held is negative'",
            evidence="'shares=' || shares_held",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R09", "R", "Maturity in distant future", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                  AND maturity_date IS NOT NULL AND maturity_date <> ''
                  AND report_date IS NOT NULL
                  AND TRY_CAST(maturity_date AS DATE) > TRY_CAST(report_date AS DATE) + INTERVAL 30 YEAR
                  AND TRY_CAST(fair_value AS DOUBLE) > 0
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, cik)",
            detail="'Loan maturity_date > 30 years from report_date'",
            evidence="'maturity=' || maturity_date",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R10", "R", "PIK rate exceeds total rate", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv
                FROM holdings
                WHERE TRY_CAST(pik_rate AS DOUBLE) > 0
                  AND TRY_CAST(interest_rate AS DOUBLE) > 0
                  AND TRY_CAST(pik_rate AS DOUBLE) > TRY_CAST(interest_rate AS DOUBLE)
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            hit_rate="TRY_CAST(pik_rate AS DOUBLE)",
            priority="ROW_NUMBER() OVER (ORDER BY TRY_CAST(pik_rate AS DOUBLE) DESC, cik)",
            detail="'PIK rate exceeds total interest rate'",
            evidence="'pik=' || pik_rate || ' rate=' || interest_rate",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R11", "R", "Pct > 25% with many positions", "WARN", False, ("holdings",),
            f"""WITH counts AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, COUNT(*) AS n
                FROM holdings GROUP BY cik, q HAVING n > 100
            ), g AS (
                SELECT h.*, TRY_CAST(h.fair_value AS DOUBLE) AS fv,
                       TRY_CAST(h.pct_of_net_assets AS DOUBLE) AS pct
                FROM holdings h
                JOIN counts c ON h.cik = c.cik AND COALESCE(h.quarter, h.report_date) = c.q
                WHERE TRY_CAST(h.pct_of_net_assets AS DOUBLE) > 25
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            hit_rate="pct",
            priority="ROW_NUMBER() OVER (ORDER BY pct DESC, cik)",
            detail="'pct_of_net_assets > 25% for CIK-quarter with >100 positions'",
            evidence="'Likely scale error in pct_of_net_assets'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R12", "R", "Cost equals FV exactly for bulk", "WARN", False, ("holdings",),
            f"""WITH has_real_cost AS (
                SELECT DISTINCT cik FROM holdings
                WHERE TRY_CAST(cost AS DOUBLE) > 0
                  AND TRY_CAST(cost AS DOUBLE) != TRY_CAST(fair_value AS DOUBLE)
            ), g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN TRY_CAST(cost AS DOUBLE) = TRY_CAST(fair_value AS DOUBLE)
                                 AND TRY_CAST(fair_value AS DOUBLE) > 0 THEN 1 ELSE 0 END) AS exact_match,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE TRY_CAST(fair_value AS DOUBLE) > 0
                  AND cik IN (SELECT cik FROM has_real_cost)
                GROUP BY cik, q
                HAVING n > 10 AND exact_match::DOUBLE / n > 0.9
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="fv", denominator="n",
            hit_rate="exact_match::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY exact_match::DOUBLE / n DESC, cik, q)",
            detail="'CIK-quarter with >90% cost==FV exactly (>10 positions, excludes proxy-only CIKs)'",
            evidence="'May indicate cost proxy fallback or stale marks'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R13", "R", "Duplicate CUSIP within CIK-quarter", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, cusip,
                       COUNT(*) AS n, SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6
                GROUP BY cik, q, cusip
                HAVING n > 3
            )
            SELECT {_detail_sql("cik_quarter_cusip", "cik || '|' || q || '|' || cusip",
            cik="cik", quarter="q", affected_fv="fv", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY n DESC, fv DESC, cik, q)",
            detail="'Same CUSIP appears >3 times in one CIK-quarter'",
            evidence="'CUSIP=' || cusip || ' count=' || n",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R14", "R", "Interest rate exceeds 50%", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv,
                       TRY_CAST(interest_rate AS DOUBLE) AS rate
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                  AND TRY_CAST(interest_rate AS DOUBLE) > 50
                  AND TRY_CAST(fair_value AS DOUBLE) > 0
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            hit_rate="rate",
            priority="ROW_NUMBER() OVER (ORDER BY rate DESC, cik)",
            detail="'DIRECT_LENDING interest_rate > 50 (likely bps vs pct error)'",
            evidence="'rate=' || interest_rate",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("R15", "R", "Principal equals zero for debt", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT *, TRY_CAST(fair_value AS DOUBLE) AS fv
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                  AND COALESCE(principal_amount, '') <> ''
                  AND TRY_CAST(principal_amount AS DOUBLE) = 0
                  AND TRY_CAST(fair_value AS DOUBLE) > 100000
            )
            SELECT {_detail_sql("position", "COALESCE(position_id, cik || '|' || issuer_name || '|' || report_date)",
            cik="cik", quarter="quarter", report_date="report_date", issuer="issuer_name",
            position_id="position_id", source="source", affected_fv="fv",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, cik)",
            detail="'DIRECT_LENDING with principal_amount explicitly = 0'",
            evidence="'Loan with zero principal at >$100K FV is unusual'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
    ]


def _cross_source_rules() -> list[ValidationRule]:
    """Cross-source agreement rules (XS01-XS06)."""
    return [
        ValidationRule("XS01", "XS", "FV divergence", "WARN", False, ("holdings",),
            f"""WITH by_source AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, source,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings GROUP BY cik, q, source
            ), paired AS (
                SELECT a.cik, a.q, a.fv AS bdc_fv, b.fv AS nport_fv
                FROM by_source a
                JOIN by_source b ON a.cik = b.cik AND a.q = b.q
                WHERE LOWER(a.source) = 'bdc' AND LOWER(b.source) = 'nport'
                  AND a.fv > 0 AND b.fv > 0
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", affected_fv="GREATEST(bdc_fv, nport_fv)",
            hit_rate="ABS(bdc_fv - nport_fv) / GREATEST(bdc_fv, nport_fv)",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(bdc_fv - nport_fv) / GREATEST(bdc_fv, nport_fv) DESC, cik, q)",
            detail="'Same CIK-quarter from BDC + N-PORT, total FV differs >20%'",
            evidence="'bdc_fv=' || ROUND(bdc_fv) || ' nport_fv=' || ROUND(nport_fv)",
            source_file="'private_markets_holdings.csv'")} FROM paired
            WHERE ABS(bdc_fv - nport_fv) / GREATEST(bdc_fv, nport_fv) > 0.20"""),
        ValidationRule("XS02", "XS", "Position count divergence", "WARN", False, ("holdings",),
            f"""WITH by_source AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, source, COUNT(*) AS n
                FROM holdings GROUP BY cik, q, source
            ), paired AS (
                SELECT a.cik, a.q, a.n AS bdc_n, b.n AS nport_n
                FROM by_source a
                JOIN by_source b ON a.cik = b.cik AND a.q = b.q
                WHERE LOWER(a.source) = 'bdc' AND LOWER(b.source) = 'nport'
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", denominator="GREATEST(bdc_n, nport_n)",
            hit_rate="ABS(bdc_n - nport_n)::DOUBLE / GREATEST(bdc_n, nport_n)",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(bdc_n - nport_n)::DOUBLE / GREATEST(bdc_n, nport_n) DESC, cik, q)",
            detail="'Same CIK-quarter from both sources, counts differ >30%'",
            evidence="'bdc_n=' || bdc_n || ' nport_n=' || nport_n",
            source_file="'private_markets_holdings.csv'")} FROM paired
            WHERE ABS(bdc_n - nport_n)::DOUBLE / GREATEST(bdc_n, nport_n) > 0.30"""),
        ValidationRule("XS03", "XS", "Classification disagreement", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, cusip,
                       MIN(CASE WHEN LOWER(source) = 'bdc' THEN index_classification END) AS bdc_class,
                       MIN(CASE WHEN LOWER(source) = 'nport' THEN index_classification END) AS nport_class,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6
                GROUP BY cik, q, cusip
                HAVING bdc_class IS NOT NULL AND nport_class IS NOT NULL AND bdc_class <> nport_class
            )
            SELECT {_detail_sql("cusip_quarter", "cik || '|' || q || '|' || cusip",
            cik="cik", quarter="q", affected_fv="fv",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, cik, q)",
            detail="'Same CUSIP from both sources has different classification'",
            evidence="'bdc=' || bdc_class || ' nport=' || nport_class || ' cusip=' || cusip",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("XS04", "XS", "Rate disagreement", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, cusip,
                       MIN(CASE WHEN LOWER(source) = 'bdc' THEN TRY_CAST(interest_rate AS DOUBLE) END) AS bdc_rate,
                       MIN(CASE WHEN LOWER(source) = 'nport' THEN TRY_CAST(interest_rate AS DOUBLE) END) AS nport_rate,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6
                GROUP BY cik, q, cusip
                HAVING bdc_rate IS NOT NULL AND nport_rate IS NOT NULL
                   AND ABS(bdc_rate - nport_rate) > 2
            )
            SELECT {_detail_sql("cusip_quarter", "cik || '|' || q || '|' || cusip",
            cik="cik", quarter="q", affected_fv="fv",
            hit_rate="ABS(bdc_rate - nport_rate)",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(bdc_rate - nport_rate) DESC, cik, q)",
            detail="'Same CUSIP from both sources, interest_rate differs >2pp'",
            evidence="'bdc_rate=' || ROUND(bdc_rate,2) || ' nport_rate=' || ROUND(nport_rate,2) || ' cusip=' || cusip",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("XS05", "XS", "Issuer name disagreement", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, cusip,
                       MIN(CASE WHEN LOWER(source) = 'bdc' THEN issuer_name END) AS bdc_name,
                       MIN(CASE WHEN LOWER(source) = 'nport' THEN issuer_name END) AS nport_name,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6
                  AND issuer_name IS NOT NULL
                GROUP BY cik, q, cusip
                HAVING bdc_name IS NOT NULL AND nport_name IS NOT NULL
                   AND LENGTH(bdc_name) > 3 AND LENGTH(nport_name) > 3
            )
            SELECT {_detail_sql("cusip_quarter", "cik || '|' || q || '|' || cusip",
            cik="cik", quarter="q", affected_fv="fv",
            hit_rate="levenshtein(LOWER(bdc_name), LOWER(nport_name))::DOUBLE / GREATEST(LENGTH(bdc_name), LENGTH(nport_name))",
            priority="ROW_NUMBER() OVER (ORDER BY levenshtein(LOWER(bdc_name), LOWER(nport_name))::DOUBLE / GREATEST(LENGTH(bdc_name), LENGTH(nport_name)) DESC, cik, q)",
            detail="'Same CUSIP from both sources, name levenshtein > 40%'",
            evidence="'bdc=' || bdc_name || ' nport=' || nport_name",
            source_file="'private_markets_holdings.csv'")} FROM g
            WHERE levenshtein(LOWER(bdc_name), LOWER(nport_name))::DOUBLE / GREATEST(LENGTH(bdc_name), LENGTH(nport_name)) > 0.4"""),
        ValidationRule("XS06", "XS", "Maturity disagreement", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, cusip,
                       MIN(CASE WHEN LOWER(source) = 'bdc' THEN TRY_CAST(maturity_date AS DATE) END) AS bdc_mat,
                       MIN(CASE WHEN LOWER(source) = 'nport' THEN TRY_CAST(maturity_date AS DATE) END) AS nport_mat,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6
                  AND maturity_date IS NOT NULL AND maturity_date <> ''
                GROUP BY cik, q, cusip
                HAVING bdc_mat IS NOT NULL AND nport_mat IS NOT NULL
                   AND ABS(DATEDIFF('day', bdc_mat, nport_mat)) > 90
            )
            SELECT {_detail_sql("cusip_quarter", "cik || '|' || q || '|' || cusip",
            cik="cik", quarter="q", affected_fv="fv",
            hit_rate="ABS(DATEDIFF('day', bdc_mat, nport_mat))",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(DATEDIFF('day', bdc_mat, nport_mat)) DESC, cik, q)",
            detail="'Same CUSIP from both sources, maturity differs >90 days'",
            evidence="'bdc_mat=' || bdc_mat || ' nport_mat=' || nport_mat || ' cusip=' || cusip",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
    ]


def _idx_new_rules() -> list[ValidationRule]:
    """New index-level rules (IDX10-IDX15)."""
    return [
        ValidationRule("IDX10", "IDX", "Constituent count QoQ stability", "WARN", False, ("index_returns",),
            f"""WITH lagged AS (
                SELECT *,
                       TRY_CAST(constituent_count AS DOUBLE) AS cnt,
                       LAG(TRY_CAST(constituent_count AS DOUBLE)) OVER (PARTITION BY index_classification ORDER BY quarter) AS prev_cnt
                FROM index_returns
            )
            SELECT {_detail_sql("index_quarter", "index_classification || '|' || quarter",
            quarter="quarter", affected_fv="TRY_CAST(total_begin_fv AS DOUBLE)",
            hit_rate="(prev_cnt - cnt) / NULLIF(prev_cnt, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY (prev_cnt - cnt) / NULLIF(prev_cnt, 0) DESC, index_classification, quarter)",
            detail="'Constituent count dropped >20% QoQ'",
            evidence="'prev=' || CAST(prev_cnt AS INT) || ' curr=' || CAST(cnt AS INT)",
            source_file="'index_returns.csv'")} FROM lagged
            WHERE prev_cnt > 0 AND (prev_cnt - cnt) / prev_cnt > 0.20"""),
        ValidationRule("IDX11", "IDX", "Index coverage gap", "WARN", False, ("index_returns",),
            f"""WITH lagged AS (
                SELECT *,
                       TRY_CAST(total_begin_fv AS DOUBLE) AS bfv,
                       LAG(TRY_CAST(total_end_fv AS DOUBLE)) OVER (PARTITION BY index_classification ORDER BY quarter) AS prev_end_fv
                FROM index_returns
            )
            SELECT {_detail_sql("index_quarter", "index_classification || '|' || quarter",
            quarter="quarter", affected_fv="bfv",
            hit_rate="bfv / NULLIF(prev_end_fv, 0)",
            priority="ROW_NUMBER() OVER (ORDER BY bfv / NULLIF(prev_end_fv, 0) ASC, index_classification, quarter)",
            detail="'total_begin_fv < 80% of prior quarter total_end_fv'",
            evidence="'Coverage gap suggests missing constituents'",
            source_file="'index_returns.csv'")} FROM lagged
            WHERE prev_end_fv > 0 AND bfv / prev_end_fv < 0.80"""),
        ValidationRule("IDX12", "IDX", "Vehicle type dominance shift", "WARN", False, ("position_returns", "combined_universe"),
            f"""WITH pr_vt AS (
                SELECT pr.index_classification, pr.end_quarter AS quarter,
                       COALESCE(u.vehicle_type, 'unknown') AS vtype,
                       SUM(TRY_CAST(pr.begin_fair_value AS DOUBLE)) AS vt_fv,
                       SUM(SUM(TRY_CAST(pr.begin_fair_value AS DOUBLE))) OVER (PARTITION BY pr.index_classification, pr.end_quarter) AS total_fv
                FROM position_returns pr
                LEFT JOIN combined_universe u ON pr.cik = u.cik
                WHERE TRY_CAST(pr.begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
                GROUP BY pr.index_classification, pr.end_quarter, vtype
            ), shares AS (
                SELECT *, vt_fv / NULLIF(total_fv, 0) AS share
                FROM pr_vt WHERE total_fv > 0
            ), lagged AS (
                SELECT *,
                       LAG(share) OVER (PARTITION BY index_classification, vtype ORDER BY quarter) AS prev_share
                FROM shares
            )
            SELECT {_detail_sql("index_quarter", "index_classification || '|' || quarter || '|' || vtype",
            quarter="quarter", hit_rate="share",
            priority="ROW_NUMBER() OVER (ORDER BY share - COALESCE(prev_share, 0) DESC, index_classification, quarter)",
            detail="'Single vehicle_type went from <50% to >80% of index FV'",
            evidence="'vtype=' || vtype || ' prev=' || ROUND(COALESCE(prev_share,0)*100,1) || '% now=' || ROUND(share*100,1) || '%'",
            source_file="'position_returns.csv;combined_universe.csv'")} FROM lagged
            WHERE COALESCE(prev_share, 0) < 0.50 AND share > 0.80"""),
        ValidationRule("IDX13", "IDX", "Return dispersion", "WARN", False, ("position_returns",),
            f"""WITH g AS (
                SELECT index_classification, end_quarter AS quarter,
                       STDDEV_POP(TRY_CAST(quarterly_total_return AS DOUBLE)) AS ret_std,
                       COUNT(*) AS n,
                       SUM(TRY_CAST(begin_fair_value AS DOUBLE)) AS fv
                FROM position_returns
                WHERE TRY_CAST(quarterly_total_return AS DOUBLE) IS NOT NULL
                  AND COALESCE(index_classification, '') NOT IN ('', 'UNCLASSIFIED')
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
                GROUP BY index_classification, end_quarter
                HAVING n >= {MIN_CONSTITUENTS} AND ret_std > 1.0
            )
            SELECT {_detail_sql("index_quarter", "index_classification || '|' || quarter",
            quarter="quarter", affected_fv="fv", denominator="n",
            hit_rate="ret_std",
            priority="ROW_NUMBER() OVER (ORDER BY ret_std DESC, index_classification, quarter)",
            detail="'Cross-sectional std dev of quarterly returns > 100%'",
            evidence="'Extreme dispersion may indicate data quality issues'",
            source_file="'position_returns.csv'")} FROM g"""),
        ValidationRule("IDX14", "IDX", "Index vs fund NAV return", "WARN", False, ("index_returns", "fund_financials", "position_returns"),
            f"""WITH idx AS (
                SELECT index_classification, quarter,
                       TRY_CAST(fv_weighted_return AS DOUBLE) AS idx_ret
                FROM index_returns
            ), fund_ret AS (
                SELECT ff.cik, ff.quarter,
                       (TRY_CAST(ff.total_assets AS DOUBLE) - LAG(TRY_CAST(ff.total_assets AS DOUBLE)) OVER (PARTITION BY ff.cik ORDER BY ff.quarter))
                       / NULLIF(LAG(TRY_CAST(ff.total_assets AS DOUBLE)) OVER (PARTITION BY ff.cik ORDER BY ff.quarter), 0) AS nav_ret
                FROM fund_financials ff
            ), cik_idx AS (
                SELECT DISTINCT cik, index_classification
                FROM position_returns
                WHERE COALESCE(index_classification, '') NOT IN ('', 'UNCLASSIFIED')
            ), avg_fund AS (
                SELECT ci.index_classification, fr.quarter,
                       AVG(fr.nav_ret) AS avg_nav_ret
                FROM fund_ret fr
                JOIN cik_idx ci ON fr.cik = ci.cik
                WHERE fr.nav_ret IS NOT NULL
                GROUP BY ci.index_classification, fr.quarter
                HAVING COUNT(*) >= 3
            )
            SELECT {_detail_sql("index_quarter", "i.index_classification || '|' || i.quarter",
            quarter="i.quarter", hit_rate="ABS(i.idx_ret - af.avg_nav_ret)",
            priority="ROW_NUMBER() OVER (ORDER BY ABS(i.idx_ret - af.avg_nav_ret) DESC, i.index_classification, i.quarter)",
            detail="'Index return diverges >500bps from weighted avg fund return'",
            evidence="'idx=' || ROUND(i.idx_ret*100,2) || '% fund_avg=' || ROUND(af.avg_nav_ret*100,2) || '%'",
            source_file="'index_returns.csv;fund_financials.csv'")}
            FROM idx i JOIN avg_fund af ON i.index_classification = af.index_classification AND i.quarter = af.quarter
            WHERE ABS(i.idx_ret - af.avg_nav_ret) > 0.05"""),
        ValidationRule("IDX15", "IDX", "Negative income return for direct lending", "WARN", False, ("position_returns",),
            f"""WITH g AS (
                SELECT end_quarter AS quarter,
                       SUM(TRY_CAST(income_return AS DOUBLE) * TRY_CAST(begin_fair_value AS DOUBLE))
                       / NULLIF(SUM(TRY_CAST(begin_fair_value AS DOUBLE)), 0) AS wt_income,
                       SUM(TRY_CAST(begin_fair_value AS DOUBLE)) AS fv
                FROM position_returns
                WHERE index_classification = 'DIRECT_LENDING'
                  AND TRY_CAST(quarterly_total_return AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(begin_fair_value AS DOUBLE) >= {MIN_BEGIN_FV}
                GROUP BY end_quarter
                HAVING COUNT(*) >= {MIN_CONSTITUENTS} AND wt_income < 0
            )
            SELECT {_detail_sql("index_quarter", "'DIRECT_LENDING|' || quarter",
            quarter="quarter", affected_fv="fv", hit_rate="wt_income",
            priority="ROW_NUMBER() OVER (ORDER BY wt_income ASC, quarter)",
            detail="'DIRECT_LENDING index-quarter has negative weighted income return'",
            evidence="'Credit index should have positive income'",
            source_file="'position_returns.csv'")} FROM g"""),
    ]


def _freshness_rules() -> list[ValidationRule]:
    """Freshness and completeness rules (F01-F10)."""
    return [
        ValidationRule("F01", "F", "Missing quarter", "WARN", False, ("holdings",),
            f"""WITH cik_quarters AS (
                SELECT DISTINCT cik, COALESCE(quarter, report_date) AS q
                FROM holdings
            ), all_q AS (
                SELECT DISTINCT COALESCE(quarter, report_date) AS q FROM holdings
            ), expected AS (
                SELECT c.cik, a.q
                FROM (SELECT DISTINCT cik FROM cik_quarters) c
                CROSS JOIN all_q a
            ), present AS (
                SELECT cik, q, 1 AS has_data FROM cik_quarters
            ), gaps AS (
                SELECT e.cik, e.q, p.has_data,
                       LAG(p.has_data) OVER (PARTITION BY e.cik ORDER BY e.q) AS prev_has,
                       LEAD(p.has_data) OVER (PARTITION BY e.cik ORDER BY e.q) AS next_has
                FROM expected e
                LEFT JOIN present p ON e.cik = p.cik AND e.q = p.q
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q",
            priority="ROW_NUMBER() OVER (ORDER BY cik, q)",
            detail="'CIK present in adjacent quarters but absent in between'",
            evidence="'Missing data point in time series'",
            source_file="'private_markets_holdings.csv'")} FROM gaps
            WHERE has_data IS NULL AND prev_has = 1 AND next_has = 1"""),
        ValidationRule("F02", "F", "Stale filing", "WARN", False, ("holdings", "combined_universe"),
            f"""WITH latest AS (
                SELECT cik, MAX(COALESCE(quarter, report_date)) AS last_q
                FROM holdings GROUP BY cik
            ), distinct_q AS (
                SELECT DISTINCT COALESCE(quarter, report_date) AS q FROM holdings
            ), stale_cutoff AS (
                SELECT q AS cutoff_q FROM distinct_q ORDER BY q DESC LIMIT 1 OFFSET 2
            ), max_q AS (
                SELECT MAX(COALESCE(quarter, report_date)) AS global_max FROM holdings
            ), universe AS (
                SELECT cik, MAX(COALESCE(status, '')) AS status
                FROM combined_universe GROUP BY cik
            )
            SELECT {_detail_sql("cik", "l.cik",
            cik="l.cik", quarter="l.last_q",
            priority="ROW_NUMBER() OVER (ORDER BY l.last_q ASC, l.cik)",
            detail="'CIK last data is >2 quarters old'",
            evidence="'last_q=' || l.last_q || ' stale_cutoff=' || sc.cutoff_q || ' global_max=' || m.global_max",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")}
            FROM latest l CROSS JOIN max_q m
            CROSS JOIN stale_cutoff sc
            JOIN universe u ON l.cik = u.cik
            WHERE l.last_q < sc.cutoff_q
              AND LOWER(COALESCE(u.status, '')) NOT IN ('withdrawn', 'inactive')"""),
        ValidationRule("F03", "F", "Source coverage drop", "WARN", False, ("holdings",),
            f"""WITH normalized AS (
                SELECT source,
                       CASE
                           WHEN REGEXP_MATCHES(LOWER(COALESCE(quarter, report_date)), '^[0-9]{{4}}q[1-4]$')
                               THEN LOWER(COALESCE(quarter, report_date))
                           WHEN TRY_CAST(COALESCE(report_date, quarter) AS DATE) IS NOT NULL
                               THEN CAST(YEAR(TRY_CAST(COALESCE(report_date, quarter) AS DATE)) AS VARCHAR) || 'q' || CAST(QUARTER(TRY_CAST(COALESCE(report_date, quarter) AS DATE)) AS VARCHAR)
                           ELSE LOWER(COALESCE(quarter, report_date))
                       END AS q,
                       cik
                FROM holdings
            ), q_counts AS (
                SELECT source, q, COUNT(DISTINCT cik) AS n_ciks
                FROM normalized GROUP BY source, q
            ), stats AS (
                SELECT *, MAX(n_ciks) OVER (PARTITION BY source) AS max_ciks
                FROM q_counts
            )
            SELECT {_detail_sql("source_quarter", "source || '|' || q",
            quarter="q", source="source", denominator="max_ciks", hit_rate="n_ciks::DOUBLE / max_ciks",
            priority="ROW_NUMBER() OVER (ORDER BY n_ciks::DOUBLE / max_ciks ASC, source, q)",
            detail="'Source-quarter CIK count < 80% of source historical max'",
            evidence="'source=' || source || ' n_ciks=' || n_ciks || ' source_max=' || max_ciks",
            source_file="'private_markets_holdings.csv'")} FROM stats
            WHERE n_ciks::DOUBLE / max_ciks < 0.80"""),
        ValidationRule("F04", "F", "N-PORT quarterly gap", "WARN", False, ("holdings",),
            f"""WITH nport_q AS (
                SELECT DISTINCT cik, COALESCE(quarter, report_date) AS q
                FROM holdings WHERE LOWER(source) = 'nport'
            ), all_nport_q AS (
                SELECT DISTINCT q FROM nport_q
            ), expected AS (
                SELECT c.cik, a.q
                FROM (SELECT DISTINCT cik FROM nport_q) c CROSS JOIN all_nport_q a
            ), present AS (
                SELECT cik, q, 1 AS has_data FROM nport_q
            ), gaps AS (
                SELECT e.cik, e.q, p.has_data,
                       LAG(p.has_data) OVER (PARTITION BY e.cik ORDER BY e.q) AS prev_has,
                       LEAD(p.has_data) OVER (PARTITION BY e.cik ORDER BY e.q) AS next_has
                FROM expected e
                LEFT JOIN present p ON e.cik = p.cik AND e.q = p.q
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q",
            priority="ROW_NUMBER() OVER (ORDER BY cik, q)",
            detail="'N-PORT CIK present in adjacent quarters but absent in between'",
            evidence="'Quarterly filing gap for N-PORT filer'",
            source_file="'private_markets_holdings.csv'")} FROM gaps
            WHERE has_data IS NULL AND prev_has = 1 AND next_has = 1"""),
        ValidationRule("F05", "F", "BDC filing gap", "WARN", False, ("bdc_filings_index",),
            f"""WITH filings AS (
                SELECT cik, report_date,
                       UPPER(COALESCE(form_type, '')) AS ft
                FROM bdc_filings_index
                WHERE form_type IS NOT NULL
            ), annual AS (
                SELECT DISTINCT cik, LEFT(report_date, 4) AS yr
                FROM filings WHERE ft LIKE '%10-K%'
            ), quarterly AS (
                SELECT DISTINCT cik, report_date
                FROM filings WHERE ft LIKE '%10-Q%'
            ), expected AS (
                SELECT a.cik, a.yr
                FROM annual a
            )
            SELECT {_detail_sql("cik_year", "e.cik || '|' || e.yr",
            cik="e.cik", quarter="e.yr",
            priority="ROW_NUMBER() OVER (ORDER BY e.cik, e.yr)",
            detail="'BDC has 10-K but fewer than 2 10-Qs in same year'",
            evidence="'Check filing completeness'",
            source_file="'bdc_filings_index.csv'")}
            FROM expected e
            WHERE (SELECT COUNT(*) FROM quarterly q WHERE q.cik = e.cik AND LEFT(q.report_date, 4) = e.yr) < 2"""),
        ValidationRule("F06", "F", "Fund financials coverage", "WARN", False, ("holdings", "fund_financials", "combined_universe"),
            f"""WITH h_ciks AS (
                SELECT DISTINCT cik FROM holdings
            ), ff_ciks AS (
                SELECT DISTINCT cik FROM fund_financials
            )
            SELECT {_detail_sql("cik", "h.cik",
            cik="h.cik",
            priority="ROW_NUMBER() OVER (ORDER BY COALESCE(u.vehicle_type, 'ZZZ'), h.cik)",
            detail="'CIK in holdings but missing from fund_financials (vehicle_type=' || COALESCE(u.vehicle_type, 'unknown') || ')'",
            evidence="CASE WHEN COALESCE(u.vehicle_type, '') = 'BDC' THEN 'BDC should have companyfacts data - investigate'"
                     " ELSE 'N-PORT-only filer - structural gap (no companyfacts)' END",
            source_file="'private_markets_holdings.csv;fund_financials.csv'")}
            FROM h_ciks h
            LEFT JOIN ff_ciks ff ON h.cik = ff.cik
            LEFT JOIN combined_universe u ON h.cik = u.cik
            WHERE ff.cik IS NULL"""),
        ValidationRule("F07", "F", "GICS coverage", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT COALESCE(quarter, report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN COALESCE(gics_sub_industry, '') = '' THEN 1 ELSE 0 END) AS missing
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                GROUP BY q
                HAVING n > 100 AND missing::DOUBLE / n > 0.10
            )
            SELECT {_detail_sql("quarter", "q",
            quarter="q", denominator="n", hit_rate="missing::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY missing::DOUBLE / n DESC, q)",
            detail="'More than 10% of DIRECT_LENDING positions lack gics_sub_industry'",
            evidence="'GICS classification coverage gap'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("F08", "F", "Entity resolution coverage", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT COALESCE(quarter, report_date) AS q, source,
                       COUNT(*) AS n,
                       SUM(CASE WHEN COALESCE(entity_id, '') = '' THEN 1 ELSE 0 END) AS missing,
                       SUM(CASE WHEN COALESCE(entity_id, '') = '' THEN TRY_CAST(fair_value AS DOUBLE) ELSE 0 END) AS missing_fv
                FROM holdings GROUP BY q, source
                HAVING n > 100 AND missing::DOUBLE / n > 0.05
            )
            SELECT {_detail_sql("source_quarter", "source || '|' || q",
            quarter="q", source="source", affected_fv="missing_fv", denominator="n", hit_rate="missing::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY missing::DOUBLE / n DESC, source, q)",
            detail="'More than 5% of source-quarter positions lack entity_id'",
            evidence="'source=' || source || ' missing_count=' || missing || ' total_rows=' || n",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("F09", "F", "Position ID coverage", "WARN", False, ("holdings",),
            f"""WITH multi_q AS (
                SELECT cik, COUNT(DISTINCT COALESCE(quarter, report_date)) AS n_q
                FROM holdings GROUP BY cik HAVING n_q > 1
            ), g AS (
                SELECT h.cik,
                       COUNT(*) AS n,
                       SUM(CASE WHEN COALESCE(h.position_id, '') = '' THEN 1 ELSE 0 END) AS missing
                FROM holdings h
                JOIN multi_q m ON h.cik = m.cik
                GROUP BY h.cik
                HAVING n > 20 AND missing::DOUBLE / n > 0.25
            )
            SELECT {_detail_sql("cik", "cik",
            cik="cik", denominator="n", hit_rate="missing::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY missing::DOUBLE / n DESC, cik)",
            detail="'More than 25% of multi-quarter CIK positions lack position_id'",
            evidence="'Position matching under-coverage'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("F10", "F", "New CIK without history", "WARN", False, ("holdings",),
            f"""WITH latest_q AS (
                SELECT MAX(COALESCE(quarter, report_date)) AS max_q FROM holdings
            ), cik_first AS (
                SELECT cik, MIN(COALESCE(quarter, report_date)) AS first_q,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
                FROM holdings GROUP BY cik
            )
            SELECT {_detail_sql("cik", "cf.cik",
            cik="cf.cik", quarter="cf.first_q", affected_fv="cf.total_fv",
            priority="ROW_NUMBER() OVER (ORDER BY cf.total_fv DESC, cf.cik)",
            detail="'CIK appears for first time in latest quarter with >$100M FV'",
            evidence="'New entrant needs review for data quality'",
            source_file="'private_markets_holdings.csv'")}
            FROM cik_first cf CROSS JOIN latest_q lq
            WHERE cf.first_q = lq.max_q AND cf.total_fv > 100000000"""),
    ]


def _matching_rules() -> list[ValidationRule]:
    """Matching quality rules (M01, M03-M10)."""
    return [
        ValidationRule("M01", "M", "CUSIP collision", "WARN", False, ("holdings",),
            f"""WITH cusip_names AS (
                SELECT cusip, issuer_name, SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6
                  AND issuer_name IS NOT NULL AND LENGTH(issuer_name) > 3
                GROUP BY cusip, issuer_name
            ), multi_name_cusips AS (
                SELECT cusip FROM cusip_names GROUP BY cusip
                HAVING COUNT(*) BETWEEN 2 AND 10
            ), filtered AS (
                SELECT cn.* FROM cusip_names cn
                JOIN multi_name_cusips mc ON cn.cusip = mc.cusip
            ), pairs AS (
                SELECT a.cusip, a.issuer_name AS name_a, b.issuer_name AS name_b,
                       a.fv + b.fv AS total_fv,
                       levenshtein(LOWER(a.issuer_name), LOWER(b.issuer_name)) AS dist,
                       GREATEST(LENGTH(a.issuer_name), LENGTH(b.issuer_name)) AS max_len
                FROM filtered a
                JOIN filtered b ON a.cusip = b.cusip AND a.issuer_name < b.issuer_name
            )
            SELECT {_detail_sql("cusip", "cusip",
            affected_fv="total_fv",
            hit_rate="dist::DOUBLE / max_len",
            priority="ROW_NUMBER() OVER (ORDER BY dist::DOUBLE / max_len DESC, cusip)",
            detail="'Same CUSIP maps to names with levenshtein > 50% of length'",
            evidence="'a=' || name_a || ' b=' || name_b",
            source_file="'private_markets_holdings.csv'")} FROM pairs
            WHERE dist::DOUBLE / max_len > 0.5"""),
        ValidationRule("M03", "M", "1:many match over cap", "WARN", False, ("position_matches",),
            f"""WITH g AS (
                SELECT position_id, COUNT(*) AS n,
                       SUM(TRY_CAST(begin_fair_value AS DOUBLE)) AS fv
                FROM position_matches
                WHERE COALESCE(position_id, '') <> ''
                GROUP BY position_id
                HAVING n > 3
            )
            SELECT {_detail_sql("position", "position_id",
            position_id="position_id", affected_fv="fv", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY n DESC, fv DESC)",
            detail="'Position matched to >3 others'",
            evidence="'Possible over-matching or chain contamination'",
            source_file="'position_matches.csv'")} FROM g"""),
        ValidationRule("M04", "M", "Identifier parse failure", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN issuer_name IS NOT NULL
                                 AND instrument_description IS NOT NULL
                                 AND issuer_name = instrument_description THEN 1 ELSE 0 END) AS unparsed
                FROM holdings
                WHERE LOWER(source) = 'bdc'
                GROUP BY cik, q
                HAVING n >= 10 AND unparsed::DOUBLE / n > 0.20
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", denominator="n",
            hit_rate="unparsed::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY unparsed::DOUBLE / n DESC, cik, q)",
            detail="'More than 20% of BDC positions have issuer_name == instrument_description'",
            evidence="'Identifier parsing may have failed for this CIK'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("M05", "M", "Entity resolution fragmentation", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cusip, COUNT(DISTINCT entity_id) AS n_entities,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6
                  AND COALESCE(entity_id, '') <> ''
                GROUP BY cusip
                HAVING n_entities > 3
            )
            SELECT {_detail_sql("cusip", "cusip",
            affected_fv="fv", denominator="n_entities",
            priority="ROW_NUMBER() OVER (ORDER BY n_entities DESC, fv DESC)",
            detail="'Same CUSIP has >3 distinct entity_ids'",
            evidence="'Entity resolution may be fragmenting a single issuer'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("M06", "M", "Instrument description empty", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN COALESCE(instrument_description, '') = '' THEN 1 ELSE 0 END) AS missing
                FROM holdings
                WHERE index_classification = 'DIRECT_LENDING'
                GROUP BY cik, q
                HAVING n >= 10 AND missing::DOUBLE / n > 0.50
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", denominator="n",
            hit_rate="missing::DOUBLE / n",
            priority="ROW_NUMBER() OVER (ORDER BY missing::DOUBLE / n DESC, cik, q)",
            detail="'More than 50% of DIRECT_LENDING positions lack instrument_description'",
            evidence="'Missing tranche/security type information'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("M07", "M", "CUSIP coverage drop", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q,
                       COUNT(*) AS n,
                       SUM(CASE WHEN COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6 THEN 1 ELSE 0 END) AS has_cusip
                FROM holdings GROUP BY cik, q HAVING n >= 10
            ), lagged AS (
                SELECT *, has_cusip::DOUBLE / n AS fill,
                       LAG(has_cusip::DOUBLE / n) OVER (PARTITION BY cik ORDER BY q) AS prev_fill
                FROM g
            )
            SELECT {_detail_sql("cik_quarter", "cik || '|' || q",
            cik="cik", quarter="q", denominator="n", hit_rate="fill",
            priority="ROW_NUMBER() OVER (ORDER BY prev_fill - fill DESC, cik, q)",
            detail="'CUSIP fill dropped from >60% to <20% QoQ'",
            evidence="'prev_fill=' || ROUND(prev_fill*100,1) || '% now=' || ROUND(fill*100,1) || '%'",
            source_file="'private_markets_holdings.csv'")} FROM lagged
            WHERE prev_fill > 0.6 AND fill < 0.2"""),
        ValidationRule("M08", "M", "Position ID chain break", "WARN", False, ("holdings",),
            f"""WITH pid_q AS (
                SELECT DISTINCT cik, position_id, COALESCE(quarter, report_date) AS q
                FROM holdings
                WHERE COALESCE(position_id, '') <> ''
            ), cik_q AS (
                SELECT DISTINCT cik, COALESCE(quarter, report_date) AS q FROM holdings
            ), expected AS (
                SELECT p.cik, p.position_id, cq.q
                FROM (SELECT DISTINCT cik, position_id FROM pid_q) p
                JOIN cik_q cq ON p.cik = cq.cik
            ), presence AS (
                SELECT e.cik, e.position_id, e.q,
                       CASE WHEN pq.q IS NOT NULL THEN 1 END AS has_data,
                       LAG(CASE WHEN pq.q IS NOT NULL THEN 1 END) OVER (PARTITION BY e.cik, e.position_id ORDER BY e.q) AS prev_has,
                       LEAD(CASE WHEN pq.q IS NOT NULL THEN 1 END) OVER (PARTITION BY e.cik, e.position_id ORDER BY e.q) AS next_has
                FROM expected e
                LEFT JOIN pid_q pq ON e.cik = pq.cik AND e.position_id = pq.position_id AND e.q = pq.q
            )
            SELECT {_detail_sql("position_quarter", "cik || '|' || position_id || '|' || q",
            cik="cik", quarter="q", position_id="position_id",
            priority="ROW_NUMBER() OVER (ORDER BY cik, position_id, q)",
            detail="'position_id present in Q-1 and Q+1 but not Q'",
            evidence="'Chain break in position time series'",
            source_file="'private_markets_holdings.csv'")} FROM presence
            WHERE has_data IS NULL AND prev_has = 1 AND next_has = 1"""),
        ValidationRule("M09", "M", "Duplicate entity_id for different issuers", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT cik, COALESCE(quarter, report_date) AS q, entity_id,
                       COUNT(DISTINCT LOWER(TRIM(issuer_name))) AS n_names,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(entity_id, '') <> ''
                  AND issuer_name IS NOT NULL
                GROUP BY cik, q, entity_id
                HAVING n_names > 1
            )
            SELECT {_detail_sql("cik_quarter_entity", "cik || '|' || q || '|' || entity_id",
            cik="cik", quarter="q", affected_fv="fv", denominator="n_names",
            priority="ROW_NUMBER() OVER (ORDER BY n_names DESC, fv DESC, cik, q)",
            detail="'Two distinct issuer_names share entity_id within CIK-quarter'",
            evidence="'entity_id=' || entity_id",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("M10", "M", "Name normalization collision", "WARN", False, ("holdings",),
            f"""WITH g AS (
                SELECT LOWER(TRIM(issuer_name)) AS norm_name,
                       COUNT(DISTINCT cusip) AS n_cusips,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings
                WHERE COALESCE(cusip, '') <> '' AND LENGTH(cusip) >= 6
                  AND issuer_name IS NOT NULL AND LENGTH(issuer_name) > 3
                GROUP BY norm_name
                HAVING n_cusips > 2
            )
            SELECT {_detail_sql("issuer", "norm_name",
            issuer="norm_name", affected_fv="fv", denominator="n_cusips",
            priority="ROW_NUMBER() OVER (ORDER BY n_cusips DESC, fv DESC)",
            detail="'Same normalized issuer_name maps to >2 distinct CUSIPs'",
            evidence="'May indicate different tranches or normalization collision'",
            source_file="'private_markets_holdings.csv'")} FROM g"""),
    ]


def _referential_integrity_rules() -> list[ValidationRule]:
    """Source and artifact referential-integrity rules (RI01-RI06)."""
    norm_cik = "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')"
    hq = "COALESCE(NULLIF(quarter, ''), CASE WHEN TRY_CAST(report_date AS DATE) IS NOT NULL THEN CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR) || 'q' || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) ELSE report_date END)"
    ffq = "COALESCE(NULLIF(report_quarter, ''), NULLIF(quarter, ''), CASE WHEN TRY_CAST(report_date AS DATE) IS NOT NULL THEN CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR) || 'q' || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) ELSE report_date END)"
    return [
        ValidationRule("RI01", "RI", "Holdings CIKs exist in combined universe", "FAIL", True, ("holdings", "combined_universe"),
            f"""WITH h AS (
                SELECT {norm_cik} AS norm_cik, COUNT(*) AS n,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
                FROM holdings GROUP BY norm_cik
            ), u AS (
                SELECT DISTINCT {norm_cik} AS norm_cik FROM combined_universe
            ), g AS (
                SELECT h.* FROM h LEFT JOIN u USING (norm_cik) WHERE u.norm_cik IS NULL
            )
            SELECT {_detail_sql("cik", "norm_cik", cik="norm_cik",
            affected_fv="fv", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY fv DESC, norm_cik)",
            detail="'Holdings CIK is absent from combined_universe'",
            evidence="'Normalize CIK to 10 digits before comparing'",
            source_file="'private_markets_holdings.csv;combined_universe.csv'")} FROM g"""),
        ValidationRule("RI02", "RI", "Position matches CIKs exist in holdings", "FAIL", True, ("position_matches", "holdings"),
            f"""WITH m AS (
                SELECT {norm_cik} AS norm_cik, COUNT(*) AS n
                FROM position_matches GROUP BY norm_cik
            ), h AS (
                SELECT DISTINCT {norm_cik} AS norm_cik FROM holdings
            ), g AS (
                SELECT m.* FROM m LEFT JOIN h USING (norm_cik) WHERE h.norm_cik IS NULL
            )
            SELECT {_detail_sql("cik", "norm_cik", cik="norm_cik",
            denominator="n", priority="ROW_NUMBER() OVER (ORDER BY n DESC, norm_cik)",
            detail="'position_matches CIK is absent from holdings'",
            evidence="'Position matching should be downstream of unified holdings'",
            source_file="'position_matches.csv;private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("RI03", "RI", "Cross-level financial CIK-quarters exist in fund financials", "FAIL", True, ("fund_financials_cross_level", "fund_financials"),
            f"""WITH x AS (
                SELECT {norm_cik} AS norm_cik, {ffq} AS q, COUNT(*) AS n
                FROM fund_financials_cross_level GROUP BY norm_cik, q
            ), f AS (
                SELECT DISTINCT {norm_cik} AS norm_cik, {ffq} AS q
                FROM fund_financials
            ), g AS (
                SELECT x.* FROM x LEFT JOIN f USING (norm_cik, q) WHERE f.norm_cik IS NULL
            )
            SELECT {_detail_sql("cik_quarter", "norm_cik || '|' || q",
            cik="norm_cik", quarter="q", denominator="n",
            priority="ROW_NUMBER() OVER (ORDER BY n DESC, norm_cik, q)",
            detail="'fund_financials_cross_level CIK-quarter is absent from fund_financials'",
            evidence="'Cross-level diagnostics must reference an existing fund financial row'",
            source_file="'fund_financials_cross_level.csv;fund_financials.csv'")} FROM g"""),
        ValidationRule("RI04", "RI", "Index return quarters fall within holdings quarter range", "FAIL", True, ("index_returns", "holdings"),
            f"""WITH h_range AS (
                SELECT MIN({hq}) AS min_q, MAX({hq}) AS max_q FROM holdings
            ), g AS (
                SELECT i.*, h.min_q, h.max_q
                FROM index_returns i CROSS JOIN h_range h
                WHERE COALESCE(i.quarter, '') <> ''
                  AND (h.min_q IS NULL OR i.quarter < h.min_q OR i.quarter > h.max_q)
            )
            SELECT {_detail_sql("index_quarter", "index_classification || '|' || quarter",
            quarter="quarter", hit_rate="0",
            priority="ROW_NUMBER() OVER (ORDER BY quarter, index_classification)",
            detail="'index_returns quarter falls outside holdings quarter range'",
            evidence="'holdings_range=' || COALESCE(min_q, '') || '..' || COALESCE(max_q, '')",
            source_file="'index_returns.csv;private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("RI05", "RI", "Fee uplift CIKs exist in holdings", "FAIL", True, ("fee_uplift", "holdings"),
            f"""WITH fu AS (
                SELECT {norm_cik} AS norm_cik, COUNT(*) AS n
                FROM fee_uplift GROUP BY norm_cik
            ), h AS (
                SELECT DISTINCT {norm_cik} AS norm_cik FROM holdings
            ), g AS (
                SELECT fu.* FROM fu LEFT JOIN h USING (norm_cik) WHERE h.norm_cik IS NULL
            )
            SELECT {_detail_sql("cik", "norm_cik", cik="norm_cik",
            denominator="n", priority="ROW_NUMBER() OVER (ORDER BY n DESC, norm_cik)",
            detail="'fee_uplift CIK is absent from holdings'",
            evidence="'Fee uplift should only exist for funds with holdings'",
            source_file="'fee_uplift.csv;private_markets_holdings.csv'")} FROM g"""),
        ValidationRule("RI06", "RI", "Index-used BDC income CIKs exist in BDC holdings", "FAIL", True, ("bdc_fund_income", "bdc_holdings", "fee_uplift"),
            f"""WITH index_used_income AS (
                SELECT DISTINCT fi.*
                FROM bdc_fund_income fi
                JOIN fee_uplift fu
                  ON {norm_cik.replace('cik', 'fi.cik')} = {norm_cik.replace('cik', 'fu.cik')}
            ), fi AS (
                SELECT {norm_cik} AS norm_cik, COUNT(*) AS n
                FROM index_used_income GROUP BY norm_cik
            ), bh AS (
                SELECT DISTINCT {norm_cik} AS norm_cik FROM bdc_holdings
            ), g AS (
                SELECT fi.* FROM fi LEFT JOIN bh USING (norm_cik) WHERE bh.norm_cik IS NULL
            )
            SELECT {_detail_sql("cik", "norm_cik", cik="norm_cik",
            denominator="n", priority="ROW_NUMBER() OVER (ORDER BY n DESC, norm_cik)",
            detail="'index-used bdc_fund_income CIK is absent from bdc_holdings'",
            evidence="'RI06 is scoped to income CIKs used by fee_uplift; RI05 covers fee_uplift CIKs absent from unified holdings'",
            source_file="'bdc_fund_income.csv;fee_uplift.csv;bdc_holdings.csv'")} FROM g"""),
    ]



def _rules() -> list[ValidationRule]:
    """Combine all rule categories."""
    return (
        _referential_integrity_rules()
        +
        _pc_and_existing_rules()
        + _temporal_rules()
        + _strategy_rules()
        + _relational_rules()
        + _cross_source_rules()
        + _idx_new_rules()
        + _freshness_rules()
        + _matching_rules()
    )


RULE_REGISTRY = {rule.rule_id: rule for rule in _rules()}
DEFAULT_CATEGORIES = ("PC", "IDX", "T", "S", "R", "XS", "F", "M", "RI")


def _empty_detail() -> pd.DataFrame:
    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _load_tables(
    con: duckdb.DuckDBPyConnection,
    rules: Iterable[ValidationRule],
    table_paths: dict[str, str | Path] | None,
) -> dict[str, str]:
    paths = {**TABLE_PATHS, **(table_paths or {})}
    needed = {
        table
        for rule in rules
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
                '{csv_path}', header=true, all_varchar=true, ignore_errors=true
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


def _select_rules(categories: set[str]) -> list[ValidationRule]:
    """Return category-selected rules plus transitive dependencies in stable order."""
    selected_ids = {
        rule.rule_id for rule in RULE_REGISTRY.values() if rule.category in categories
    }
    stack = list(selected_ids)
    while stack:
        rule_id = stack.pop()
        rule = RULE_REGISTRY.get(rule_id)
        if rule is None:
            raise ValueError(f"Unknown validation rule dependency: {rule_id}")
        for dep in rule.depends_on:
            if dep not in RULE_REGISTRY:
                raise ValueError(f"Unknown validation rule dependency: {rule_id} -> {dep}")
            if dep not in selected_ids:
                selected_ids.add(dep)
                stack.append(dep)
    return _topological_order(selected_ids)


def _topological_order(rule_ids: set[str]) -> list[ValidationRule]:
    order_index = {rule_id: i for i, rule_id in enumerate(RULE_REGISTRY)}
    visiting: set[str] = set()
    visited: set[str] = set()
    ordered: list[str] = []

    def visit(rule_id: str) -> None:
        if rule_id in visited:
            return
        if rule_id in visiting:
            cycle = " -> ".join(list(visiting) + [rule_id])
            raise ValueError(f"Validation rule dependency cycle detected: {cycle}")
        visiting.add(rule_id)
        rule = RULE_REGISTRY[rule_id]
        for dep in sorted(rule.depends_on, key=lambda value: order_index[value]):
            if dep in rule_ids:
                visit(dep)
        visiting.remove(rule_id)
        visited.add(rule_id)
        ordered.append(rule_id)

    for rule_id in sorted(rule_ids, key=lambda value: order_index[value]):
        visit(rule_id)
    return [RULE_REGISTRY[rule_id] for rule_id in ordered]


def _write_history(aggregate_df: pd.DataFrame) -> None:
    history_path = config.VALIDATION_RULES_HISTORY_FILE
    history_cols = [
        "rule_id", "category", "run_id", "run_timestamp", "status",
        "hit_count", "hit_rate", "affected_fair_value",
    ]
    history_path.parent.mkdir(parents=True, exist_ok=True)
    header = not history_path.exists()
    aggregate_df.loc[:, history_cols].to_csv(
        history_path,
        mode="a",
        header=header,
        index=False,
    )


def _read_history(path: str | Path | None = None) -> pd.DataFrame:
    history_path = Path(path or config.VALIDATION_RULES_HISTORY_FILE)
    if not history_path.exists():
        return pd.DataFrame()
    return pd.read_csv(history_path, dtype=str)


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
        "affected_outputs": _affected_outputs_text(rule),
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
        "affected_outputs": _affected_outputs_text(rule),
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
    selected = {c.upper() for c in (categories or DEFAULT_CATEGORIES)}
    selected_rules = _select_rules(selected)
    run_id = run_id or uuid4().hex[:12]
    ts = datetime.now(timezone.utc).isoformat()

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    missing = _load_tables(con, selected_rules, table_paths)

    aggregate_rows = []
    detail_frames = []
    status_by_rule: dict[str, str] = {}
    for rule in selected_rules:
        failed_deps = [
            dep for dep in rule.depends_on
            if status_by_rule.get(dep) == "FAIL"
        ]
        if failed_deps:
            aggregate = _skip_row(
                rule,
                run_id,
                ts,
                "failed dependency: " + ", ".join(failed_deps),
            )
            aggregate_rows.append(aggregate)
            status_by_rule[rule.rule_id] = aggregate["status"]
            continue
        missing_for_rule = [missing[t] for t in rule.required_tables if t in missing]
        if missing_for_rule:
            aggregate = _skip_row(rule, run_id, ts, "; ".join(missing_for_rule))
            aggregate_rows.append(aggregate)
            status_by_rule[rule.rule_id] = aggregate["status"]
            continue
        try:
            aggregate, detail = _run_rule(con, rule, run_id, ts)
        except Exception as exc:
            aggregate = _skip_row(rule, run_id, ts, f"execution error: {exc}")
            aggregate_rows.append(aggregate)
            status_by_rule[rule.rule_id] = aggregate["status"]
            logger.exception("Validation rule %s failed", rule.rule_id)
            continue
        aggregate_rows.append(aggregate)
        status_by_rule[rule.rule_id] = aggregate["status"]
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
        trend_path = config.VALIDATION_RULES_TREND_FILE
        prior_history_df = _read_history()
        aggregate_path.parent.mkdir(parents=True, exist_ok=True)
        aggregate_df.to_csv(aggregate_path, index=False)
        detail_df.to_csv(detail_path, index=False)
        _write_history(aggregate_df)
        from pipeline.validation_rules.trend import compute_trends
        trend_df = compute_trends(prior_history_df, aggregate_df)
        trend_path.parent.mkdir(parents=True, exist_ok=True)
        trend_df.to_csv(trend_path, index=False)
        logger.info("Wrote validation rules aggregate: %s (%d rows)", aggregate_path, len(aggregate_df))
        logger.info("Wrote validation rules detail: %s (%d rows)", detail_path, len(detail_df))
        logger.info("Wrote validation rules trend: %s (%d rows)", trend_path, len(trend_df))

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
    "DEFAULT_CATEGORIES",
    "DETAIL_COLUMNS",
    "RULE_REGISTRY",
    "ValidationRule",
    "_affected_outputs",
    "_select_rules",
    "_topological_order",
    "run_all",
    "run_category",
]
