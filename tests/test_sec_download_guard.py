import csv
import hashlib
import json
from pathlib import Path

from pipeline.sec_download_guard import (
    bdc_html_cache_path,
    download_bdc_html,
    normalize_accession,
)


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content


class FakeClient:
    def __init__(self, content: bytes = b"", fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.urls: list[str] = []
        self.resolve_calls = 0

    def get(self, url: str) -> FakeResponse:
        self.urls.append(url)
        if self.fail:
            raise RuntimeError("network disabled")
        return FakeResponse(self.content)

    def resolve_filing_document_url(self, *args, **kwargs) -> str:
        self.resolve_calls += 1
        return ""


def _write_filings_index(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "cik",
        "entity_name",
        "accession_number",
        "form_type",
        "filing_date",
        "report_date",
        "primary_document",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _manifest_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_unknown_accession_is_rejected_without_network(tmp_path: Path) -> None:
    filings_index = tmp_path / "bdc_filings_index.csv"
    manifest = tmp_path / "manifest.jsonl"
    lock_dir = tmp_path / "locks"
    cache_dir = tmp_path / "html"
    _write_filings_index(
        filings_index,
        [
            {
                "cik": "0001234567",
                "entity_name": "Known BDC",
                "accession_number": "0001234567-26-000001",
                "form_type": "10-K",
                "filing_date": "2026-03-01",
                "report_date": "2025-12-31",
                "primary_document": "known.htm",
            }
        ],
    )

    client = FakeClient(fail=True)
    record = download_bdc_html(
        client=client,
        cik="0001234567",
        accession="0001234567-26-000002",
        primary_doc="unknown.htm",
        filings_index_file=filings_index,
        cache_dir=cache_dir,
        manifest_file=manifest,
        lock_dir=lock_dir,
    )

    assert record["status"] == "failed"
    assert record["stage"] == "unknown_accession"
    assert client.urls == []
    assert _manifest_records(manifest)[0]["stage"] == "unknown_accession"


def test_cached_file_short_circuits_after_index_validation(tmp_path: Path) -> None:
    filings_index = tmp_path / "bdc_filings_index.csv"
    manifest = tmp_path / "manifest.jsonl"
    lock_dir = tmp_path / "locks"
    cache_dir = tmp_path / "html"
    accession = "0001234567-26-000001"
    _write_filings_index(
        filings_index,
        [
            {
                "cik": "0001234567",
                "entity_name": "Known BDC",
                "accession_number": accession,
                "form_type": "10-K",
                "filing_date": "2026-03-01",
                "report_date": "2025-12-31",
                "primary_document": "known.htm",
            }
        ],
    )
    path = bdc_html_cache_path("0001234567", accession, cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 32)

    client = FakeClient(fail=True)
    record = download_bdc_html(
        client=client,
        cik="1234567",
        accession=accession,
        filings_index_file=filings_index,
        cache_dir=cache_dir,
        manifest_file=manifest,
        lock_dir=lock_dir,
        min_bytes=16,
    )

    assert record["status"] == "cached"
    assert record["byte_count"] == 32
    assert client.urls == []
    assert _manifest_records(manifest)[0]["status"] == "cached"


def test_download_writes_final_file_and_manifest_receipt(tmp_path: Path) -> None:
    filings_index = tmp_path / "bdc_filings_index.csv"
    manifest = tmp_path / "manifest.jsonl"
    lock_dir = tmp_path / "locks"
    cache_dir = tmp_path / "html"
    accession = "0001234567-26-000001"
    content = b"<html>" + b"a" * 64 + b"</html>"
    _write_filings_index(
        filings_index,
        [
            {
                "cik": "0001234567",
                "entity_name": "Known BDC",
                "accession_number": accession,
                "form_type": "10-Q",
                "filing_date": "2026-05-01",
                "report_date": "2026-03-31",
                "primary_document": "known.htm",
            }
        ],
    )

    client = FakeClient(content=content)
    record = download_bdc_html(
        client=client,
        cik="0001234567",
        accession=accession.replace("-", ""),
        filings_index_file=filings_index,
        cache_dir=cache_dir,
        manifest_file=manifest,
        lock_dir=lock_dir,
        agent="test-agent",
        reason="unit_test",
        min_bytes=16,
    )

    path = bdc_html_cache_path("0001234567", accession, cache_dir=cache_dir)
    assert record["status"] == "downloaded"
    assert path.read_bytes() == content
    assert record["sha256"] == hashlib.sha256(content).hexdigest()
    assert client.urls == [
        "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/known.htm"
    ]
    manifest_record = _manifest_records(manifest)[0]
    assert manifest_record["agent"] == "test-agent"
    assert manifest_record["reason"] == "unit_test"
    assert manifest_record["status"] == "downloaded"


def test_short_content_fails_without_final_file(tmp_path: Path) -> None:
    filings_index = tmp_path / "bdc_filings_index.csv"
    manifest = tmp_path / "manifest.jsonl"
    lock_dir = tmp_path / "locks"
    cache_dir = tmp_path / "html"
    accession = "0001234567-26-000001"
    _write_filings_index(
        filings_index,
        [
            {
                "cik": "0001234567",
                "entity_name": "Known BDC",
                "accession_number": accession,
                "form_type": "10-K",
                "filing_date": "2026-03-01",
                "report_date": "2025-12-31",
                "primary_document": "known.htm",
            }
        ],
    )

    client = FakeClient(content=b"short")
    record = download_bdc_html(
        client=client,
        cik="0001234567",
        accession=accession,
        filings_index_file=filings_index,
        cache_dir=cache_dir,
        manifest_file=manifest,
        lock_dir=lock_dir,
        min_bytes=16,
    )

    path = bdc_html_cache_path("0001234567", accession, cache_dir=cache_dir)
    assert record["status"] == "failed"
    assert record["stage"] == "short_content"
    assert not path.exists()
    assert _manifest_records(manifest)[0]["stage"] == "short_content"


def test_accession_normalization_accepts_dashed_and_undashed() -> None:
    assert normalize_accession("0001234567-26-000001") == "0001234567-26-000001"
    assert normalize_accession("000123456726000001") == "0001234567-26-000001"
