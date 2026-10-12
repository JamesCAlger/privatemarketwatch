"""A filer that tags a loan's coupon, cash margin and PIK margin as three separate facts.

BlackRock Private Credit Fund, 'IQN Holding ... 2.63 % Cash + 3.13 % PIK 9.45 %': the context
carries InvestmentInterestRatePaidInCash 0.0263 (the cash margin), InvestmentInterestRatePaidInKind
0.0313 (the PIK margin) and InvestmentInterestRate 0.0945 (the total coupon). The extractor maps
both rate concepts to ``interest_rate`` and keeps the first, so the coupon was discarded and the
cash margin published as the rate (5.76 after the PIK was added).

A filer whose wrapper sets ``source_encodings.rate_tag_reading: ["coupon_with_margins"]`` has the
plain tag read as the rate and the paid-in-cash tag as the cash margin (``basis_spread``, where no
spread is tagged). A context with no plain tag is read as before.

``["cash_rate_with_plain_spread"]`` is the opposite filer: the paid-in-cash tag is the cash rate
and, in the filings where a plain tag sits beside it with no spread tag, the plain tag is the
spread (Stepstone Private Credit, 10-K 2024-12-31, 'Creek Parent ... 1M SOFR + 5.25 % / 0.75 %
12.75 %': InvestmentInterestRate 0.0525, InvestmentInterestRatePaidInCash 0.1275; the pipeline
kept the first rate fact and published 5.25 as the rate on 618 to 1,050 rows a quarter).
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

PAID_IN_CASH = "investmentinterestratepaidincash"
_HELD = "_cash_margin"


@lru_cache(maxsize=1)
def _readings() -> dict[str, str]:
    from pipeline.source_encodings import load_encodings
    return {cik: encoding["rate_tag_reading"][0] for cik, encoding in load_encodings().items()
            if encoding.get("rate_tag_reading")}


def _margin_ciks() -> frozenset[str]:
    # every fund whose paid-in-cash facts are held until the context is complete
    return frozenset(_readings())


def reading(cik: Any) -> str:
    """'coupon_with_margins', 'cash_rate_with_plain_spread' or '' for the fund."""
    return _readings().get(re.sub(r"\D", "", str(cik or "")).zfill(10), "")


def reads_margins(cik: Any) -> bool:
    return re.sub(r"\D", "", str(cik or "")).zfill(10) in _margin_ciks()


def hold_cash_margin(facts: dict[str, Any], value: Any) -> None:
    """Keep a paid-in-cash fact aside until the context is complete (first fact wins)."""
    facts.setdefault(_HELD, value)


def settle(facts_by_context: dict[str, dict[str, Any]], provenance: dict[str, dict[str, dict]] | None = None,
           mode: str = "coupon_with_margins") -> int:
    """Place each held paid-in-cash fact. Returns the contexts where a plain tag sat beside it."""
    kept = 0
    if mode == "cash_rate_with_plain_spread":
        for context, facts in facts_by_context.items():
            if _HELD not in facts:
                continue
            cash = facts.pop(_HELD)
            plain = facts.get("interest_rate")
            marks = provenance.setdefault(context, {}) if provenance is not None else {}
            plain_mark = marks.get("interest_rate")
            facts["interest_rate"] = cash
            facts["interest_rate_concept"] = "paid_in_cash"
            entry: dict[str, Any] = {"c": PAID_IN_CASH}
            if isinstance(cash, (int, float)):
                entry["r"] = cash
            marks["interest_rate"] = entry
            if plain is not None:
                kept += 1
                if facts.get("basis_spread") is None:
                    facts["basis_spread"] = plain
                    marks["basis_spread"] = plain_mark if isinstance(plain_mark, dict) else (
                        {"c": "investmentinterestrate", "r": plain} if isinstance(plain, (int, float))
                        else {"c": "investmentinterestrate"})
        return kept
    for context, facts in facts_by_context.items():
        if _HELD not in facts:
            continue
        margin = facts.pop(_HELD)
        entry: dict[str, Any] = {"c": PAID_IN_CASH}
        if isinstance(margin, (int, float)):
            entry["r"] = margin
        if facts.get("interest_rate") is None:
            facts["interest_rate"] = margin
            facts["interest_rate_concept"] = "paid_in_cash"
            if provenance is not None:
                provenance.setdefault(context, {})["interest_rate"] = entry
            continue
        kept += 1
        if facts.get("basis_spread") is None:
            facts["basis_spread"] = margin
            if provenance is not None:
                provenance.setdefault(context, {})["basis_spread"] = entry
    return kept
