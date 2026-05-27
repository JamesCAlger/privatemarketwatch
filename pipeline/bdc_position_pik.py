"""Position-level BDC PIK income/accrual evidence from cached XBRL.

This module deliberately extracts current PIK payment/accrual evidence from
source facts only. It does not infer current PIK status from contractual
``pik_rate`` terms.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import pandas as pd
from lxml import etree

from pipeline.bdc_filings import _local_name, _parse_xbrl_contexts
from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_POSITION_PIK_EVIDENCE_FILE,
)

logger = logging.getLogger(__name__)

PIK_EVIDENCE_COLUMNS = [
    "cik", "entity_name", "accession_number", "form_type",
    "filing_date", "report_date", "period", "concept",
    "context_id", "dimensions_raw", "matched_identifier",
    "amount", "unit", "decimals", "evidence_kind", "position_level",
]

_PIK_WORD_RE = re.compile(r"(paidinkind|paymentinkind|\bpik\b)", re.IGNORECASE)
_INCOME_WORD_RE = re.compile(
    r"(income|interest|accrual|accrued|capitali[sz]|deferred|receivable)",
    re.IGNORECASE,
)
_TERMS_ONLY_RE = re.compile(
    r"(rate|interestrate|coupon|spread|percentage|percent|yield)",
    re.IGNORECASE,
)


def _is_pik_current_concept(local_name: str) -> bool:
    """Return true for PIK income/accrual/capitalization facts, not terms."""
    compact = re.sub(r"[^A-Za-z0-9]", "", str(local_name or ""))
    if not _PIK_WORD_RE.search(compact):
        return False
    explicit_current = re.search(r"(income|accrual|accrued|capitali[sz]|deferred|receivable)", compact, re.IGNORECASE)
    if _TERMS_ONLY_RE.search(compact) and not explicit_current:
        return False
    return bool(_INCOME_WORD_RE.search(compact))


def _evidence_kind(local_name: str, amount: float) -> str:
    base = "bdc_position_pik_income_positive" if amount > 0 else "bdc_position_pik_income_zero"
    lower = str(local_name or "").lower()
    if "capital" in lower:
        return base.replace("income", "capitalization")
    if "accru" in lower:
        return base.replace("income", "accrual")
    return base


def _parse_numeric(raw: str) -> float | None:
    try:
        return float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _extract_pik_evidence_facts(
    tree: etree._ElementTree,
    contexts: dict[str, dict],
    filing_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Extract PIK current-payment evidence facts from one parsed XBRL tree."""
    records: list[dict[str, Any]] = []
    root = tree.getroot()

    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if not ctx_ref or ctx_ref not in contexts:
            continue

        nil = elem.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
        if nil and nil.lower() == "true":
            continue

        local = _local_name(elem.tag)
        if not _is_pik_current_concept(local):
            continue

        amount = _parse_numeric(elem.text or "")
        if amount is None:
            continue

        ctx = contexts[ctx_ref]
        dimensions_raw = str(ctx.get("dimensions_raw", "") or "")
        matched_identifier = str(ctx.get("investment_identifier", "") or "")
        position_level = bool(ctx.get("is_investment") and matched_identifier)
        kind = _evidence_kind(local, amount) if position_level else "bdc_fund_level_pik_income"

        records.append({
            "cik": filing_meta.get("cik", ""),
            "entity_name": filing_meta.get("entity_name", ""),
            "accession_number": filing_meta.get("accession_number", ""),
            "form_type": filing_meta.get("form_type", ""),
            "filing_date": filing_meta.get("filing_date", ""),
            "report_date": filing_meta.get("report_date", ""),
            "period": ctx.get("period", ""),
            "concept": local,
            "context_id": ctx_ref,
            "dimensions_raw": dimensions_raw,
            "matched_identifier": matched_identifier,
            "amount": amount,
            "unit": elem.get("unitRef", "") or "",
            "decimals": elem.get("decimals", "") or "",
            "evidence_kind": kind,
            "position_level": position_level,
        })

    return records


def extract_bdc_position_pik_evidence(
    filings_index: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Extract BDC position-level PIK evidence from cached XBRL files only."""
    t0 = time.time()

    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            logger.warning("No filings index found at %s", BDC_FILINGS_INDEX_FILE)
            return pd.DataFrame(columns=PIK_EVIDENCE_COLUMNS)
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)

    required = {"xbrl_download_status", "xbrl_local_path"}
    if not required.issubset(filings_index.columns):
        logger.warning("Filings index lacks cached XBRL path/status columns")
        return pd.DataFrame(columns=PIK_EVIDENCE_COLUMNS)

    cached = filings_index[
        filings_index["xbrl_download_status"].isin(["cached", "downloaded"])
        & filings_index["xbrl_local_path"].notna()
        & (filings_index["xbrl_local_path"] != "")
    ].copy()

    all_records: list[dict[str, Any]] = []
    parsed = 0
    errors = 0
    for _, row in cached.iterrows():
        xml_path = row["xbrl_local_path"]
        filing_meta = {
            "cik": str(row.get("cik", "")),
            "entity_name": str(row.get("entity_name", "")),
            "accession_number": str(row.get("accession_number", "")),
            "form_type": str(row.get("form_type", "")),
            "filing_date": str(row.get("filing_date", "")),
            "report_date": str(row.get("report_date", "")),
        }
        try:
            tree = etree.parse(xml_path)
            contexts = _parse_xbrl_contexts(tree)
            all_records.extend(_extract_pik_evidence_facts(tree, contexts, filing_meta))
            parsed += 1
        except Exception as exc:
            errors += 1
            if errors <= 5:
                logger.debug("Error parsing %s for BDC PIK evidence: %s", xml_path, exc)

    df = pd.DataFrame(all_records)
    for col in PIK_EVIDENCE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[PIK_EVIDENCE_COLUMNS].sort_values(
        ["cik", "report_date", "accession_number", "context_id", "concept"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    BDC_POSITION_PIK_EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(BDC_POSITION_PIK_EVIDENCE_FILE, index=False)

    position_rows = int((df["position_level"].astype(str).str.lower() == "true").sum()) if not df.empty else 0
    logger.info(
        "BDC PIK evidence: %d rows (%d position-level) from %d filings (%d errors) in %.1f s",
        len(df), position_rows, parsed, errors, time.time() - t0,
    )
    return df
