import csv
import json
from pathlib import Path

import pytest

from pipeline import interval_source_review as review


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _nport_row(
    *,
    cik: str = "1",
    series_id: str = "S1",
    report_date: str = "2025-03-31",
    holding_id: str = "H1",
    issuer_name: str = "Private Borrower LLC",
    issuer_title: str = "First Lien Loan",
    asset_cat: str = "DBT",
    issuer_type: str = "CORP",
    ticker: str = "",
    cusip: str = "",
    restricted: str = "Y",
    value: str = "100",
) -> dict[str, str]:
    return {
        "accession_number": "0001-25-000001",
        "cik": cik,
        "registrant_name": "Fund A",
        "series_id": series_id,
        "series_name": "Fund A Series",
        "report_date": report_date,
        "holding_id": holding_id,
        "issuer_name": issuer_name,
        "issuer_title": issuer_title,
        "asset_cat": asset_cat,
        "issuer_type": issuer_type,
        "identifier_ticker": ticker,
        "issuer_cusip": cusip,
        "identifier_isin": "",
        "issuer_lei": "",
        "is_restricted_security": restricted,
        "currency_value": value,
        "maturity_date": "2029-03-31",
        "annualized_rate": "10",
    }


def _holding_row(
    *,
    cik: str = "1",
    series_id: str = "S1",
    report_date: str = "2025-03-31",
    holding_id: str = "H1",
    issuer_name: str = "Private Borrower LLC",
    value: str = "100",
) -> dict[str, str]:
    return {
        "source": "nport",
        "cik": cik,
        "entity_name": "Fund A",
        "report_date": report_date,
        "accession_number": "0001-25-000001",
        "issuer_name": issuer_name,
        "instrument_description": "First Lien Loan",
        "fair_value": value,
        "nport_holding_id": holding_id,
        "nport_series_id": series_id,
        "nport_series_name": "Fund A Series",
        "nport_asset_cat": "DBT",
        "nport_issuer_type": "CORP",
        "maturity_date": "2029-03-31",
        "interest_rate": "10",
        "entity_id": "ENT-1",
        "canonical_name": issuer_name,
    }


def test_worklist_filters_interval_tender_and_reconciles_exact_identifier(tmp_path):
    universe = tmp_path / "combined_universe.csv"
    nport = tmp_path / "nport_holdings.csv"
    holdings = tmp_path / "private_markets_holdings.csv"
    out = tmp_path / "interval_source_review"
    _write_csv(
        universe,
        [
            {"cik": "1", "series_id": "S1", "entity_name": "Fund A", "fund_name": "Fund A Series", "vehicle_type": "interval_fund"},
            {"cik": "2", "series_id": "S2", "entity_name": "BDC B", "fund_name": "BDC B", "vehicle_type": "bdc"},
        ],
    )
    _write_csv(nport, [_nport_row(), _nport_row(cik="2", series_id="S2", holding_id="B1")])
    _write_csv(holdings, [_holding_row()])

    stats = review.build_worklist(nport_path=nport, holdings_path=holdings, universe_path=universe, output_dir=out)

    assert stats["worklist_count"] == 0
    detail = _read_csv(out / "source_reconciliation_detail.csv")
    assert len(detail) == 1
    assert detail[0]["status"] == "MATCHED"
    assert detail[0]["match_tier"] == "holding_id"


def test_private_source_only_blocks_public_and_cash_do_not(tmp_path):
    universe = tmp_path / "combined_universe.csv"
    nport = tmp_path / "nport_holdings.csv"
    holdings = tmp_path / "private_markets_holdings.csv"
    out = tmp_path / "interval_source_review"
    _write_csv(universe, [{"cik": "1", "series_id": "S1", "entity_name": "Fund A", "fund_name": "Fund A Series", "vehicle_type": "tender_offer_fund"}])
    _write_csv(
        nport,
        [
            _nport_row(holding_id="PVT", issuer_name="Private Borrower LLC", value="100"),
            _nport_row(holding_id="PUB", issuer_name="Public Co", issuer_title="Common Stock", asset_cat="EC", ticker="PUB", cusip="123456789", restricted="N", value="50"),
            _nport_row(holding_id="CASH", issuer_name="Money Market Fund", issuer_title="Cash Sweep", asset_cat="STIV", issuer_type="RF", restricted="N", value="25"),
        ],
    )
    _write_csv(holdings, [])

    stats = review.build_worklist(nport_path=nport, holdings_path=holdings, universe_path=universe, output_dir=out)

    assert stats["worklist_count"] == 1
    worklist = _read_csv(out / "worklist.csv")
    assert worklist[0]["source_only_blocker_rows"] == "1"
    source_only = _read_csv(out / "source_only_detail.csv")
    blocking = [row for row in source_only if row["blocking_issue"] == "True"]
    nonblocking = [row for row in source_only if row["blocking_issue"] == "False"]
    assert len(blocking) == 1
    assert blocking[0]["diagnosis"] == "REAL_SOURCE_POSITION_MISSING_FROM_UNIFIED"
    assert {row["diagnosis"] for row in nonblocking} == {"PUBLIC_MARKET_OR_NON_PRIVATE_FILTERED", "MONEY_MARKET_OR_CASH_EQUIVALENT"}


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.needs_cache
def test_build_bundle_includes_ncsr_html_and_entity_context(tmp_path, monkeypatch):
    output = tmp_path / "output"
    review_dir = output / "interval_source_review"
    monkeypatch.setattr(review.config, "UNIFIED_HOLDINGS_FILE", output / "private_markets_holdings.csv")
    monkeypatch.setattr(review.config, "NPORT_HOLDINGS_FILE", output / "nport_holdings.csv")
    monkeypatch.setattr(review.config, "COMBINED_UNIVERSE_FILE", output / "combined_universe.csv")
    monkeypatch.setattr(review.config, "NCSR_FILINGS_INDEX_FILE", output / "ncsr_filings_index.csv")
    monkeypatch.setattr(review.config, "ENTITY_LOOKUP_FILE", output / "entity_lookup.csv")
    monkeypatch.setattr(review.config, "NCSR_HTML_CACHE_DIR", output / "ncsr_html")

    _write_csv(review.config.COMBINED_UNIVERSE_FILE, [{"cik": "1", "series_id": "S1", "entity_name": "Fund A", "fund_name": "Fund A Series", "vehicle_type": "interval_fund"}])
    _write_csv(review.config.NPORT_HOLDINGS_FILE, [_nport_row()])
    _write_csv(review.config.UNIFIED_HOLDINGS_FILE, [])
    _write_csv(review.config.NCSR_FILINGS_INDEX_FILE, [{"cik": "1", "report_date": "2025-03-31", "accession_number": "0001-25-000001", "filing_date": "2025-05-01"}])
    _write_csv(review.config.ENTITY_LOOKUP_FILE, [{"entity_id": "ENT-1", "canonical_name": "Private Borrower LLC", "issuer_name_variant": "Private Borrower LLC", "source": "nport"}])

    review.build_worklist(output_dir=review_dir)
    manifest = review.build_bundles(output_dir=review_dir, overwrite=True)

    bundle = json.loads((review_dir / "bundles" / f"{manifest[0]['review_id']}.json").read_text(encoding="utf-8"))
    evidence_ids = [item["evidence_id"] for item in bundle["evidence_items"]]
    assert bundle["schema_version"] == "interval-source-review-bundle.v1"
    assert "entity_candidate_context" in evidence_ids
    assert "html_artifact" in evidence_ids
    html_item = next(item for item in bundle["evidence_items"] if item["evidence_id"] == "html_artifact")
    assert html_item["data"]["status"] == "missing_cached_html"


def test_validate_verdict_rejects_html_ref_without_coordinates(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "INTSRC_0000000001_S1_2025-03-31_M_abc"
    _write_csv(output / "worklist.csv", [{"review_id": review_id, "cik": "0000000001", "series_id": "S1", "report_date": "2025-03-31", "mechanism": "m", "affected_source_fair_value": "100"}])
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps({"review_id": review_id, "cik": "0000000001", "series_id": "S1", "report_date": "2025-03-31", "evidence_items": [{"evidence_id": "html_source_row_coordinate_candidates"}]}),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "report_date": "2025-03-31",
        "verdict": "INSUFFICIENT_EVIDENCE",
        "confidence": "LOW",
        "primary_justification": "HTML evidence is unresolved.",
        "reconciliation_diagnosis": "INSUFFICIENT_EVIDENCE",
        "evidence_refs": ["html_source_row_coordinate_candidates"],
        "changed_files": [],
        "patch_summary": "",
        "source_reconciliation_effect": "",
        "gav_effect": "",
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "Need coordinate-level N-CSR evidence.",
        "residual_risk": "No bounded mechanism.",
        "reviewer_notes": "Reject free-text-only HTML citation.",
    }
    verdict_path = output / "verdicts" / f"{review_id}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = review.validate_verdict_file(verdict_path, output)
    assert any("requires table_index,row_index,cell_indices" in error for error in errors)

    verdict["evidence_refs"] = []
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    assert review.validate_all_verdicts(output) == []
