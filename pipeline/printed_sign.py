"""Cost and fair value whose tagged sign disagrees with the printed brackets.

An inline XBRL fact carries its sign in the ``sign="-"`` attribute; the printed page shows the
same negative in brackets. NMF SLF I's filings from the 10-K for 2025-12-31 print the undrawn
lines' negative cost and fair value in brackets ('DigiCert, Inc. Software First Lien(3)(4) -
Undrawn - - - 07/2025 07/2030 512 ( 3 ) ( 4 ) ( 0.00 )%') and tag them with no sign, so the
instance holds +3 and +4; its earlier filings sign them. A few facts go the other way: tagged
negative, printed without brackets ('OEConnection LLC ... Undrawn ... $ 1,847 $ - $ 3').

For a filing listed in the filer's wrapper under ``source_encodings.bracketed_unsigned_values``
(accession numbers), each InvestmentOwnedAtCost and InvestmentOwnedAtFairValue fact whose printed
sign (brackets) differs from its tagged sign is published with the printed sign. The tagged value
is kept in ``src_facts`` with the event ``cik_scale_fix:x-1``, which the provenance re-verifier
reads as a multiplier, so the published figure is still checked against the instance fact.

Only a fact whose magnitude equals the record's value is changed, and only the two value
concepts. No network call: a filing whose page is not cached changes nothing and logs a warning.
"""
from __future__ import annotations

import html
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SIGN_EVENT = "cik_scale_fix:x-1"
_COLUMNS = {"investmentownedatcost": "cost", "investmentownedatfairvalue": "fair_value"}
_FACT_RE = re.compile(r"<ix:nonFraction\b([^>]*)>([^<]*)</ix:nonFraction>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_ATTR_RE = {name: re.compile(r'\b%s="([^"]*)"' % name) for name in ("name", "contextRef", "scale", "sign")}


@lru_cache(maxsize=1)
def _listed() -> dict[str, frozenset[str]]:
    from pipeline.source_encodings import load_encodings
    return {cik: frozenset(str(a).strip() for a in encoding["bracketed_unsigned_values"])
            for cik, encoding in load_encodings().items() if encoding.get("bracketed_unsigned_values")}


def listed_accessions(cik: Any) -> frozenset[str]:
    return _listed().get(re.sub(r"\D", "", str(cik or "")).zfill(10), frozenset())


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", fragment)).replace("\xa0", " ").split())


def printed_signs(page_html: str) -> dict[tuple[str, str], list[tuple[float, bool, bool]]]:
    """(context, column) -> [(magnitude, printed in brackets, tagged with a minus sign)] for the two value concepts."""
    found: dict[tuple[str, str], list[tuple[float, bool, bool]]] = {}
    for match in _FACT_RE.finditer(page_html):
        attrs, value = match.groups()
        # the cell text either side of the fact, read from the page itself (not consumed by the match)
        before = page_html[max(0, match.start() - 400):match.start()]
        after = page_html[match.end():match.end() + 300]
        name = _ATTR_RE["name"].search(attrs)
        context = _ATTR_RE["contextRef"].search(attrs)
        if not name or not context:
            continue
        column = _COLUMNS.get(name.group(1).rsplit(":", 1)[-1].lower())
        if column is None:
            continue
        try:
            number = float(value.strip().replace(",", ""))
        except ValueError:
            continue
        scale = _ATTR_RE["scale"].search(attrs)
        magnitude = abs(number) * (10 ** int(scale.group(1)) if scale else 1)
        bracketed = _text(before).endswith("(") and _text(after).startswith(")")
        signed = bool(_ATTR_RE["sign"].search(attrs)) and _ATTR_RE["sign"].search(attrs).group(1) == "-"
        found.setdefault((context.group(1), column), []).append((magnitude, bracketed, signed))
    return found


def apply_printed_signs(facts_by_context: dict[str, dict[str, Any]], filing_meta: dict[str, str],
                        html_cache_dir: Path | None = None, record_events: bool = True) -> int:
    """Give listed filings' cost and fair value the printed sign, in place. Returns the values changed.

    The source-reconciliation reader calls this with ``record_events=False``, so it compares the
    published row with the same reading of the filing, as it does for the other source encodings.
    """
    cik = re.sub(r"\D", "", str(filing_meta.get("cik", ""))).zfill(10)
    accession = str(filing_meta.get("accession_number", "")).strip()
    if accession not in listed_accessions(cik):
        return 0
    if html_cache_dir is None:
        from pipeline.config import BDC_HTML_CACHE_DIR
        html_cache_dir = BDC_HTML_CACHE_DIR
    page = Path(html_cache_dir) / cik.lstrip("0") / (accession.replace("-", "") + ".html")
    if not page.exists():
        logger.warning("printed sign: no cached page for %s %s; nothing changed", cik, accession)
        return 0
    from pipeline.bdc_filings import _record_value_xform
    changed = 0
    for (context, column), facts in printed_signs(page.read_text(encoding="utf-8", errors="replace")).items():
        record = facts_by_context.get(context)
        if not record:
            continue
        value = record.get(column)
        if not isinstance(value, (int, float)) or value == 0:
            continue
        # every printing of this fact must agree: a fact printed twice with different brackets is left alone
        readings = {(bracketed, signed) for magnitude, bracketed, signed in facts if abs(magnitude - abs(value)) <= 0.5}
        if len(readings) != 1 or len({m for m, _b, _s in facts}) != 1:
            continue
        bracketed, signed = next(iter(readings))
        if bracketed == signed or (bracketed and value < 0) or (not bracketed and value > 0):
            continue
        record[column] = -value
        if record_events:
            _record_value_xform(record, column, value, SIGN_EVENT)
        changed += 1
    if changed:
        logger.info("printed sign: %s %s %d cost or fair value facts take the printed sign", cik, accession, changed)
    return changed
