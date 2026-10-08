"""Positions a filer tags on a subtotal context, named from the printed row.

Some filers give a schedule row no investment-identifier member when it is the only position in
its group: the row's facts sit on the group's own context (industry, affiliation and type members),
the same context a multi-row group uses for its subtotal. The XBRL instance then holds the
position's fair value, cost, principal and rate but not its name, and the extractor, which reads
positions from identifier members, drops it. Golub Capital Private Credit Fund's 10-Qs from
2023-12-31: about 70M to 85M of 9.6B at 2025-12-31 to 2026-06-30.

The name is on the page. For a filer whose wrapper lists ``source_encodings.page_labelled_contexts``
(each value one axis combination, lower-case local names joined by "+"), this module reads the
cached filing page and adopts a context when exactly one printed row carries its fair-value tag
and that row starts with a label, not an amount and not "Total". A subtotal row prints amounts
only, so it is never adopted. The identifier is the row's first two text cells joined by " | ".

No network call: a filing whose page is not cached adopts nothing and logs a warning.
"""
from __future__ import annotations

import html
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FAIR_VALUE_TAG_RE = re.compile(r"<ix:nonFraction\b([^>]*)>", re.I)
_CONTEXT_REF_RE = re.compile(r'contextRef="([^"]*)"')
_NAME_RE = re.compile(r'name="[^"]*:InvestmentOwnedAtFairValue"')
_CELL_SPLIT_RE = re.compile(r"<td\b", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_AMOUNT_RE = re.compile(r"^[\s$(]*[\d,]+(?:\.\d+)?[\s)%]*$")
_FOOTNOTE_MARKS_RE = re.compile(r"(?:\s*(?:\(\d+\)|[@#^*+~]))+$")


@lru_cache(maxsize=1)
def _combos_by_cik() -> dict[str, frozenset[frozenset[str]]]:
    from pipeline.source_encodings import load_encodings
    result = {}
    for cik, encoding in load_encodings().items():
        values = encoding.get("page_labelled_contexts")
        if values:
            result[cik] = frozenset(frozenset(part.strip().lower() for part in value.split("+")) for value in values)
    return result


def context_axes(dimensions_raw: str) -> frozenset[str]:
    """The axis names of a context that has explicit members only."""
    return frozenset(part.split("=", 1)[0] for part in str(dimensions_raw or "").split("|") if "=" in part)


def _cell_texts(row_html: str) -> list[str]:
    cells = []
    for cell in _CELL_SPLIT_RE.split(row_html)[1:]:
        text = " ".join(html.unescape(_TAG_RE.sub(" ", cell.split(">", 1)[-1])).replace("\xa0", " ").split())
        if text:
            cells.append(text)
    return cells


def row_identifier(cells: list[str]) -> str:
    """Identifier of a labelled position row, or '' for a subtotal, total or unlabelled row."""
    if len(cells) < 2:
        return ""
    label = _FOOTNOTE_MARKS_RE.sub("", cells[0]).strip()
    kind = cells[1].strip()
    if not label or label.lower().startswith("total") or _AMOUNT_RE.match(label) or not re.search(r"[A-Za-z]{2}", label):
        return ""
    if _AMOUNT_RE.match(kind) or not re.search(r"[A-Za-z]{2}", kind):
        return ""
    return "%s | %s" % (label, kind)


def labelled_contexts(page_html: str, candidates: set[str]) -> dict[str, str]:
    """Map each candidate context to the identifier of the one labelled row that carries it."""
    found: dict[str, set[str]] = {}
    for chunk in re.split(r"<tr\b", page_html, flags=re.I)[1:]:
        if "InvestmentOwnedAtFairValue" not in chunk:
            continue
        row = re.split(r"</tr>", chunk, maxsplit=1, flags=re.I)[0]
        refs = {m.group(1) for attrs in _FAIR_VALUE_TAG_RE.findall(row) if _NAME_RE.search(attrs)
                for m in [_CONTEXT_REF_RE.search(attrs)] if m and m.group(1) in candidates}
        if not refs:
            continue
        identifier = row_identifier(_cell_texts(row))
        for ref in refs:
            found.setdefault(ref, set()).add(identifier)
    return {ref: next(iter(names)) for ref, names in found.items() if len(names) == 1 and "" not in names}


def adopt_page_labelled_contexts(contexts: dict[str, dict[str, Any]], filing_meta: dict[str, str],
                                 html_cache_dir: Path | None = None) -> int:
    """Mark page-labelled subtotal contexts as positions, in place. Returns the number adopted."""
    cik = re.sub(r"\D", "", str(filing_meta.get("cik", ""))).zfill(10)
    combos = _combos_by_cik().get(cik)
    if not combos:
        return 0
    candidates = {ctx_id for ctx_id, info in contexts.items()
                  if not info.get("is_investment") and context_axes(info.get("dimensions_raw", "")) in combos}
    if not candidates:
        return 0
    if html_cache_dir is None:
        from pipeline.config import BDC_HTML_CACHE_DIR
        html_cache_dir = BDC_HTML_CACHE_DIR
    accession = str(filing_meta.get("accession_number", "")).replace("-", "")
    page = Path(html_cache_dir) / cik.lstrip("0") / (accession + ".html")
    if not page.exists():
        logger.warning("page-labelled contexts: no cached page for %s %s; nothing adopted", cik, accession)
        return 0
    adopted = labelled_contexts(page.read_text(encoding="utf-8", errors="replace"), candidates)
    for ctx_id, identifier in adopted.items():
        contexts[ctx_id]["investment_identifier"] = identifier
        contexts[ctx_id]["is_investment"] = True
    if adopted:
        logger.info("page-labelled contexts: %s %s adopted %d of %d candidate contexts",
                    cik, accession, len(adopted), len(candidates))
    return len(adopted)


_MISDATED_RE = re.compile(r"(\d{10}-\d{2}-\d{6}) (\S+) (\d{4}-\d{2}-\d{2}) -> (\d{4}-\d{2}-\d{2})")


@lru_cache(maxsize=1)
def _misdated_by_accession() -> dict[tuple[str, str], dict[str, tuple[str, str]]]:
    from pipeline.source_encodings import load_encodings
    result: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}
    for cik, encoding in load_encodings().items():
        for value in encoding.get("misdated_contexts", []):
            accession, context, filed, corrected = _MISDATED_RE.fullmatch(value.strip()).groups()
            result.setdefault((cik, accession), {})[context] = (filed, corrected)
    return result


def correct_misdated_contexts(contexts: dict[str, dict[str, Any]], filing_meta: dict[str, str]) -> int:
    """Re-date contexts a filer dated to the wrong period, in place. Returns the number re-dated.

    A filer can tag a current-period schedule row on a context dated to the prior period (Ares
    Strategic Income 0001918712-25-000030: the 2025-03-31 Grant Thornton loan, 31.2M, on a
    context dated 2024-12-31). The row then reads as a comparative and leaves the quarter. The
    wrapper's ``source_encodings.misdated_contexts`` lists each one as
    'ACCESSION CONTEXT FILED-DATE -> CORRECT-DATE', with the printed row as evidence. A listed
    context whose filed date is not the one recorded is left alone and logged: the filing is not
    the one that was read.
    """
    cik = re.sub(r"\D", "", str(filing_meta.get("cik", ""))).zfill(10)
    listed = _misdated_by_accession().get((cik, str(filing_meta.get("accession_number", ""))))
    if not listed:
        return 0
    changed = 0
    for context, (filed, corrected) in listed.items():
        info = contexts.get(context)
        if info is None or str(info.get("period", ""))[:10] != filed:
            logger.warning("misdated context %s %s %s: not found with period %s; left alone",
                           cik, filing_meta.get("accession_number", ""), context, filed)
            continue
        info["period"] = corrected
        changed += 1
    return changed


def encoding_signature(cik: str) -> str:
    """The two readings as configured for one filer, '' when it uses neither.

    A cache of facts extracted per filing mixes this into its key, so changing a filer's
    wrapper re-extracts that filer's filings and leaves every other filer's cache valid.
    """
    cik = re.sub(r"\D", "", str(cik or "")).zfill(10)
    combos = sorted("+".join(sorted(combo)) for combo in _combos_by_cik().get(cik, ()))
    misdated = sorted("%s %s %s %s" % (accession, context, filed, corrected)
                      for (owner, accession), listed in _misdated_by_accession().items() if owner == cik
                      for context, (filed, corrected) in listed.items())
    return "|".join(combos + misdated)
