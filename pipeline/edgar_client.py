"""Rate-limited HTTP client for SEC EDGAR."""

import logging
import re
import time
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pipeline.config import (
    MAX_RETRIES,
    REQUEST_DELAY_SECONDS,
    RETRY_BACKOFF_FACTOR,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


class EdgarClient:
    """HTTP client that respects SEC EDGAR rate limits."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })

        # Retry adapter for transient errors
        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=RETRY_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._last_request_time: float = 0.0

    def _rate_limit(self) -> None:
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY_SECONDS:
            time.sleep(REQUEST_DELAY_SECONDS - elapsed)
        self._last_request_time = time.time()

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Send a rate-limited GET request."""
        self._rate_limit()
        logger.debug("GET %s", url)
        resp = self.session.get(url, timeout=60, **kwargs)
        resp.raise_for_status()
        return resp

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """GET request returning parsed JSON."""
        resp = self.get(url, **kwargs)
        return resp.json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        """GET request returning response text."""
        resp = self.get(url, **kwargs)
        return resp.text

    def download_file(self, url: str, dest_path: Any) -> None:
        """Download a file to *dest_path*."""
        from pathlib import Path

        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        self._rate_limit()
        logger.info("Downloading %s -> %s", url, dest_path)
        with self.session.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # EFTS full-text search with pagination
    # ------------------------------------------------------------------
    def search_filings(
        self,
        query: str | None = None,
        form_type: str | None = None,
        date_range: tuple[str, str] | None = None,
        max_results: int = 500,
    ) -> list[dict]:
        """Search EDGAR full-text search (EFTS) and paginate through results.

        Parameters
        ----------
        query : str, optional
            Free-text search query.
        form_type : str, optional
            Filing form type (e.g. "N-54A").
        date_range : tuple of (start, end) date strings "YYYY-MM-DD", optional
        max_results : int
            Maximum total hits to return.

        Returns
        -------
        list of dicts
            Each dict has keys like 'file_num', 'entity_name', 'cik', etc.
        """
        base_url = "https://efts.sec.gov/LATEST/search-index"
        all_hits: list[dict] = []
        start = 0
        page_size = 100  # EFTS default max

        while start < max_results:
            params: dict[str, Any] = {
                "from": start,
                "size": min(page_size, max_results - start),
            }
            if query:
                params["q"] = query
            if form_type:
                params["forms"] = form_type
            if date_range:
                params["startdt"] = date_range[0]
                params["enddt"] = date_range[1]

            data = self.get_json(base_url, params=params)
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break
            all_hits.extend(hits)
            total_available = data.get("hits", {}).get("total", {})
            if isinstance(total_available, dict):
                total_available = total_available.get("value", 0)
            if start + page_size >= total_available:
                break
            start += page_size

        logger.info(
            "EFTS search returned %d results (query=%s, form=%s)",
            len(all_hits), query, form_type,
        )
        return all_hits

    def get_company_submissions(self, cik: str) -> dict:
        """Fetch company submissions JSON for a given CIK."""
        cik_padded = cik.zfill(10)
        url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        return self.get_json(url)

    # ------------------------------------------------------------------
    # Safe GET (returns None on HTTP errors instead of raising)
    # ------------------------------------------------------------------
    def get_safe(self, url: str, **kwargs: Any) -> requests.Response | None:
        """Like get() but returns None on HTTP errors instead of raising."""
        try:
            return self.get(url, **kwargs)
        except requests.HTTPError as exc:
            logger.debug("GET %s returned %s", url, exc.response.status_code if exc.response else exc)
            return None

    # ------------------------------------------------------------------
    # Quarterly index scan — find all N-2 filings from full-index files
    # ------------------------------------------------------------------
    def scan_quarterly_indices(
        self,
        since_year: int = 2015,
        form_types: tuple[str, ...] | None = None,
    ) -> list[dict]:
        """Scan EDGAR quarterly company.idx files for filings of given form types.

        Iterates https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{qtr}/company.idx
        from *since_year* Q1 through the current quarter.

        Returns list of dicts with keys: cik, company_name, accession_number,
        filing_date, form_type.
        """
        if form_types is None:
            form_types = ("N-2", "N-2/A", "N-2ASR", "N-2MEF")

        form_set = set(form_types)
        now = datetime.now()
        current_year = now.year
        current_qtr = (now.month - 1) // 3 + 1

        results: list[dict] = []
        seen: set[tuple[str, str]] = set()  # (cik, accession_number)

        for year in range(since_year, current_year + 1):
            max_qtr = current_qtr if year == current_year else 4
            for qtr in range(1, max_qtr + 1):
                url = (
                    f"https://www.sec.gov/Archives/edgar/full-index/"
                    f"{year}/QTR{qtr}/company.idx"
                )
                resp = self.get_safe(url)
                if resp is None:
                    logger.debug("Index not available: %s", url)
                    continue

                text = resp.text
                # company.idx is fixed-width: skip header lines (lines starting with
                # dashes or containing "Company Name")
                in_data = False
                count = 0
                for line in text.splitlines():
                    if not in_data:
                        if line.startswith("---"):
                            in_data = True
                        continue

                    # Fixed-width format:
                    # Company Name          Form Type  CIK         Date Filed  Filename
                    # Cols: 0-61 name, 62-73 form, 74-85 CIK, 86-97 date, 98+ filename
                    if len(line) < 98:
                        continue

                    company_name = line[:62].strip()
                    form_type = line[62:74].strip()
                    cik_str = line[74:86].strip()
                    filing_date = line[86:98].strip()
                    filename = line[98:].strip()

                    if form_type not in form_set:
                        continue

                    # Extract accession number from filename
                    # e.g. edgar/data/1234567/0001234567-23-012345.txt
                    parts = filename.replace("\\", "/").split("/")
                    acc_file = parts[-1] if parts else ""
                    accession = acc_file.replace(".txt", "")

                    key = (cik_str, accession)
                    if key in seen:
                        continue
                    seen.add(key)

                    results.append({
                        "cik": cik_str,
                        "company_name": company_name,
                        "accession_number": accession,
                        "filing_date": filing_date,
                        "form_type": form_type,
                    })
                    count += 1

                if count:
                    logger.info("  Index %d/QTR%d: %d %s filings",
                                year, qtr, count, "/".join(form_types))

        logger.info("Quarterly index scan: %d total filings from %d to %d",
                     len(results), since_year, current_year)
        return results

    # ------------------------------------------------------------------
    # Resolve the primary document URL from a filing index page
    # ------------------------------------------------------------------
    def resolve_filing_document_url(
        self,
        cik: str,
        accession_number: str,
        doc_types: tuple[str, ...] | None = None,
    ) -> str | None:
        """Resolve the primary document URL for a filing.

        Fetches the filing index page and finds the main document link.
        Returns full URL or None.
        """
        if doc_types is None:
            doc_types = ("N-2", "N-2/A", "N-2 POS", "N-2 MEF")

        cik_stripped = cik.lstrip("0") or "0"
        acc_nodash = accession_number.replace("-", "")
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_stripped}/{acc_nodash}/{accession_number}-index.htm"
        )

        resp = self.get_safe(index_url)
        if resp is None:
            return None

        html = resp.text

        # Parse table rows looking for document type matches
        # Pattern: <td>DOC_TYPE</td> ... <a href="...">
        doc_type_lower = {dt.lower() for dt in doc_types}

        # Find all table rows
        row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        href_pattern = re.compile(r'<a\s+href="([^"]+)"', re.IGNORECASE)
        td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)

        fallback_url = None

        for row_match in row_pattern.finditer(html):
            row_html = row_match.group(1)
            tds = td_pattern.findall(row_html)
            # Clean HTML tags from td content
            td_texts = [re.sub(r"<[^>]+>", "", td).strip() for td in tds]

            # Check if any td matches our doc types
            row_has_type = any(
                t.lower() in doc_type_lower for t in td_texts
            )

            href_match = href_pattern.search(row_html)
            if href_match:
                href = href_match.group(1)

                # Handle iXBRL wrapper
                if "/ix?doc=" in href:
                    href = href.split("/ix?doc=")[-1]

                # Make absolute URL
                if href.startswith("/"):
                    href = f"https://www.sec.gov{href}"
                elif not href.startswith("http"):
                    href = (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{cik_stripped}/{acc_nodash}/{href}"
                    )

                if row_has_type:
                    return href

                # Track first non-exhibit .htm as fallback
                if (
                    fallback_url is None
                    and href.lower().endswith((".htm", ".html"))
                    and "ex" not in href.lower().split("/")[-1][:3]
                ):
                    fallback_url = href

        return fallback_url

    # ------------------------------------------------------------------
    # Partial download (first N bytes of a document)
    # ------------------------------------------------------------------
    def download_partial(self, url: str, max_bytes: int = 150_000) -> str | None:
        """Download only the first *max_bytes* of a document.

        Uses HTTP Range header. Returns text on success, None on failure.
        """
        self._rate_limit()
        try:
            resp = self.session.get(
                url,
                headers={"Range": f"bytes=0-{max_bytes}"},
                timeout=30,
            )
            self._last_request_time = time.time()
            if resp.status_code in (200, 206):
                return resp.text
            return None
        except Exception as exc:
            logger.debug("Partial download failed for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # XBRL company facts — IntervalFundFlag scan
    # ------------------------------------------------------------------
    def scan_xbrl_interval_fund_flags(self) -> list[dict]:
        """Scan XBRL frames API for entities that reported IntervalFundFlag = true.

        Tries multiple calendar years via the frames endpoint:
        https://data.sec.gov/api/xbrl/frames/cef/IntervalFundFlag/bool/CY{year}.json
        """
        results: list[dict] = []
        seen_ciks: set[str] = set()
        now = datetime.now()

        for year in range(now.year, now.year - 5, -1):
            url = (
                f"https://data.sec.gov/api/xbrl/frames/"
                f"cef/IntervalFundFlag/bool/CY{year}.json"
            )
            resp = self.get_safe(url)
            if resp is None:
                logger.debug("XBRL frames not available for CY%d", year)
                continue

            try:
                data = resp.json()
            except Exception:
                continue

            entries = data.get("data", [])
            for entry in entries:
                cik = str(entry.get("cik", ""))
                if not cik or cik in seen_ciks:
                    continue

                val = entry.get("val")
                # val can be True/1/"true" for interval fund flag
                if val in (True, 1, "true", "1"):
                    seen_ciks.add(cik)
                    results.append({
                        "cik": cik,
                        "entity_name": entry.get("entityName", ""),
                        "concept": "IntervalFundFlag",
                        "value": val,
                        "filing_date": entry.get("end", ""),
                    })

            logger.info("XBRL frames CY%d: %d entries, %d interval flags",
                        year, len(entries), len([e for e in entries
                        if e.get("val") in (True, 1, "true", "1")]))

        logger.info("XBRL IntervalFundFlag scan: %d unique CIKs", len(results))
        return results
