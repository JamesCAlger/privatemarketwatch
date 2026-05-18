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
            "principal_amount": "100000",
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
