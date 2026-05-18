"""Generate cache-only BDC non-accrual position flags from cached XBRL.

Usage:
    python -m pipeline.extract_nonaccrual_flags
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.config import BDC_FILINGS_INDEX_FILE, OUTPUT_DIR
from pipeline.nonaccrual_evidence import extract_nonaccrual_candidates

logger = logging.getLogger(__name__)

NONACCRUAL_FLAGS_FILE = OUTPUT_DIR / "nonaccrual_flags.csv"
NONACCRUAL_CANDIDATES_FILE = OUTPUT_DIR / "nonaccrual_flag_candidates.csv"

FLAG_COLUMNS = [
    "cik",
    "report_date",
    "investment_identifier",
    "nonaccrual_source",
    "accession_number",
    "context_ids",
    "fact_ids",
]

CANDIDATE_COLUMNS = [
    "cik",
    "report_date",
    "accession_number",
    "investment_identifier",
    "nonaccrual_source",
    "accepted",
    "rejection_reason",
    "context_id",
    "fact_id",
    "footnote_text",
]


def _normalize_cik(cik: Any) -> str:
    digits = re.sub(r"\D", "", "" if cik is None else str(cik))
    return digits.zfill(10) if digits else ""


def _existing_path(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    path = Path(text)
    return str(path) if path.exists() else ""


def _source_summary(values: pd.Series) -> str:
    sources = sorted({str(v) for v in values.dropna().astype(str) if str(v)})
    if "dimension" in sources:
        return "dimension"
    return ";".join(sources)


def build_flags(filings_index: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    if filings_index.empty:
        return pd.DataFrame(columns=FLAG_COLUMNS), pd.DataFrame(columns=CANDIDATE_COLUMNS)

    for _, filing in filings_index.iterrows():
        xml_path = _existing_path(filing.get("xbrl_local_path", ""))
        report_date = str(filing.get("report_date", "") or "").strip()
        if not xml_path or not report_date:
            continue

        cik = _normalize_cik(filing.get("cik", ""))
        accession = str(filing.get("accession_number", "") or "").strip()
        try:
            rows.extend(
                extract_nonaccrual_candidates(
                    xml_path,
                    cik=cik,
                    report_date=report_date,
                    accession_number=accession,
                )
            )
        except Exception as exc:
            logger.warning("Failed to parse non-accrual candidates for %s %s: %s",
                           cik, accession, exc)

    candidates = pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)
    if candidates.empty:
        return pd.DataFrame(columns=FLAG_COLUMNS), candidates

    accepted = candidates[candidates["accepted"] == True].copy()  # noqa: E712
    if accepted.empty:
        return pd.DataFrame(columns=FLAG_COLUMNS), candidates

    flags = (
        accepted
        .groupby(["cik", "report_date", "investment_identifier"], dropna=False)
        .agg(
            nonaccrual_source=("nonaccrual_source", _source_summary),
            accession_number=("accession_number", lambda s: "|".join(sorted(set(s.astype(str))))),
            context_ids=("context_id", lambda s: "|".join(sorted({v for v in s.astype(str) if v}))),
            fact_ids=("fact_id", lambda s: "|".join(sorted({v for v in s.astype(str) if v}))),
        )
        .reset_index()
    )
    return flags[FLAG_COLUMNS], candidates


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not BDC_FILINGS_INDEX_FILE.exists():
        raise FileNotFoundError(BDC_FILINGS_INDEX_FILE)
    filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
    flags, candidates = build_flags(filings_index)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    flags.to_csv(NONACCRUAL_FLAGS_FILE, index=False)
    candidates.to_csv(NONACCRUAL_CANDIDATES_FILE, index=False)

    accepted_count = int(candidates["accepted"].sum()) if "accepted" in candidates else 0
    rejected_count = len(candidates) - accepted_count
    logger.info("Wrote %d non-accrual flags to %s",
                len(flags), NONACCRUAL_FLAGS_FILE.as_posix())
    logger.info("Wrote %d candidates (%d accepted, %d rejected) to %s",
                len(candidates), accepted_count, rejected_count,
                NONACCRUAL_CANDIDATES_FILE.as_posix())
    return flags, candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
