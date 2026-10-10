"""Schedule rows that are undrawn commitments, netted to what the fund holds.

A filer can list an undrawn commitment in its schedule as a row at the full committed amount
and subtract the commitments again as one line per section (KKR FS Income Trust, 10-Q for
2026-03-31: "Sotheby's, Revolver (i) ... 31,849 31,849 31,849", footnote (i) 'Security is an
unfunded commitment', then 'Unfunded Loan Commitments (430,150) (430,150)' before the section's
net total). The rows then sum to more than the filed investments total. The same filing tags
each commitment in its commitments note (InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount
on the investment's own member).

A filer whose wrapper sets ``source_encodings.unfunded_rows: ["net_of_tagged_commitment"]`` has
each such row netted: cost and fair value are reduced by the tagged commitment, the principal
keeps the committed amount. A schedule row is the commitment's row only when it is on the same
date, its name starts with the commitment's name, and its cost equals the tagged amount; among
several such rows the one whose principal also equals it is taken. A commitment with no such row is left alone.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

COMMITMENT_CONCEPT = "investmentcompanyfinancialcommitmenttoinvesteefutureamount"
NET_EVENT = "net_of_commitment:"
_AMOUNT_RE = re.compile(r"-?\d+(?:\.\d+)?")


@lru_cache(maxsize=1)
def _netting_ciks() -> frozenset[str]:
    from pipeline.source_encodings import load_encodings
    return frozenset(cik for cik, encoding in load_encodings().items()
                     if encoding.get("unfunded_rows") == ["net_of_tagged_commitment"])


def nets_unfunded_rows(cik: Any) -> bool:
    return re.sub(r"\D", "", str(cik or "")).zfill(10) in _netting_ciks()


def _name(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def match_commitments(commitments: list[tuple[str, float]], rows: list[dict[str, Any]]
                      ) -> tuple[list[tuple[dict[str, Any], float]], list[tuple[str, float]]]:
    """Pair each (name, amount) with one schedule row of the same date; return (pairs, unmatched)."""
    taken: set[int] = set()
    matched: list[tuple[dict[str, Any], float]] = []
    unmatched: list[tuple[str, float]] = []
    for identifier, amount in commitments:
        # the note numbers a company's commitments ('AGS Health LLC 1'); the schedule numbers its rows
        name = re.sub(r" \d+$", "", _name(identifier))
        found = None
        for position, row in enumerate(rows):
            if position in taken or not name:
                continue
            row_name = _name(row.get("investment_identifier"))
            if not (row_name == name or row_name.startswith(name + " ")):
                continue
            principal, cost = row.get("principal_amount"), row.get("cost")
            if not isinstance(cost, (int, float)) or abs(cost - amount) > 0.5:
                continue
            if isinstance(principal, (int, float)) and abs(principal - amount) <= 0.5:
                found = position
                break
            if found is None:
                found = position
        if found is None:
            unmatched.append((identifier, amount))
        else:
            taken.add(found)
            matched.append((rows[found], amount))
    return matched, unmatched


def net_unfunded_rows(tree: Any, contexts: dict[str, dict[str, Any]], facts_by_context: dict[str, dict[str, Any]],
                      filing_meta: dict[str, str], record_events: bool = True) -> int:
    """Net the filer's commitment rows in place. Returns the number of rows netted.

    ``facts_by_context`` maps a context id to its values (cost, fair_value, principal_amount).
    With ``record_events`` each netted value notes the tagged figure and the event in ``src_facts``.
    """
    if not nets_unfunded_rows(filing_meta.get("cik", "")):
        return 0
    from pipeline.bdc_filings import _local_name, _record_value_xform
    by_period: dict[str, list[tuple[str, float]]] = {}
    seen: set[str] = set()
    for elem in tree.getroot().iter():
        if not isinstance(elem.tag, str) or _local_name(elem.tag).lower() != COMMITMENT_CONCEPT:
            continue
        context = elem.get("contextRef") or ""
        info = contexts.get(context)
        text = (elem.text or "").strip()
        if context in seen or not info or not info.get("investment_identifier") or not _AMOUNT_RE.fullmatch(text):
            continue
        seen.add(context)
        if float(text) > 0:
            by_period.setdefault(info["period"], []).append((info["investment_identifier"], float(text)))
    netted = 0
    for period, commitments in by_period.items():
        rows = [{"investment_identifier": contexts[context].get("investment_identifier"), "cost": values.get("cost"),
                 "principal_amount": values.get("principal_amount"), "_values": values}
                for context, values in facts_by_context.items()
                if context in contexts and contexts[context].get("period") == period]
        matched, unmatched = match_commitments(commitments, rows)
        for row, amount in matched:
            values = row["_values"]
            for column in ("fair_value", "cost"):
                value = values.get(column)
                if isinstance(value, (int, float)):
                    values[column] = value - amount
                    if record_events:
                        _record_value_xform(values, column, value, NET_EVENT + repr(float(amount)))
            netted += 1
        if unmatched:
            logger.warning("unfunded rows %s %s %s: %d of %d tagged commitments have no schedule row; left alone",
                           filing_meta.get("cik", ""), filing_meta.get("accession_number", ""), period,
                           len(unmatched), len(commitments))
    return netted


def net_offset(x_events: list) -> float:
    """The amount an extractor netting event subtracted from the tagged value."""
    return sum(float(code[len(NET_EVENT):]) for code in x_events or [] if str(code).startswith(NET_EVENT))
