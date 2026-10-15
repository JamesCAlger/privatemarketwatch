"""Contexts on the investment axis that are not schedule rows, told apart by their tags.

A filer can reuse its schedule members in other notes: a roll-forward of affiliate investments
(fair value only), a joint-venture or credit-facility note with amounts rounded to the hundred
thousand. Those contexts carry an identifier and a fair value, so they read as positions and are
published beside the schedule row (Barings Private Credit, 10-Q for 2023-06-30: seven roll-forward
contexts, 203.2M, e.g. 'Eclipse Business Capital, LLC ... LLC Units' 102,939 on c-906 beside the
schedule row; and 'Eclipse Business Capital Holdings LLC, Revolver, Funded' 2,600 tagged at
decimals -5).

A filer's wrapper names the test that fits its filings in ``source_encodings.schedule_row_tags``:

- ``cost_or_percent_unrounded``: a position carries a cost tag or a percent-of-net-assets tag, and
  none of its value columns (fair value, cost, principal) is filed only in a form rounded more
  coarsely than the thousand (decimals below -3).
- ``cost_or_percent``: the same without the rounding clause, for a filer whose schedule rows can
  carry a fair value tagged at decimals below -3 (T Series 10-K for 2024-12-31, c-277: 'Fetch
  Insurance Services, LLC ... 1,707 1,677 1,690 0.16', fair value 1,690,000 tagged at decimals -4
  beside an exact cost and a percent) and whose note rows carry neither cost nor percent.
- ``quantity_or_percent``: a position carries a principal, a share count or a percent tag (New
  Mountain: the non-accrual paragraph's 'aggregate cost basis of $45.3 million, an aggregate fair
  value of $36.9 million' is tagged with cost and fair value on the issuer's member, c-708).
- ``not_commitment_only``: a context that carries the commitment-note amount
  (InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount) and no cost tag is a row of the
  unfunded commitments table, not of the schedule (Jefferies Credit Partners).
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_VALUE_COLUMNS = ("fair_value", "cost", "principal_amount")


@lru_cache(maxsize=1)
def _tagged_ciks() -> dict[str, frozenset[str]]:
    from pipeline.source_encodings import load_encodings
    return {cik: frozenset(encoding["schedule_row_tags"]) for cik, encoding in load_encodings().items()
            if encoding.get("schedule_row_tags")}


TESTS = ("cost_or_percent_unrounded", "cost_or_percent", "quantity_or_percent", "not_commitment_only")
_COMMITMENT = "investmentcompanyfinancialcommitmenttoinvesteefutureamount"


def reads_schedule_row_tags(cik: Any) -> bool:
    return re.sub(r"\D", "", str(cik or "")).zfill(10) in _tagged_ciks()


def schedule_row_tests(cik: Any) -> frozenset[str]:
    return _tagged_ciks().get(re.sub(r"\D", "", str(cik or "")).zfill(10), frozenset())


def non_schedule_contexts(tree: Any, contexts: dict[str, dict[str, Any]], filing_meta: dict[str, str]) -> set[str]:
    """Investment contexts of this filing that are not schedule rows; empty for other filers."""
    if not reads_schedule_row_tags(filing_meta.get("cik", "")):
        return set()
    from pipeline.bdc_filings import _local_name, fair_value_aliases, match_concept_for
    tests = schedule_row_tests(filing_meta.get("cik", ""))
    aliases = fair_value_aliases(filing_meta.get("cik", ""))
    wanted = {cid for cid, info in contexts.items() if info.get("is_investment")}
    seen: dict[str, set[str]] = {}
    coarse: set[tuple[str, str]] = set()
    exact: set[tuple[str, str]] = set()
    for elem in tree.getroot().iter():
        context = elem.get("contextRef")
        if context not in wanted or not isinstance(elem.tag, str) or not (elem.text or "").strip():
            continue
        local = _local_name(elem.tag).lower()
        column = "commitment" if local == _COMMITMENT else match_concept_for(local, aliases)
        if column is None:
            continue
        seen.setdefault(context, set()).add(column)
        if column in _VALUE_COLUMNS:
            decimals = elem.get("decimals") or ""
            (coarse if re.fullmatch(r"-\d+", decimals) and int(decimals) < -3 else exact).add((context, column))
    # A value column filed only in rounded form marks a note row. A schedule row whose figures a note
    # repeats in rounded form on the same context keeps its exact facts and stays a position (Barings
    # 2023-06-30, c-838: cost 4,622,000 and fair value 4,534,000 at decimals -3 beside 4,600,000 and
    # 4,500,000 at -5; a note row is c-775, 2025-03-31: fair value at -3, cost 2,900,000 at -5 only).
    rounded = {context for context, _ in coarse - exact}
    dropped: set[str] = set()
    for context, columns in seen.items():
        if not columns & set(_VALUE_COLUMNS):
            continue
        if "cost_or_percent_unrounded" in tests and (not columns & {"cost", "pct_of_net_assets"} or context in rounded):
            dropped.add(context)
        if "cost_or_percent" in tests and not columns & {"cost", "pct_of_net_assets"}:
            dropped.add(context)
        if "quantity_or_percent" in tests and not columns & {"principal_amount", "shares_held", "pct_of_net_assets"}:
            dropped.add(context)
        if "not_commitment_only" in tests and "commitment" in columns and "cost" not in columns:
            dropped.add(context)
    return dropped


def drop_non_schedule_contexts(tree: Any, contexts: dict[str, dict[str, Any]], facts_by_context: dict[str, Any],
                               filing_meta: dict[str, str]) -> int:
    """Remove the non-schedule contexts from a facts mapping in place. Returns how many went."""
    dropped = non_schedule_contexts(tree, contexts, filing_meta)
    for context in dropped:
        facts_by_context.pop(context, None)
    return len(dropped)
