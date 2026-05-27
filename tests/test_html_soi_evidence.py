import json
from pathlib import Path

from pipeline import html_extract
from pipeline import html_soi_evidence as evidence


def _write_html(cache_root: Path, cik: str, accession: str, body: str) -> Path:
    path = cache_root / cik.lstrip("0") / f"{accession.replace('-', '')}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return path


def _table(header: list[str], rows: list[list[str]]) -> str:
    all_rows = [header] + rows
    return "<table>" + "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in all_rows
    ) + "</table>"


def _soi_table(rows: list[list[str]]) -> str:
    return _table(
        ["Portfolio Company", "Investment", "Principal", "Cost", "Fair Value", "Maturity", "Rate", "Industry"],
        rows,
    )


def _patch_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    cache = tmp_path / "filings" / "bdc_html"
    templates = tmp_path / "filing_templates"
    templates.mkdir(parents=True)
    monkeypatch.setattr(evidence.config, "BDC_HTML_CACHE_DIR", cache)
    monkeypatch.setattr(html_extract, "HTML_TEMPLATE_DIR", templates)
    return cache, templates


def test_template_table_selection_beats_auto_detect_fallback(monkeypatch, tmp_path):
    cache, templates = _patch_paths(monkeypatch, tmp_path)
    accession = "0001-25-000001"
    _write_html(
        cache,
        "1",
        accession,
        _soi_table([["Wrong Issuer", "Loan", "1", "1", "1", "2029", "10%", ""] for _ in range(6)])
        + _soi_table([["Template Issuer", "Loan", "2", "2", "2", "2029", "10%", ""] for _ in range(6)]),
    )
    (templates / "1.json").write_text(
        json.dumps({"version": "3.0", "cik": "1", "filings": {accession: {"tables": [1], "table_periods": {"2025-06-30": [1]}}}}),
        encoding="utf-8",
    )

    items = evidence.build_html_soi_evidence(source="bdc", cik="1", report_date="2025-06-30", accession=accession, residual_names=["Template Issuer"])

    by_id = {item["evidence_id"]: item["data"] for item in items}
    assert by_id["html_template_selection"]["selection_source"] == "accession_template"
    assert "html_detected_soi_candidates" not in by_id
    assert {cell["table_index"] for cell in by_id["html_table_grid_excerpt"]} == {1}


def test_auto_detect_produces_labeled_candidate_evidence_without_template(monkeypatch, tmp_path):
    cache, _ = _patch_paths(monkeypatch, tmp_path)
    accession = "0001-25-000002"
    _write_html(
        cache,
        "1",
        accession,
        _soi_table([["Issuer A", "Loan", "1", "1", "1", "2029", "10%", ""] for _ in range(15)]),
    )

    items = evidence.build_html_soi_evidence(source="bdc", cik="1", report_date="2025-06-30", accession=accession)
    by_id = {item["evidence_id"]: item["data"] for item in items}

    assert by_id["html_detected_soi_candidates"]["candidate_type"] == "auto_detect_fallback"
    assert by_id["html_detected_soi_candidates"]["selected_tables"] == [0]


def test_table_periods_separate_current_and_comparative_rows(monkeypatch, tmp_path):
    cache, templates = _patch_paths(monkeypatch, tmp_path)
    accession = "0001-25-000003"
    _write_html(
        cache,
        "1",
        accession,
        _soi_table([["Current Issuer", "Loan", "1", "1", "1", "2029", "10%", ""] for _ in range(6)])
        + _soi_table([["Comparative Issuer", "Loan", "1", "1", "1", "2028", "9%", ""] for _ in range(6)]),
    )
    (templates / "1.json").write_text(
        json.dumps({"version": "3.0", "cik": "1", "filings": {accession: {"tables": [0, 1], "table_periods": {"2025-06-30": [0], "2024-06-30": [1]}}}}),
        encoding="utf-8",
    )

    items = evidence.build_html_soi_evidence(source="bdc", cik="1", report_date="2025-06-30", accession=accession, residual_names=["Comparative Issuer"])
    candidates = {row["row_text"]: row for item in items if item["evidence_id"] == "html_row_classification_candidates" for row in item["data"]}

    comparative = next(row for text, row in candidates.items() if "Comparative Issuer" in text)
    assert comparative["period"] == "2024-06-30"
    assert "COMPARATIVE_PERIOD_ROW" in comparative["classification_candidates"]


def test_aggregate_subtotal_and_continuation_rows_preserve_coordinates(monkeypatch, tmp_path):
    cache, templates = _patch_paths(monkeypatch, tmp_path)
    accession = "0001-25-000004"
    _write_html(
        cache,
        "1",
        accession,
        _soi_table(
            [
                ["Non-controlled investments", "", "", "", "", "", "", ""],
                ["Issuer A", "First Lien", "1", "1", "1", "2029", "10%", ""],
                ["", "Delayed Draw", "2", "2", "2", "2029", "10%", ""],
                ["Total investments", "", "", "3", "3", "", "", ""],
                ["Portfolio Company", "", "", "", "", "", "", ""],
            ]
        ),
    )
    (templates / "1.json").write_text(
        json.dumps({"version": "3.0", "cik": "1", "filings": {accession: {"tables": [0]}}}),
        encoding="utf-8",
    )

    items = evidence.build_html_soi_evidence(source="bdc", cik="1", report_date="2025-06-30", accession=accession, residual_names=["Issuer A"])
    rows = [row for item in items if item["evidence_id"] == "html_row_classification_candidates" for row in item["data"]]

    labels = {row["row_index"]: row["classification_candidates"] for row in rows}
    assert "AGGREGATE_HEADER" in labels[1]
    assert "CONTINUATION_ROW" in labels[3]
    assert "SUBTOTAL_ROW" in labels[4]
    assert all("table_index" in row and "row_index" in row and row["cell_indices"] for row in rows)


def test_missing_cached_html_creates_explicit_missing_evidence(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)

    items = evidence.build_html_soi_evidence(source="bdc", cik="1", report_date="2025-06-30", accession="0001-25-999999")

    assert items[0]["evidence_id"] == "html_artifact"
    assert items[0]["data"]["status"] == "missing_cached_html"
    assert items[0]["data"]["path"].endswith("filings/bdc_html/1/000125999999.html")
    assert items[0]["data"]["accession_number"] == "0001-25-999999"


def test_non_bdc_skips_html_evidence(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    assert evidence.build_html_soi_evidence(source="nport", cik="1", report_date="2025-06-30", accession="x") == []
