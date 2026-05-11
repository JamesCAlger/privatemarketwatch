"""Column-level data quality validation for unified holdings.

This module produces standardized issue, metric, and CIK-quarter summary
artifacts for ``private_markets_holdings.csv``. It intentionally does not
mutate holdings data or enforce downstream gating; it only reports quality
signals in a common schema.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

DATASET = "private_markets_holdings"

SEVERITY_FAIL = "FAIL"
SEVERITY_WARN = "WARN"
SEVERITY_INFO = "INFO"

EVIDENCE_STRONG = "STRONG"
EVIDENCE_MODERATE = "MODERATE"
EVIDENCE_WEAK = "WEAK"

STATUS_OPEN = "OPEN"
ACTION_BLOCK_VERIFIED = "BLOCK_VERIFIED"
ACTION_EXCLUDE_FROM_INDEX = "EXCLUDE_FROM_INDEX"
ACTION_REVIEW = "REVIEW"
ACTION_DISCLOSE = "DISCLOSE"
ACTION_TRACK_ONLY = "TRACK_ONLY"

GAV_BDC_FAIL_RULE = "GAV_BDC01"
GAV_BDC_WARN_RULE = "GAV_BDC02"
GAV_NPORT_SCOPE_RULE = "GAV_NPORT01"

ISSUE_COLUMNS = [
    "dataset", "source", "cik", "report_date", "row_key", "column",
    "rule_id", "severity", "evidence_strength", "status", "action",
    "value", "message", "evidence",
]

METRIC_COLUMNS = [
    "dataset", "source", "cik", "quarter", "column", "total_rows",
    "filled_count", "parseable_count", "valid_count", "fill_rate",
    "parse_rate", "valid_rate", "fail_count", "warn_count",
]

SUMMARY_COLUMNS = [
    "dataset", "source", "cik", "report_date", "quarter", "row_count",
    "validation_tier", "fail_count", "warn_count", "info_count",
    "strong_issue_count", "moderate_issue_count", "weak_issue_count",
]

REQUIRED_COLUMNS = [
    "source", "cik", "accession_number", "filing_date", "report_date",
    "entity_name", "issuer_name", "instrument_description", "cusip", "isin",
    "entity_id", "bdc_investment_identifier", "fair_value", "cost",
    "principal_amount", "interest_rate", "basis_spread", "pik_rate",
    "shares_held", "index_classification", "asset_category",
    "issuer_category", "exposure_type", "asset_class", "coupon_type",
    "maturity_date", "pct_of_net_assets", "reference_rate_type",
    "gics_sub_industry", "nport_asset_cat", "nport_issuer_type",
]

NUMERIC_COLUMNS = {
    "fair_value", "cost", "principal_amount", "interest_rate",
    "basis_spread", "pik_rate", "shares_held", "pct_of_net_assets",
}

DATE_COLUMNS = {"filing_date", "report_date", "maturity_date"}

ENUM_VALUES = {
    "source": {"bdc", "nport", "html"},
    "exposure_type": {"DIRECT", "FUND", "LIQUID"},
    "asset_class": {
        "PRIVATE_CREDIT", "PRIVATE_EQUITY", "REAL_ESTATE",
        "STRUCTURED_CREDIT", "HEDGE_FUND", "CASH", "OTHER",
    },
    "index_classification": {
        "DIRECT_LENDING", "COMMON_EQUITY", "PREFERRED_EQUITY",
        "PRIVATE_CREDIT_FUND", "PRIVATE_EQUITY_FUND", "REAL_ESTATE_FUND",
        "DIRECT_REAL_ESTATE", "STRUCTURED_CREDIT", "HEDGE_FUND", "CASH",
        "UNCLASSIFIED",
    },
    "coupon_type": {"Fixed", "Floating", "Variable"},
}


def _empty_issues() -> pd.DataFrame:
    return pd.DataFrame(columns=ISSUE_COLUMNS)


def _empty_metrics() -> pd.DataFrame:
    return pd.DataFrame(columns=METRIC_COLUMNS)


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=SUMMARY_COLUMNS)


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with all columns referenced by validation SQL present."""
    prepared = df.copy()
    for col in REQUIRED_COLUMNS:
        if col not in prepared.columns:
            prepared[col] = ""
    prepared["_row_key"] = range(len(prepared))
    return prepared


def _quarter_sql(date_col: str = "report_date") -> str:
    return f"""
        CASE WHEN TRY_CAST({date_col} AS DATE) IS NOT NULL THEN
            CAST(YEAR(TRY_CAST({date_col} AS DATE)) AS VARCHAR)
            || 'q'
            || CAST(QUARTER(TRY_CAST({date_col} AS DATE)) AS VARCHAR)
        ELSE ''
        END
    """


def _blank_sql(col: str) -> str:
    return f"TRIM(COALESCE(CAST({col} AS VARCHAR), '')) = ''"


def _value_sql(col: str) -> str:
    return f"COALESCE(CAST({col} AS VARCHAR), '')"


def _issue_query(
    column: str,
    rule_id: str,
    severity: str,
    evidence_strength: str,
    action: str,
    condition: str,
    message: str,
    evidence: str,
    value_expr: Optional[str] = None,
) -> str:
    value = value_expr or _value_sql(column)
    esc_message = message.replace("'", "''")
    esc_evidence = evidence.replace("'", "''")
    return f"""
        SELECT
            '{DATASET}' AS dataset,
            {_value_sql('source')} AS source,
            {_value_sql('cik')} AS cik,
            {_value_sql('report_date')} AS report_date,
            CAST(_row_key AS VARCHAR) AS row_key,
            '{column}' AS column,
            '{rule_id}' AS rule_id,
            '{severity}' AS severity,
            '{evidence_strength}' AS evidence_strength,
            '{STATUS_OPEN}' AS status,
            '{action}' AS action,
            CAST({value} AS VARCHAR) AS value,
            '{esc_message}' AS message,
            '{esc_evidence}' AS evidence
        FROM h
        WHERE {condition}
    """


def validate_column_contracts(
    unified_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run column and cross-column validation on unified holdings.

    Returns ``(issues, metrics)``. Both outputs use stable schemas even when
    no issues are found.
    """
    if unified_df.empty:
        return _empty_issues(), _empty_metrics()

    df = _prepare_df(unified_df)
    con = duckdb.connect()
    con.register("h", df)

    issue_queries = [
        # Tier 0 identity and lineage
        _issue_query(
            "source", "C001", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            f"{_blank_sql('source')} OR lower(TRIM(CAST(source AS VARCHAR))) "
            "NOT IN ('bdc', 'nport', 'html')",
            "source must be one of bdc, nport, html",
            "source drives source-specific validation",
        ),
        _issue_query(
            "cik", "C002", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            f"{_blank_sql('cik')} OR regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g') = ''",
            "cik is missing or cannot be normalized to digits",
            "cik is required for grouping and source reconciliation",
        ),
        _issue_query(
            "report_date", "C004", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            f"{_blank_sql('report_date')} OR TRY_CAST(report_date AS DATE) IS NULL",
            "report_date is missing or unparseable",
            "report_date is the CIK-quarter key",
        ),
        _issue_query(
            "report_date", "C005", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(report_date AS DATE) > CURRENT_DATE",
            "report_date is in the future",
            "future report dates are usually data errors",
        ),
        _issue_query(
            "accession_number", "C006", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            "lower(TRIM(CAST(source AS VARCHAR))) IN ('bdc', 'html') "
            f"AND {_blank_sql('accession_number')}",
            "filing-derived BDC/HTML row is missing accession_number",
            "accession_number is required for source traceability",
        ),
        _issue_query(
            "filing_date", "C007", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('filing_date')} AND TRY_CAST(filing_date AS DATE) IS NULL",
            "filing_date is present but unparseable",
            "filing_date should parse when present",
        ),
        _issue_query(
            "entity_name", "C008", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            _blank_sql("entity_name"),
            "entity_name is missing",
            "entity_name is required for public display and diagnostics",
        ),

        # Tier 1 numeric/index inputs
        _issue_query(
            "fair_value", "C101", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_EXCLUDE_FROM_INDEX,
            f"{_blank_sql('fair_value')} "
            "AND COALESCE(index_classification, '') NOT IN ('', 'UNCLASSIFIED')",
            "fair_value is missing on an indexable row",
            "index returns and public FV aggregations require fair_value",
        ),
        _issue_query(
            "fair_value", "C102", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_EXCLUDE_FROM_INDEX,
            f"NOT {_blank_sql('fair_value')} AND TRY_CAST(fair_value AS DOUBLE) IS NULL",
            "fair_value is present but unparseable",
            "numeric fair_value is required when present",
        ),
        _issue_query(
            "fair_value", "C103", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(fair_value AS DOUBLE) < 0",
            "fair_value is negative",
            "negative fair_value can be legitimate but needs review",
        ),
        _issue_query(
            "fair_value", "C104", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(fair_value AS DOUBLE) = 0",
            "fair_value is zero",
            "zero fair_value may be legitimate but affects aggregation and returns",
        ),
        _issue_query(
            "fair_value", "C105", SEVERITY_WARN, EVIDENCE_WEAK,
            ACTION_REVIEW,
            "TRY_CAST(fair_value AS DOUBLE) > 3000000000",
            "fair_value exceeds $3B",
            "large positions can be legitimate but are high-impact outliers",
        ),
        _issue_query(
            "cost", "C106", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('cost')} AND TRY_CAST(cost AS DOUBLE) IS NULL",
            "cost is present but unparseable",
            "numeric cost is required when present",
        ),
        _issue_query(
            "cost", "C107", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(cost AS DOUBLE) < 0",
            "cost is negative",
            "negative cost can be legitimate but should be monitored",
        ),
        _issue_query(
            "principal_amount", "C109", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('principal_amount')} AND TRY_CAST(principal_amount AS DOUBLE) IS NULL",
            "principal_amount is present but unparseable",
            "numeric principal_amount is required when present",
        ),
        _issue_query(
            "principal_amount", "X06", SEVERITY_FAIL, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(fair_value AS DOUBLE) > 0 "
            "AND TRY_CAST(principal_amount AS DOUBLE) > 10 * TRY_CAST(fair_value AS DOUBLE)",
            "principal_amount is more than 10x fair_value",
            "likely scale error; can corrupt income and return analytics",
        ),
        _issue_query(
            "principal_amount", "C110", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(principal_amount AS DOUBLE) < 0",
            "principal_amount is negative",
            "negative principal is unusual",
        ),
        _issue_query(
            "interest_rate", "C112", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('interest_rate')} AND TRY_CAST(interest_rate AS DOUBLE) IS NULL",
            "interest_rate is present but unparseable",
            "numeric interest_rate is required when present",
        ),
        _issue_query(
            "interest_rate", "C113", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(interest_rate AS DOUBLE) > 25 OR TRY_CAST(interest_rate AS DOUBLE) < 0",
            "interest_rate is outside the expected percentage range",
            "rates are stored as whole-number percentages",
        ),
        _issue_query(
            "basis_spread", "C114", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('basis_spread')} AND TRY_CAST(basis_spread AS DOUBLE) IS NULL",
            "basis_spread is present but unparseable",
            "numeric basis_spread is required when present",
        ),
        _issue_query(
            "basis_spread", "C115", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(basis_spread AS DOUBLE) > 15 OR TRY_CAST(basis_spread AS DOUBLE) < 0",
            "basis_spread is outside the expected percentage range",
            "spreads are stored as whole-number percentages",
        ),
        _issue_query(
            "pik_rate", "C116", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('pik_rate')} AND TRY_CAST(pik_rate AS DOUBLE) IS NULL",
            "pik_rate is present but unparseable",
            "numeric pik_rate is required when present",
        ),
        _issue_query(
            "pik_rate", "C117", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(pik_rate AS DOUBLE) > 20 OR TRY_CAST(pik_rate AS DOUBLE) < 0",
            "pik_rate is outside the expected percentage range",
            "PIK rates above 20% are high-impact outliers",
        ),
        _issue_query(
            "shares_held", "C118", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('shares_held')} AND TRY_CAST(shares_held AS DOUBLE) IS NULL",
            "shares_held is present but unparseable",
            "numeric shares_held is required when present",
        ),
        _issue_query(
            "shares_held", "C119", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(shares_held AS DOUBLE) < 0",
            "shares_held is negative",
            "negative share counts can be valid short or derivative representation",
        ),

        # Tier 2 identity/matching inputs
        _issue_query(
            "issuer_name", "C201", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            _blank_sql("issuer_name"),
            "issuer_name is missing",
            "issuer_name is required for position identity and display",
        ),
        _issue_query(
            "issuer_name", "C202", SEVERITY_WARN, EVIDENCE_WEAK,
            ACTION_REVIEW,
            "length(TRIM(CAST(issuer_name AS VARCHAR))) < 3 "
            f"AND NOT {_blank_sql('issuer_name')}",
            "issuer_name is shorter than 3 characters",
            "very short issuer names are usually parsing artifacts",
        ),
        _issue_query(
            "issuer_name", "C203", SEVERITY_WARN, EVIDENCE_WEAK,
            ACTION_REVIEW,
            "length(TRIM(CAST(issuer_name AS VARCHAR))) > 300",
            "issuer_name is unusually long",
            "long issuer names may be full dimension strings",
        ),
        _issue_query(
            "cusip", "C204", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('cusip')} AND length(TRIM(CAST(cusip AS VARCHAR))) != 9",
            "CUSIP is present but not 9 characters",
            "CUSIP format should be 9 characters",
        ),
        _issue_query(
            "isin", "C205", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('isin')} AND length(TRIM(CAST(isin AS VARCHAR))) != 12",
            "ISIN is present but not 12 characters",
            "ISIN format should be 12 characters",
        ),
        _issue_query(
            "bdc_investment_identifier", "C207", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            "lower(TRIM(CAST(source AS VARCHAR))) = 'bdc' "
            f"AND {_blank_sql('bdc_investment_identifier')}",
            "BDC row is missing bdc_investment_identifier",
            "raw BDC source identifier must be preserved",
        ),

        # Tier 3 classifications
        _issue_query(
            "index_classification", "C301", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            f"{_blank_sql('index_classification')} OR index_classification NOT IN "
            "('DIRECT_LENDING','COMMON_EQUITY','PREFERRED_EQUITY',"
            "'PRIVATE_CREDIT_FUND','PRIVATE_EQUITY_FUND','REAL_ESTATE_FUND',"
            "'DIRECT_REAL_ESTATE','STRUCTURED_CREDIT','HEDGE_FUND','CASH',"
            "'UNCLASSIFIED')",
            "index_classification is missing or unknown",
            "index_classification drives public index assignment",
        ),
        _issue_query(
            "exposure_type", "C303", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            f"{_blank_sql('exposure_type')} OR exposure_type NOT IN ('DIRECT','FUND','LIQUID')",
            "exposure_type is missing or unknown",
            "exposure_type is a controlled classification axis",
        ),
        _issue_query(
            "asset_class", "C304", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_BLOCK_VERIFIED,
            f"{_blank_sql('asset_class')} OR asset_class NOT IN "
            "('PRIVATE_CREDIT','PRIVATE_EQUITY','REAL_ESTATE',"
            "'STRUCTURED_CREDIT','HEDGE_FUND','CASH','OTHER')",
            "asset_class is missing or unknown",
            "asset_class is a controlled classification axis",
        ),
        _issue_query(
            "coupon_type", "C306", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('coupon_type')} AND coupon_type NOT IN ('Fixed','Floating','Variable')",
            "coupon_type is unknown",
            "coupon_type must be a controlled value when present",
        ),

        # Tier 4 display fields
        _issue_query(
            "maturity_date", "C401", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            f"NOT {_blank_sql('maturity_date')} "
            "AND maturity_date != '9999-12-31' "
            "AND TRY_CAST(maturity_date AS DATE) IS NULL",
            "maturity_date is present but unparseable",
            "maturity_date should parse unless it is a known sentinel",
        ),
        _issue_query(
            "maturity_date", "C402", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            "TRY_CAST(maturity_date AS DATE) IS NOT NULL "
            "AND YEAR(TRY_CAST(maturity_date AS DATE)) < 1900 "
            "AND (asset_category IN ('LOAN', 'DEBT') OR asset_class = 'PRIVATE_CREDIT')",
            "maturity_date year is before 1900",
            "pre-1900 debt maturity years are parsing errors",
        ),
        _issue_query(
            "maturity_date", "C403", SEVERITY_INFO, EVIDENCE_STRONG,
            ACTION_DISCLOSE,
            "maturity_date = '9999-12-31'",
            "maturity_date uses perpetual/no-maturity sentinel",
            "9999-12-31 is treated as a display sentinel",
        ),
        _issue_query(
            "maturity_date", "X10", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(maturity_date AS DATE) IS NOT NULL "
            "AND TRY_CAST(report_date AS DATE) IS NOT NULL "
            "AND maturity_date != '9999-12-31' "
            "AND TRY_CAST(maturity_date AS DATE) < TRY_CAST(report_date AS DATE)",
            "maturity_date is before report_date",
            "matured positions can still be reported but need monitoring",
        ),
        _issue_query(
            "pct_of_net_assets", "X09", SEVERITY_FAIL, EVIDENCE_MODERATE,
            ACTION_BLOCK_VERIFIED,
            "TRY_CAST(pct_of_net_assets AS DOUBLE) > 100.0",
            "pct_of_net_assets exceeds 100 percentage points",
            "usually a dimension-path duplication or denominator artifact",
        ),
        _issue_query(
            "pct_of_net_assets", "C404", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "TRY_CAST(pct_of_net_assets AS DOUBLE) < 0",
            "pct_of_net_assets is negative",
            "negative pct_of_net_assets can be legitimate but should be monitored",
        ),

        # Cross-column semantic rules
        _issue_query(
            "interest_rate", "X01", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "asset_class = 'PRIVATE_EQUITY' AND TRY_CAST(interest_rate AS DOUBLE) > 0",
            "PRIVATE_EQUITY row has interest_rate",
            "likely convertible note or classification mismatch",
        ),
        _issue_query(
            "interest_rate", "X02", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "asset_class = 'PRIVATE_CREDIT' "
            f"AND {_blank_sql('interest_rate')} "
            f"AND {_blank_sql('basis_spread')}",
            "PRIVATE_CREDIT row has no interest_rate or basis_spread",
            "missing rate data affects income return computation",
        ),
        _issue_query(
            "maturity_date", "X03", SEVERITY_INFO, EVIDENCE_WEAK,
            ACTION_TRACK_ONLY,
            "exposure_type = 'FUND' "
            f"AND NOT {_blank_sql('maturity_date')}",
            "FUND exposure has maturity_date",
            "unusual but low-risk unless other checks fail",
        ),
        _issue_query(
            "basis_spread", "X04", SEVERITY_FAIL, EVIDENCE_STRONG,
            ACTION_REVIEW,
            "coupon_type = 'Fixed' AND TRY_CAST(basis_spread AS DOUBLE) > 0",
            "Fixed coupon row has basis_spread",
            "fixed-rate instruments should not have floating spread",
        ),
        _issue_query(
            "basis_spread", "X05", SEVERITY_WARN, EVIDENCE_MODERATE,
            ACTION_REVIEW,
            "coupon_type = 'Floating' "
            "AND (TRY_CAST(basis_spread AS DOUBLE) IS NULL "
            "OR TRY_CAST(basis_spread AS DOUBLE) = 0)",
            "Floating coupon row has missing or zero basis_spread",
            "all-in rate or source omission can explain this gap",
        ),
        _issue_query(
            "cost", "X07", SEVERITY_WARN, EVIDENCE_WEAK,
            ACTION_REVIEW,
            "TRY_CAST(fair_value AS DOUBLE) > 0 AND TRY_CAST(cost AS DOUBLE) > 0 "
            "AND TRY_CAST(fair_value AS DOUBLE) / TRY_CAST(cost AS DOUBLE) > 10",
            "fair_value exceeds 10x cost",
            "extreme appreciation or data error",
        ),
        _issue_query(
            "cost", "X08", SEVERITY_WARN, EVIDENCE_WEAK,
            ACTION_REVIEW,
            "TRY_CAST(fair_value AS DOUBLE) > 0 AND TRY_CAST(cost AS DOUBLE) > 0 "
            "AND TRY_CAST(fair_value AS DOUBLE) / TRY_CAST(cost AS DOUBLE) < 0.05",
            "fair_value is below 5% of cost",
            "severely distressed position or data error",
        ),
    ]

    issues = con.execute("\nUNION ALL\n".join(issue_queries)).fetchdf()
    if issues.empty:
        issues = _empty_issues()

    metrics = _build_column_metrics(con, issues)
    con.close()
    return issues[ISSUE_COLUMNS], metrics[METRIC_COLUMNS]


def _build_column_metrics(
    con: duckdb.DuckDBPyConnection,
    issues: pd.DataFrame,
) -> pd.DataFrame:
    metric_columns = [
        "source", "cik", "accession_number", "filing_date", "report_date",
        "entity_name", "issuer_name", "instrument_description", "cusip", "isin",
        "entity_id", "bdc_investment_identifier", "fair_value", "cost",
        "principal_amount", "interest_rate", "basis_spread", "pik_rate",
        "shares_held", "index_classification", "asset_category",
        "issuer_category", "exposure_type", "asset_class", "coupon_type",
        "maturity_date", "pct_of_net_assets", "reference_rate_type",
        "gics_sub_industry",
    ]

    parts = []
    quarter_expr = _quarter_sql("report_date")
    for col in metric_columns:
        blank = _blank_sql(col)
        if col in NUMERIC_COLUMNS:
            parseable = f"TRY_CAST({col} AS DOUBLE) IS NOT NULL"
        elif col in DATE_COLUMNS:
            if col == "maturity_date":
                parseable = f"TRY_CAST({col} AS DATE) IS NOT NULL OR {col} = '9999-12-31'"
            else:
                parseable = f"TRY_CAST({col} AS DATE) IS NOT NULL"
        elif col in ENUM_VALUES:
            allowed = ", ".join(f"'{v}'" for v in sorted(ENUM_VALUES[col]))
            if col == "source":
                parseable = f"lower(TRIM(CAST({col} AS VARCHAR))) IN ({allowed})"
            else:
                parseable = f"{col} IN ({allowed})"
        else:
            parseable = f"NOT {blank}"

        sql = f"""
        SELECT
            '{DATASET}' AS dataset,
            {_value_sql('source')} AS source,
            {_value_sql('cik')} AS cik,
            {quarter_expr} AS quarter,
            '{col}' AS column,
            COUNT(*) AS total_rows,
            SUM(CASE WHEN NOT {blank} THEN 1 ELSE 0 END) AS filled_count,
            SUM(CASE WHEN NOT {blank} AND ({parseable}) THEN 1 ELSE 0 END) AS parseable_count,
            SUM(CASE WHEN {blank} OR ({parseable}) THEN 1 ELSE 0 END) AS valid_count,
            ROUND(SUM(CASE WHEN NOT {blank} THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 6) AS fill_rate,
            ROUND(
                SUM(CASE WHEN NOT {blank} AND ({parseable}) THEN 1 ELSE 0 END)
                * 1.0 / NULLIF(SUM(CASE WHEN NOT {blank} THEN 1 ELSE 0 END), 0),
                6
            ) AS parse_rate,
            ROUND(SUM(CASE WHEN {blank} OR ({parseable}) THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 6) AS valid_rate
        FROM h
        GROUP BY source, cik, quarter
        """
        parts.append(con.execute(sql).fetchdf())

    metrics = pd.concat(parts, ignore_index=True) if parts else _empty_metrics()
    if metrics.empty:
        return _empty_metrics()

    if issues.empty:
        metrics["fail_count"] = 0
        metrics["warn_count"] = 0
        return metrics[METRIC_COLUMNS]

    issue_counts = issues.copy()
    issue_counts["quarter"] = issue_counts["report_date"].map(_quarter_from_date_string)
    grouped = (
        issue_counts
        .groupby(["source", "cik", "quarter", "column", "severity"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    for sev in (SEVERITY_FAIL, SEVERITY_WARN):
        if sev not in grouped.columns:
            grouped[sev] = 0
    grouped = grouped.rename(columns={
        SEVERITY_FAIL: "fail_count",
        SEVERITY_WARN: "warn_count",
    })
    metrics = metrics.merge(
        grouped[["source", "cik", "quarter", "column", "fail_count", "warn_count"]],
        on=["source", "cik", "quarter", "column"],
        how="left",
    )
    metrics["fail_count"] = metrics["fail_count"].fillna(0).astype(int)
    metrics["warn_count"] = metrics["warn_count"].fillna(0).astype(int)
    return metrics[METRIC_COLUMNS]


def _quarter_from_date_string(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return f"{parsed.year}q{((parsed.month - 1) // 3) + 1}"


def adapt_validation_reports(reports: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Convert existing validation report DataFrames to issue rows."""
    if not reports:
        return _empty_issues()

    issue_frames = [
        _adapt_gav(reports.get("gav_reconciliation")),
        _adapt_pct_sum(reports.get("pct_sum")),
        _adapt_count_stability(reports.get("count_stability")),
        _adapt_income_yield(reports.get("income_yield")),
        _adapt_classification(reports.get("classification_validation")),
        _adapt_aggregate_leaks(reports.get("aggregate_leaks")),
        _adapt_coverage(reports.get("coverage")),
        _adapt_cross_source_duplicates(reports.get("duplicate_holdings")),
    ]
    issue_frames = [df for df in issue_frames if df is not None and not df.empty]
    return pd.concat(issue_frames, ignore_index=True) if issue_frames else _empty_issues()


def _make_issue_frame(
    rows: list[dict[str, Any]],
    default_column: str = "",
) -> pd.DataFrame:
    if not rows:
        return _empty_issues()
    normalized = []
    for row in rows:
        item = {col: "" for col in ISSUE_COLUMNS}
        item.update({
            "dataset": DATASET,
            "status": STATUS_OPEN,
            "row_key": "",
            "column": default_column,
            "value": "",
            "evidence": "",
        })
        item.update(row)
        normalized.append(item)
    return pd.DataFrame(normalized, columns=ISSUE_COLUMNS)


def _adapt_gav(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_issues()
    rows = []
    for _, row in df.iterrows():
        ratio = pd.to_numeric(row.get("gav_ratio_adjusted"), errors="coerce")
        if pd.isna(ratio):
            ratio = pd.to_numeric(row.get("gav_ratio"), errors="coerce")
        if pd.isna(ratio):
            continue
        rule_hint = str(row.get("gav_rule_id", "") or "")
        holdings_source = str(row.get("holdings_source", "") or row.get("source", "") or "").lower()
        is_nport_scope = rule_hint == GAV_NPORT_SCOPE_RULE or holdings_source == "nport"
        comparison_source = row.get("comparison_source", "")
        evidence = (
            f"comparison_source={comparison_source}; "
            f"holdings_scope={row.get('holdings_scope', '')}; "
            f"denominator_scope={row.get('denominator_scope', '')}"
        )
        if is_nport_scope and (ratio < 0.8 or ratio > 1.2):
            rows.append({
                "source": "nport",
                "cik": row.get("cik", ""),
                "report_date": row.get("report_date", ""),
                "column": "fair_value",
                "rule_id": GAV_NPORT_SCOPE_RULE,
                "severity": SEVERITY_WARN,
                "evidence_strength": EVIDENCE_MODERATE,
                "action": ACTION_DISCLOSE,
                "value": str(ratio),
                "message": (
                    "N-PORT private-market holdings coverage ratio is outside "
                    "full-fund denominator range"
                ),
                "evidence": evidence,
            })
            continue
        if ratio < 0.3 or ratio > 5.0:
            rows.append({
                "source": "bdc" if holdings_source == "bdc" else "",
                "cik": row.get("cik", ""),
                "report_date": row.get("report_date", ""),
                "column": "fair_value",
                "rule_id": GAV_BDC_FAIL_RULE,
                "severity": SEVERITY_FAIL,
                "evidence_strength": EVIDENCE_STRONG,
                "action": ACTION_BLOCK_VERIFIED,
                "value": str(ratio),
                "message": "BDC GAV reconciliation ratio is extreme",
                "evidence": evidence,
            })
        elif ratio < 0.8 or ratio > 1.2:
            rows.append({
                "source": "bdc" if holdings_source == "bdc" else "",
                "cik": row.get("cik", ""),
                "report_date": row.get("report_date", ""),
                "column": "fair_value",
                "rule_id": GAV_BDC_WARN_RULE,
                "severity": SEVERITY_WARN,
                "evidence_strength": EVIDENCE_MODERATE,
                "action": ACTION_REVIEW,
                "value": str(ratio),
                "message": "BDC GAV reconciliation ratio outside 0.8-1.2",
                "evidence": evidence,
            })
    return _make_issue_frame(rows)


def _adapt_pct_sum(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty or "flag" not in df.columns:
        return _empty_issues()
    rows = []
    for _, row in df[df["flag"].isin(["high_pct_sum", "low_pct_sum"])].iterrows():
        rows.append({
            "source": "bdc",
            "cik": row.get("cik", ""),
            "report_date": row.get("report_date", ""),
            "column": "pct_of_net_assets",
            "rule_id": "PCT01" if row.get("flag") == "high_pct_sum" else "PCT02",
            "severity": SEVERITY_WARN,
            "evidence_strength": EVIDENCE_MODERATE,
            "action": ACTION_REVIEW,
            "value": str(row.get("pct_sum", "")),
            "message": "pct_of_net_assets CIK-quarter sum outside expected range",
            "evidence": f"flag={row.get('flag', '')}",
        })
    return _make_issue_frame(rows)


def _adapt_count_stability(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty or "flag" not in df.columns:
        return _empty_issues()
    rows = []
    for _, row in df[df["flag"].isin(["unstable_count", "count_fv_divergence"])].iterrows():
        rows.append({
            "source": "",
            "cik": row.get("cik", ""),
            "report_date": row.get("report_date", ""),
            "column": "issuer_name",
            "rule_id": "CNT01" if row.get("flag") == "unstable_count" else "CNT02",
            "severity": SEVERITY_WARN,
            "evidence_strength": EVIDENCE_MODERATE,
            "action": ACTION_REVIEW,
            "value": str(row.get("count_ratio", "")),
            "message": "position count stability check flagged CIK-quarter",
            "evidence": f"flag={row.get('flag', '')}; fv_ratio={row.get('fv_ratio', '')}",
        })
    return _make_issue_frame(rows)


def _adapt_income_yield(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty or "flag" not in df.columns:
        return _empty_issues()
    rows = []
    for _, row in df[df["flag"] == "yield_outlier"].iterrows():
        rows.append({
            "source": "bdc",
            "cik": row.get("cik", ""),
            "report_date": "",
            "column": "interest_rate",
            "rule_id": "YLD01",
            "severity": SEVERITY_WARN,
            "evidence_strength": EVIDENCE_MODERATE,
            "action": ACTION_REVIEW,
            "value": str(row.get("yield_ratio", "")),
            "message": "fund income yield inconsistent with median position coupon",
            "evidence": "yield_ratio outside 0.5-2.5",
        })
    return _make_issue_frame(rows)


def _adapt_classification(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty or "disagreement_count" not in df.columns:
        return _empty_issues()
    rows = []
    for _, row in df.iterrows():
        disagree = pd.to_numeric(row.get("disagreement_count"), errors="coerce")
        if pd.isna(disagree) or disagree <= 0:
            continue
        rule = str(row.get("rule", ""))
        if rule.startswith(("I1", "I2", "I3", "A2", "A3")):
            severity = SEVERITY_WARN
            evidence = EVIDENCE_MODERATE
            action = ACTION_REVIEW
        elif rule.startswith(("E2", "A1", "A4")):
            severity = SEVERITY_WARN
            evidence = EVIDENCE_MODERATE
            action = ACTION_REVIEW
        else:
            severity = SEVERITY_WARN
            evidence = EVIDENCE_WEAK
            action = ACTION_REVIEW
        rows.append({
            "source": "",
            "cik": "",
            "report_date": "",
            "column": "index_classification",
            "rule_id": f"CLS_{rule.split(':', 1)[0].strip().replace(' ', '_')}",
            "severity": severity,
            "evidence_strength": evidence,
            "action": action,
            "value": str(disagree),
            "message": "classification cross-reference disagreement",
            "evidence": f"rule={rule}; samples={row.get('sample_names', '')}",
        })
    return _make_issue_frame(rows)


def _adapt_aggregate_leaks(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_issues()
    rows = []
    for _, row in df.iterrows():
        reason = str(row.get("reason", ""))
        rows.append({
            "source": "bdc",
            "cik": row.get("cik", ""),
            "report_date": row.get("report_date", ""),
            "row_key": str(row.get("_row_id", "")),
            "column": "issuer_name",
            "rule_id": "AGG01",
            "severity": SEVERITY_WARN,
            "evidence_strength": EVIDENCE_WEAK,
            "action": ACTION_REVIEW,
            "value": str(row.get("issuer_name", "")),
            "message": "aggregate/header row suspected in holdings",
            "evidence": reason,
        })
    return _make_issue_frame(rows)


def _adapt_coverage(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty or "issue" not in df.columns:
        return _empty_issues()
    rows = []
    for _, row in df[df["issue"].isin(["no_holdings", "single_period"])].iterrows():
        rows.append({
            "source": "",
            "cik": row.get("cik", ""),
            "report_date": "",
            "column": "cik",
            "rule_id": "COV01" if row.get("issue") == "no_holdings" else "COV02",
            "severity": SEVERITY_INFO,
            "evidence_strength": EVIDENCE_MODERATE,
            "action": ACTION_DISCLOSE,
            "value": str(row.get("issue", "")),
            "message": "coverage check noted limited holdings history",
            "evidence": f"vehicle_type={row.get('vehicle_type', '')}",
        })
    return _make_issue_frame(rows)


def _adapt_cross_source_duplicates(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_issues()
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "source": str(row.get("source", "")),
            "cik": row.get("cik", ""),
            "report_date": row.get("report_date", ""),
            "column": "issuer_name",
            "rule_id": "DUP01",
            "severity": SEVERITY_WARN,
            "evidence_strength": EVIDENCE_MODERATE,
            "action": ACTION_REVIEW,
            "value": str(row.get("issuer_name", "")),
            "message": "cross-source duplicate candidate",
            "evidence": "duplicate_holdings report",
        })
    return _make_issue_frame(rows)


def build_quality_summary(
    unified_df: pd.DataFrame,
    issues: pd.DataFrame,
) -> pd.DataFrame:
    """Build CIK-report_date validation tiers from issue rows."""
    if unified_df.empty:
        return _empty_summary()
    df = _prepare_df(unified_df)
    con = duckdb.connect()
    con.register("h", df)
    base = con.execute(f"""
        SELECT
            '{DATASET}' AS dataset,
            {_value_sql('source')} AS source,
            {_value_sql('cik')} AS cik,
            {_value_sql('report_date')} AS report_date,
            {_quarter_sql('report_date')} AS quarter,
            COUNT(*) AS row_count
        FROM h
        GROUP BY source, cik, report_date, quarter
    """).fetchdf()
    con.close()

    if issues.empty:
        base["validation_tier"] = "VERIFIED"
        base["fail_count"] = 0
        base["warn_count"] = 0
        base["info_count"] = 0
        base["strong_issue_count"] = 0
        base["moderate_issue_count"] = 0
        base["weak_issue_count"] = 0
        return base[SUMMARY_COLUMNS]

    issue_data = issues.copy()
    issue_data["quarter"] = issue_data["report_date"].map(_quarter_from_date_string)
    issue_data["source"] = issue_data["source"].fillna("")
    issue_data["cik"] = issue_data["cik"].fillna("")
    issue_data["report_date"] = issue_data["report_date"].fillna("")

    group_cols = ["source", "cik", "report_date", "quarter"]
    grouped = issue_data.groupby(group_cols, dropna=False).agg(
        fail_count=("severity", lambda s: int((s == SEVERITY_FAIL).sum())),
        warn_count=("severity", lambda s: int((s == SEVERITY_WARN).sum())),
        info_count=("severity", lambda s: int((s == SEVERITY_INFO).sum())),
        strong_issue_count=("evidence_strength", lambda s: int((s == EVIDENCE_STRONG).sum())),
        moderate_issue_count=("evidence_strength", lambda s: int((s == EVIDENCE_MODERATE).sum())),
        weak_issue_count=("evidence_strength", lambda s: int((s == EVIDENCE_WEAK).sum())),
    ).reset_index()

    summary = base.merge(grouped, on=group_cols, how="left")
    for col in [
        "fail_count", "warn_count", "info_count", "strong_issue_count",
        "moderate_issue_count", "weak_issue_count",
    ]:
        summary[col] = summary[col].fillna(0).astype(int)

    summary["validation_tier"] = "VERIFIED"
    summary.loc[summary["warn_count"] > 0, "validation_tier"] = "VALIDATED_WITH_WARNINGS"
    summary.loc[summary["fail_count"] > 0, "validation_tier"] = "UNDER_REVIEW"
    return summary[SUMMARY_COLUMNS]


def run_column_quality_validation(
    unified_df: pd.DataFrame,
    existing_reports: Optional[dict[str, pd.DataFrame]] = None,
) -> dict[str, pd.DataFrame]:
    """Run column contracts and adapters, returning all quality artifacts."""
    column_issues, metrics = validate_column_contracts(unified_df)
    adapter_issues = adapt_validation_reports(existing_reports or {})
    all_issues = pd.concat(
        [df for df in [column_issues, adapter_issues] if not df.empty],
        ignore_index=True,
    ) if not column_issues.empty or not adapter_issues.empty else _empty_issues()
    summary = build_quality_summary(unified_df, all_issues)
    logger.info(
        "Column validation: %d issues, %d metric rows, %d CIK-date summaries",
        len(all_issues), len(metrics), len(summary),
    )
    return {
        "row_validation_issues": all_issues[ISSUE_COLUMNS],
        "column_quality_metrics": metrics[METRIC_COLUMNS],
        "data_quality_metrics": summary[SUMMARY_COLUMNS],
    }
