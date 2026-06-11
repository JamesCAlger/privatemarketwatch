"""Audited SEC download helpers for opt-in agent workflows.

The normal pipeline should remain cache-first. These helpers provide the narrow
path for explicitly allowed SEC HTML downloads: known accession only, shared
cross-process rate limit, per-target lock, atomic write, and JSONL receipt.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pipeline import config

_ACCESSION_DASHED_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_ACCESSION_NODASH_RE = re.compile(r"^\d{18}$")
_PRIMARY_DOC_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MIN_HTML_BYTES = 1024


class SecDownloadError(ValueError):
    """Raised when an SEC download request violates the guarded contract."""


class FileLock:
    """Small cross-process lock using exclusive file creation."""

    def __init__(
        self,
        path: Path,
        *,
        timeout_seconds: float = 30.0,
        stale_seconds: float = 300.0,
    ) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.stale_seconds = stale_seconds
        self._fd: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_seconds
        payload = json.dumps(
            {"pid": os.getpid(), "created_at": _now_iso()},
            sort_keys=True,
        )
        while True:
            try:
                self._fd = os.open(
                    str(self.path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._fd, payload.encode("utf-8"))
                return self
            except FileExistsError:
                self._remove_stale_lock()
                if time.time() >= deadline:
                    raise TimeoutError(f"Timed out waiting for lock: {self.path}")
                time.sleep(0.1)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _remove_stale_lock(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age < self.stale_seconds:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(10) if digits else ""


def normalize_accession(value: Any) -> str:
    text = str(value or "").strip()
    if _ACCESSION_DASHED_RE.match(text):
        return text
    digits = re.sub(r"\D", "", text)
    if _ACCESSION_NODASH_RE.match(digits):
        return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"
    raise SecDownloadError(f"Invalid accession number: {value!r}")


def accession_no_dashes(accession: str) -> str:
    return normalize_accession(accession).replace("-", "")


def bdc_html_cache_path(
    cik: str,
    accession: str,
    *,
    cache_dir: Path = config.BDC_HTML_CACHE_DIR,
) -> Path:
    cik_stripped = normalize_cik(cik).lstrip("0") or "0"
    return cache_dir / cik_stripped / f"{accession_no_dashes(accession)}.html"


def load_bdc_filing_row(
    cik: str,
    accession: str,
    *,
    filings_index_file: Path = config.BDC_FILINGS_INDEX_FILE,
) -> dict[str, str] | None:
    """Return the BDC filings-index row for a normalized CIK/accession pair."""
    cik_norm = normalize_cik(cik)
    accession_norm = normalize_accession(accession)
    if not filings_index_file.exists():
        return None

    with filings_index_file.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            row_cik = normalize_cik(row.get("cik", ""))
            try:
                row_accession = normalize_accession(row.get("accession_number", ""))
            except SecDownloadError:
                continue
            if row_cik == cik_norm and row_accession == accession_norm:
                return {k: (v or "") for k, v in row.items()}
    return None


def download_bdc_html(
    *,
    client: Any,
    cik: str,
    accession: str,
    primary_doc: str = "",
    agent: str = "",
    reason: str = "",
    filings_index_file: Path = config.BDC_FILINGS_INDEX_FILE,
    cache_dir: Path = config.BDC_HTML_CACHE_DIR,
    manifest_file: Path = config.SEC_DOWNLOAD_MANIFEST_FILE,
    lock_dir: Path = config.SEC_DOWNLOAD_LOCK_DIR,
    doc_types: tuple[str, ...] = ("10-K", "10-K/A", "10-Q", "10-Q/A"),
    min_bytes: int = _MIN_HTML_BYTES,
) -> dict[str, Any]:
    """Download one known BDC filing HTML file through the audited path.

    Returns a receipt dict with ``status`` in ``cached``, ``downloaded``, or
    ``failed``. This function intentionally records failed attempts too.
    """
    base_record = {
        "timestamp": _now_iso(),
        "source": "bdc",
        "agent": agent,
        "reason": reason,
        "cik": "",
        "accession_number": "",
        "status": "",
        "stage": "",
        "url": "",
        "cache_path": "",
        "byte_count": 0,
        "sha256": "",
        "error": "",
    }
    try:
        cik_norm = normalize_cik(cik)
        accession_norm = normalize_accession(accession)
        row = load_bdc_filing_row(
            cik_norm,
            accession_norm,
            filings_index_file=filings_index_file,
        )
        dest = bdc_html_cache_path(cik_norm, accession_norm, cache_dir=cache_dir)
        base_record.update(
            {
                "cik": cik_norm,
                "accession_number": accession_norm,
                "cache_path": _display_path(dest),
            }
        )
        if row is None:
            return _record_failure(
                base_record,
                "unknown_accession",
                "CIK/accession pair not present in bdc_filings_index.csv",
                manifest_file,
                lock_dir,
            )

        primary = (primary_doc or row.get("primary_document") or "").strip()
        lock_name = f"bdc_html_{cik_norm}_{accession_no_dashes(accession_norm)}.lock"
        with FileLock(lock_dir / lock_name):
            if dest.exists() and dest.stat().st_size >= min_bytes:
                record = {
                    **base_record,
                    "timestamp": _now_iso(),
                    "status": "cached",
                    "stage": "cache_hit",
                    "byte_count": dest.stat().st_size,
                    "sha256": _sha256_file(dest),
                }
                _append_manifest(record, manifest_file, lock_dir)
                return record

            url = ""
            if primary:
                if not _PRIMARY_DOC_RE.match(primary):
                    return _record_failure(
                        base_record,
                        "invalid_primary_document",
                        f"Unsafe primary document name: {primary!r}",
                        manifest_file,
                        lock_dir,
                    )
                url = _bdc_archives_url(cik_norm, accession_norm, primary)
            else:
                _rate_limit(lock_dir)
                resolved = client.resolve_filing_document_url(
                    cik_norm,
                    accession_norm,
                    doc_types=doc_types,
                )
                url = str(resolved or "")

            if not _is_allowed_sec_archives_url(url):
                return _record_failure(
                    base_record,
                    "invalid_url",
                    f"Resolved URL is outside the allowed SEC archives path: {url}",
                    manifest_file,
                    lock_dir,
                )

            try:
                _rate_limit(lock_dir)
                resp = client.get(url)
                content = bytes(resp.content)
            except Exception as exc:
                return _record_failure(
                    {**base_record, "url": url},
                    "request_failed",
                    str(exc),
                    manifest_file,
                    lock_dir,
                )

            if len(content) < min_bytes:
                return _record_failure(
                    {**base_record, "url": url, "byte_count": len(content)},
                    "short_content",
                    f"Downloaded content shorter than {min_bytes} bytes",
                    manifest_file,
                    lock_dir,
                )

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f"{dest.name}.tmp.{os.getpid()}")
            try:
                with tmp.open("wb") as f:
                    f.write(content)
                tmp.replace(dest)
            finally:
                if tmp.exists():
                    tmp.unlink()

            record = {
                **base_record,
                "timestamp": _now_iso(),
                "status": "downloaded",
                "stage": "downloaded",
                "url": url,
                "byte_count": dest.stat().st_size,
                "sha256": _sha256_file(dest),
            }
            _append_manifest(record, manifest_file, lock_dir)
            return record
    except Exception as exc:
        record = {
            **base_record,
            "timestamp": _now_iso(),
            "status": "failed",
            "stage": "guard_exception",
            "error": str(exc),
        }
        _append_manifest(record, manifest_file, lock_dir)
        return record


def _bdc_archives_url(cik: str, accession: str, primary_doc: str) -> str:
    cik_stripped = normalize_cik(cik).lstrip("0") or "0"
    acc_no_dashes = accession_no_dashes(accession)
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_stripped}/{acc_no_dashes}/{primary_doc}"
    )


def _is_allowed_sec_archives_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.netloc.lower() != "www.sec.gov":
        return False
    return parsed.path.startswith("/Archives/edgar/data/")


def _rate_limit(lock_dir: Path) -> None:
    lock_dir.mkdir(parents=True, exist_ok=True)
    state_file = lock_dir / "sec_last_request.txt"
    with FileLock(lock_dir / "sec_global_rate.lock", timeout_seconds=30.0):
        last = 0.0
        if state_file.exists():
            try:
                last = float(state_file.read_text(encoding="utf-8").strip() or "0")
            except ValueError:
                last = 0.0
        wait = config.REQUEST_DELAY_SECONDS - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        state_file.write_text(str(time.time()), encoding="utf-8")


def _record_failure(
    record: dict[str, Any],
    stage: str,
    error: str,
    manifest_file: Path,
    lock_dir: Path,
) -> dict[str, Any]:
    failed = {
        **record,
        "timestamp": _now_iso(),
        "status": "failed",
        "stage": stage,
        "error": error,
    }
    _append_manifest(failed, manifest_file, lock_dir)
    return failed


def _append_manifest(
    record: dict[str, Any],
    manifest_file: Path,
    lock_dir: Path,
) -> None:
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(lock_dir / "sec_download_manifest.lock", timeout_seconds=30.0):
        with manifest_file.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(config.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
