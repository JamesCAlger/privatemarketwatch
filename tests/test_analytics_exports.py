import csv
import json
from pathlib import Path

import duckdb

from pipeline.export import analytics_exports
from pipeline.export import helpers as export_helpers


HOLDINGS_COLUMNS = [
    "source",
    "cik",
    "report_date",
    "issuer_name",
    "fair_value",
    "cost",
    "principal_amount",
    "principal_amount_usd",
    "index_classification",
    "pik_rate",
    "nport_is_paid_in_kind",
    "bdc_investment_identifier",
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HOLDINGS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_data_quality_export_includes_gav_status_counts(monkeypatch, tmp_path):
    gav = tmp_path / "holdings_gav_reconciliation.csv"
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir(parents=True)
    _write_rows(gav, [
        {
            "cik": "0000000001",
            "report_date": "2024-03-31",
            "comparison_source": "investments_at_fair_value",
            "comparison_confidence": "STRONG",
            "reconciliation_status": "PASS",
            "gav_ratio": "1.0",
            "gav_ratio_adjusted": "1.0",
        },
        {
            "cik": "0000000002",
            "report_date": "2024-03-31",
            "comparison_source": "total_assets_companyfacts",
            "comparison_confidence": "MODERATE",
            "reconciliation_status": "WARN",
            "gav_ratio": "0.7",
            "gav_ratio_adjusted": "0.7",
        },
    ])
    missing = tmp_path / "missing.csv"
    monkeypatch.setattr(analytics_exports, "HOLDINGS_GAV_RECONCILIATION_FILE", gav)
    monkeypatch.setattr(analytics_exports, "CLASSIFICATION_VALIDATION_FILE", missing)
    monkeypatch.setattr(analytics_exports, "UNIFIED_HOLDINGS_CSV", missing)
    monkeypatch.setattr(analytics_exports, "FUND_FINANCIALS_CSV", missing)
    monkeypatch.setattr(analytics_exports, "DATA_QUALITY_METRICS_FILE", missing)
    monkeypatch.setattr(analytics_exports, "COLUMN_QUALITY_METRICS_FILE", missing)
    monkeypatch.setattr(analytics_exports, "ROW_VALIDATION_ISSUES_FILE", missing)
    monkeypatch.setattr(analytics_exports, "VALIDATION_REPORT_FILE", missing)
    monkeypatch.setattr(analytics_exports, "LLM_FUND_VALIDATION_RESULTS_FILE", missing)
    monkeypatch.setattr(analytics_exports, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(export_helpers, "FRONTEND_DATA_DIR", frontend_dir)

    con = duckdb.connect(":memory:")
    analytics_exports._export_data_quality(con)

    exported = json.loads((frontend_dir / "data_quality.json").read_text(encoding="utf-8"))
    gav_export = exported["gavReconciliation"]
    assert gav_export["statusCounts"] == [
        {"status": "PASS", "count": 1},
        {"status": "WARN", "count": 1},
    ]
    assert gav_export["strongCikQuarters"] == 1
    assert gav_export["proxyCikQuarters"] == 1


def test_credit_risk_export_is_bdc_only_independent_signals(monkeypatch, tmp_path):
    holdings = tmp_path / "private_markets_holdings.csv"
    frontend_dir = tmp_path / "frontend"
    nonaccrual = tmp_path / "nonaccrual_flags.csv"
    missing_financials = tmp_path / "missing_fund_financials.csv"
    frontend_dir.mkdir(parents=True)

    _write_csv(holdings, [
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "issuer_name": "Overlap Co",
            "fair_value": "70000",
            "cost": "100000",
            "principal_amount": "70000",
            "principal_amount_usd": "100000",
            "index_classification": "DIRECT_LENDING",
            "pik_rate": "",
            "nport_is_paid_in_kind": "",
            "bdc_investment_identifier": "overlap-id",
        },
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "issuer_name": "PIK Terms Only Co",
            "fair_value": "100000",
            "cost": "100000",
            "principal_amount": "100000",
            "principal_amount_usd": "100000",
            "index_classification": "DIRECT_LENDING",
            "pik_rate": "12.0",
            "nport_is_paid_in_kind": "",
            "bdc_investment_identifier": "pik-only-id",
        },
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "issuer_name": "Bad Scale Co",
            "fair_value": "100000",
            "cost": "1000000000",
            "principal_amount": "1000000000",
            "principal_amount_usd": "1000000000",
            "index_classification": "DIRECT_LENDING",
            "pik_rate": "",
            "nport_is_paid_in_kind": "",
            "bdc_investment_identifier": "bad-scale-id",
        },
        {
            "source": "nport",
            "cik": "0000000002",
            "report_date": "2025-03-31",
            "issuer_name": "NPORT Distressed Co",
            "fair_value": "10000",
            "cost": "100000",
            "principal_amount": "100000",
            "principal_amount_usd": "100000",
            "index_classification": "DIRECT_LENDING",
            "pik_rate": "",
            "nport_is_paid_in_kind": "Y",
            "bdc_investment_identifier": "nport-id",
        },
    ])
    nonaccrual.write_text(
        "cik,report_date,investment_identifier,nonaccrual_source\n"
        "0000000001,2025-03-31,overlap-id,fixture\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(analytics_exports, "UNIFIED_HOLDINGS_CSV", holdings)
    monkeypatch.setattr(analytics_exports, "NONACCRUAL_FLAGS_CSV", nonaccrual)
    monkeypatch.setattr(analytics_exports, "FUND_FINANCIALS_CSV", missing_financials)
    monkeypatch.setattr(analytics_exports, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(export_helpers, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(export_helpers, "UNLISTED_BDC_CIKS", set())

    con = duckdb.connect(":memory:")
    analytics_exports._export_credit_risk(con)

    exported = json.loads((frontend_dir / "credit_risk.json").read_text(encoding="utf-8"))
    assert exported == [{
        "quarter": "2025q1",
        "totalPositions": 3,
        "totalFv": 270000.0,
        "byCount": {
            "deepDistress": 0.3333,
            "nonAccrual": 0.3333,
            "markedBelowCost": 0.3333,
        },
        "byFv": {
            "deepDistress": 0.2593,
            "nonAccrual": 0.2593,
            "markedBelowCost": 0.2593,
        },
    }]
    assert "pikActive" not in exported[0]["byCount"]
    assert "healthy" not in exported[0]["byCount"]


def test_credit_risk_nonaccrual_affiliation_prefix_stripped(monkeypatch, tmp_path):
    """Non-accrual flags with affiliation-prefixed identifiers should still
    join to unified holdings where bdc_investment_identifier is stripped."""
    holdings = tmp_path / "private_markets_holdings.csv"
    frontend_dir = tmp_path / "frontend"
    nonaccrual = tmp_path / "nonaccrual_flags.csv"
    missing_financials = tmp_path / "missing_fund_financials.csv"
    frontend_dir.mkdir(parents=True)

    _write_csv(holdings, [
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "issuer_name": "Acme Corp",
            "fair_value": "50000",
            "cost": "100000",
            "principal_amount": "100000",
            "principal_amount_usd": "100000",
            "index_classification": "DIRECT_LENDING",
            "pik_rate": "",
            "nport_is_paid_in_kind": "",
            "bdc_investment_identifier": "Acme Corp - Term Loan",
        },
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "issuer_name": "Beta Inc",
            "fair_value": "50000",
            "cost": "100000",
            "principal_amount": "100000",
            "principal_amount_usd": "100000",
            "index_classification": "DIRECT_LENDING",
            "pik_rate": "",
            "nport_is_paid_in_kind": "",
            "bdc_investment_identifier": "Beta Inc - Revolver",
        },
    ])
    # Raw nonaccrual flags use affiliation-prefixed identifiers.
    # Values with commas must be quoted for CSV parsing.
    nonaccrual.write_text(
        "cik,report_date,investment_identifier,nonaccrual_source\n"
        "0000000001,2025-03-31,"
        "Non-Controlled Investments - Acme Corp - Term Loan,fixture\n"
        '0000000001,2025-03-31,'
        '"Investments in Non-Controlled, Non-Affiliated Portfolio Companies - '
        'Beta Inc - Revolver",fixture\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(analytics_exports, "UNIFIED_HOLDINGS_CSV", holdings)
    monkeypatch.setattr(analytics_exports, "NONACCRUAL_FLAGS_CSV", nonaccrual)
    monkeypatch.setattr(analytics_exports, "FUND_FINANCIALS_CSV", missing_financials)
    monkeypatch.setattr(analytics_exports, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(export_helpers, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(export_helpers, "UNLISTED_BDC_CIKS", set())

    con = duckdb.connect(":memory:")
    analytics_exports._export_credit_risk(con)

    exported = json.loads((frontend_dir / "credit_risk.json").read_text(encoding="utf-8"))
    assert len(exported) == 1
    q = exported[0]
    # Both positions should be flagged as non-accrual after prefix stripping
    assert q["byCount"]["nonAccrual"] == 1.0
    assert q["byFv"]["nonAccrual"] == 1.0


def test_gics_sector_export_uses_reconciled_bdc_before_holdings(monkeypatch, tmp_path):
    holdings = tmp_path / "private_markets_holdings.csv"
    reconciliation = tmp_path / "bdc_sector_reconciliation.csv"
    reconciled = tmp_path / "bdc_sector_breakdown_reconciled.csv"
    missing_raw_sector = tmp_path / "missing_bdc_sector_breakdown.csv"
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir(parents=True)

    _write_rows(holdings, [
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "issuer_name": "Accepted BDC Holding",
            "fair_value": "100",
            "gics_sub_industry": "Energy",
            "extracted_industry": "",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "bdc",
            "cik": "0000000002",
            "report_date": "2025-03-31",
            "issuer_name": "Failed BDC Holding",
            "fair_value": "200",
            "gics_sub_industry": "Health Care",
            "extracted_industry": "",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "nport",
            "cik": "0000000003",
            "report_date": "2025-03-31",
            "issuer_name": "NPORT Holding",
            "fair_value": "300",
            "gics_sub_industry": "Financials",
            "extracted_industry": "",
            "index_classification": "DIRECT_LENDING",
        },
    ])
    _write_rows(reconciliation, [
        {
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "holdings_fair_value": "100",
            "raw_sector_fair_value": "100",
            "absolute_delta": "0",
            "relative_delta": "0",
            "sector_row_count": "1",
            "holdings_row_count": "1",
            "reconciliation_status": "PASS",
        },
        {
            "cik": "0000000002",
            "report_date": "2025-03-31",
            "holdings_fair_value": "200",
            "raw_sector_fair_value": "500",
            "absolute_delta": "300",
            "relative_delta": "1.5",
            "sector_row_count": "1",
            "holdings_row_count": "1",
            "reconciliation_status": "FAIL_REVIEW",
        },
    ])
    _write_rows(reconciled, [
        {
            "cik": "0000000001",
            "entity_name": "Accepted BDC",
            "report_date": "2025-03-31",
            "industry_sector": "software",
            "investment_type": "",
            "gics_sub_industry": "Industrials",
            "raw_sector_fair_value": "100",
            "reconciled_fair_value": "100",
            "reconciliation_status": "PASS",
            "scale_factor": "1",
        },
    ])

    monkeypatch.setattr(analytics_exports, "UNIFIED_HOLDINGS_CSV", holdings)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_RECONCILIATION_FILE", reconciliation)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_BREAKDOWN_RECONCILED_FILE", reconciled)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_BREAKDOWN_FILE", missing_raw_sector)
    monkeypatch.setattr(analytics_exports, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(analytics_exports, "INDEX_DISPLAY_END_QUARTER", "2025q1")
    monkeypatch.setattr(export_helpers, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(export_helpers, "UNLISTED_BDC_CIKS", set())

    con = duckdb.connect(":memory:")
    analytics_exports._export_gics_sector_breakdown(con)

    exported = json.loads((frontend_dir / "gics_sector_breakdown.json").read_text(encoding="utf-8"))
    by_sector = {row["sector"]: row for row in exported}
    assert by_sector["Industrials"]["totalFv"] == 100
    assert by_sector["Industrials"]["sourceBreakdown"]["bdcSectorReconciledFv"] == 100
    assert by_sector["Health Care"]["totalFv"] == 200
    assert by_sector["Health Care"]["sourceBreakdown"]["bdcHoldingsFallbackFv"] == 200
    assert by_sector["Financials"]["totalFv"] == 300
    assert by_sector["Financials"]["sourceBreakdown"]["nportHoldingsFv"] == 300
    assert sum(row["totalFv"] for row in exported) == 600
    assert sum(row["pctOfTotal"] for row in exported) == 1.0


def test_gics_sector_export_falls_back_when_bdc_reconciliation_fails(monkeypatch, tmp_path):
    holdings = tmp_path / "private_markets_holdings.csv"
    reconciliation = tmp_path / "bdc_sector_reconciliation.csv"
    reconciled = tmp_path / "bdc_sector_breakdown_reconciled.csv"
    missing_raw_sector = tmp_path / "missing_bdc_sector_breakdown.csv"
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir(parents=True)

    _write_rows(holdings, [
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "issuer_name": "Failed BDC Holding",
            "fair_value": "100",
            "gics_sub_industry": "Energy",
            "extracted_industry": "",
            "index_classification": "DIRECT_LENDING",
        },
    ])
    _write_rows(reconciliation, [
        {
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "holdings_fair_value": "100",
            "raw_sector_fair_value": "500",
            "absolute_delta": "400",
            "relative_delta": "4",
            "sector_row_count": "1",
            "holdings_row_count": "1",
            "reconciliation_status": "FAIL_REVIEW",
        },
    ])
    _write_rows(reconciled, [
        {
            "cik": "0000000009",
            "entity_name": "Other BDC",
            "report_date": "2025-03-31",
            "industry_sector": "software",
            "investment_type": "",
            "gics_sub_industry": "Industrials",
            "raw_sector_fair_value": "999",
            "reconciled_fair_value": "999",
            "reconciliation_status": "PASS",
            "scale_factor": "1",
        },
    ])

    monkeypatch.setattr(analytics_exports, "UNIFIED_HOLDINGS_CSV", holdings)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_RECONCILIATION_FILE", reconciliation)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_BREAKDOWN_RECONCILED_FILE", reconciled)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_BREAKDOWN_FILE", missing_raw_sector)
    monkeypatch.setattr(analytics_exports, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(analytics_exports, "INDEX_DISPLAY_END_QUARTER", "2025q1")
    monkeypatch.setattr(export_helpers, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(export_helpers, "UNLISTED_BDC_CIKS", set())

    con = duckdb.connect(":memory:")
    analytics_exports._export_gics_sector_breakdown(con)

    exported = json.loads((frontend_dir / "gics_sector_breakdown.json").read_text(encoding="utf-8"))
    assert exported == [{
        "sector": "Energy",
        "totalFv": 100.0,
        "pctOfTotal": 1.0,
        "fundCount": 1,
        "sourceBreakdown": {
            "bdcSectorReconciledFv": 0.0,
            "bdcHoldingsFallbackFv": 100.0,
            "nportHoldingsFv": 0.0,
        },
    }]


def test_gics_sector_export_labels_unknown_and_uses_total_denominator(monkeypatch, tmp_path):
    holdings = tmp_path / "private_markets_holdings.csv"
    missing_reconciliation = tmp_path / "missing_bdc_sector_reconciliation.csv"
    missing_reconciled = tmp_path / "missing_bdc_sector_breakdown_reconciled.csv"
    missing_raw_sector = tmp_path / "missing_bdc_sector_breakdown.csv"
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir(parents=True)

    _write_rows(holdings, [
        {
            "source": "nport",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "issuer_name": "Classified One",
            "fair_value": "100",
            "gics_sub_industry": "Energy",
            "extracted_industry": "",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "nport",
            "cik": "0000000002",
            "report_date": "2025-03-31",
            "issuer_name": "Classified Two",
            "fair_value": "300",
            "gics_sub_industry": "Health Care",
            "extracted_industry": "",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "nport",
            "cik": "0000000003",
            "report_date": "2025-03-31",
            "issuer_name": "Unknown",
            "fair_value": "600",
            "gics_sub_industry": "",
            "extracted_industry": "",
            "index_classification": "DIRECT_LENDING",
        },
    ])

    monkeypatch.setattr(analytics_exports, "UNIFIED_HOLDINGS_CSV", holdings)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_RECONCILIATION_FILE", missing_reconciliation)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_BREAKDOWN_RECONCILED_FILE", missing_reconciled)
    monkeypatch.setattr(analytics_exports, "BDC_SECTOR_BREAKDOWN_FILE", missing_raw_sector)
    monkeypatch.setattr(analytics_exports, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(analytics_exports, "INDEX_DISPLAY_END_QUARTER", "2025q1")
    monkeypatch.setattr(export_helpers, "FRONTEND_DATA_DIR", frontend_dir)
    monkeypatch.setattr(export_helpers, "UNLISTED_BDC_CIKS", set())

    con = duckdb.connect(":memory:")
    analytics_exports._export_gics_sector_breakdown(con)

    exported = json.loads((frontend_dir / "gics_sector_breakdown.json").read_text(encoding="utf-8"))
    by_sector = {row["sector"]: row for row in exported}
    assert "Unclassified" not in by_sector
    assert by_sector["Energy"]["pctOfTotal"] == 0.1
    assert by_sector["Health Care"]["pctOfTotal"] == 0.3
    assert by_sector["Unknown"]["pctOfTotal"] == 0.6
    assert sum(row["totalFv"] for row in exported) == 1000
