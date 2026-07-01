"""Instrument-type classification for BDC holdings (text fallback).

The text analogue of :mod:`pipeline.lien_classification`. The reconciliation-gated
XBRL-member capture lives in the instrument-type breakdown
(:func:`pipeline.bdc_sector_breakdown.extract_bdc_instrument_type_breakdown`);
this fills the PER-POSITION ``instrument_type`` from the row text
(``instrument_description``) and the ``bdc_investment_identifier`` typed-member
string, for the filers/positions that lack a dimensional member.

Categories: ``Delayed Draw Term Loan`` | ``Revolver`` | ``Unitranche`` |
``Term Loan`` (returns None when no keyword matches -- e.g. equity, bonds).
"""
from __future__ import annotations

import logging
from typing import Optional

from pipeline.classification import _sql_keyword_check

logger = logging.getLogger(__name__)

# Keyword lists, checked in priority order. Delayed-draw is checked BEFORE term
# loan because "delayed draw term loan" contains "term loan"; revolver and
# unitranche are distinct products.
_DELAYED_DRAW_KEYWORDS: list[str] = ["delayed draw", "delayed-draw", "ddtl"]
_REVOLVER_KEYWORDS: list[str] = ["revolver", "revolving"]
_UNITRANCHE_KEYWORDS: list[str] = ["unitranche"]
_TERM_LOAN_KEYWORDS: list[str] = ["term loan", "term-loan"]


def _sql_classify_instrument_type() -> str:
    """Generate DuckDB CASE WHEN for instrument-type classification.

    Searches ``_combined_fund_text`` (issuer_name + instrument_description) and
    ``bdc_investment_identifier``. Returns NULL when no keyword is found.
    """
    _bid = "LOWER(COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''))"

    def _both(keywords: list[str]) -> str:
        return (f"({_sql_keyword_check('_combined_fund_text', keywords)} "
                f"OR {_sql_keyword_check(_bid, keywords)})")

    return f"""CASE
  WHEN {_both(_DELAYED_DRAW_KEYWORDS)} THEN 'Delayed Draw Term Loan'
  WHEN {_both(_REVOLVER_KEYWORDS)} THEN 'Revolver'
  WHEN {_both(_UNITRANCHE_KEYWORDS)} THEN 'Unitranche'
  WHEN {_both(_TERM_LOAN_KEYWORDS)} THEN 'Term Loan'
  ELSE NULL
END"""


def classify_instrument_type(
    instrument_desc: Optional[str],
    bdc_investment_identifier: Optional[str] = None,
    issuer_name: Optional[str] = None,
) -> Optional[str]:
    """Classify instrument type from text fields (pure-Python; for unit tests).

    Returns 'Delayed Draw Term Loan' | 'Revolver' | 'Unitranche' | 'Term Loan'
    or None. Mirrors the SQL priority order exactly.
    """
    combined = ((issuer_name or "").lower() + " " + (instrument_desc or "").lower())
    bid = (bdc_investment_identifier or "").lower()

    for kw in _DELAYED_DRAW_KEYWORDS:
        if kw in combined or kw in bid:
            return "Delayed Draw Term Loan"
    for kw in _REVOLVER_KEYWORDS:
        if kw in combined or kw in bid:
            return "Revolver"
    for kw in _UNITRANCHE_KEYWORDS:
        if kw in combined or kw in bid:
            return "Unitranche"
    for kw in _TERM_LOAN_KEYWORDS:
        if kw in combined or kw in bid:
            return "Term Loan"
    return None
