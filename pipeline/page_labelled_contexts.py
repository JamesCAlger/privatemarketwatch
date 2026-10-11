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


_NAMED_CONTEXT_RE = re.compile(r"(\d{10}-\d{2}-\d{6}) (\S+) => (.+)")


@lru_cache(maxsize=1)
def _named_by_accession() -> dict[tuple[str, str], dict[str, str]]:
    from pipeline.source_encodings import load_encodings
    result: dict[tuple[str, str], dict[str, str]] = {}
    for cik, encoding in load_encodings().items():
        for value in encoding.get("context_identifiers", []):
            accession, context, identifier = _NAMED_CONTEXT_RE.fullmatch(value.strip()).groups()
            result.setdefault((cik, accession), {})[context] = identifier.strip()
    return result


@lru_cache(maxsize=None)
def _category_marker(cik: str) -> re.Pattern[str] | None:
    """The fund wrapper's dispatch.category_marker_re, compiled; None where the wrapper has none."""
    import json
    from pipeline.config import OVERRIDES_DIR
    path = OVERRIDES_DIR / "bdc_xbrl_wrappers" / (cik + ".json")
    try:
        pattern = json.loads(path.read_text(encoding="utf-8")).get("dispatch", {}).get("category_marker_re")
    except (OSError, json.JSONDecodeError):
        return None
    return re.compile(pattern) if pattern else None


def name_declared_contexts(contexts: dict[str, dict[str, Any]], filing_meta: dict[str, str]) -> int:
    """Name the contexts a wrapper lists for this filing, in place. Returns the number named.

    A filer can leave the identifier member off its position rows in one filing and tag them on
    the group's context instead (NexPoint Capital, 10-Qs for 2025-06-30 and 2025-09-30: 13 of
    27 printed rows, 23.5M of 39.6M). Where the page-labelled reading does not fit the filer's
    layout, the wrapper's ``source_encodings.context_identifiers`` lists each one as
    'ACCESSION CONTEXT => IDENTIFIER', the identifier written as the filer writes it in its
    other filings. A context that already names a position is never renamed, and a context the
    filing does not hold is skipped with a warning.
    """
    cik = re.sub(r"\D", "", str(filing_meta.get("cik", ""))).zfill(10)
    listed = _named_by_accession().get((cik, str(filing_meta.get("accession_number", ""))))
    if not listed:
        return 0
    named = 0
    for context, identifier in listed.items():
        info = contexts.get(context)
        if info is None:
            logger.warning("declared context %s %s %s: not in the filing; skipped",
                           cik, filing_meta.get("accession_number", ""), context)
            continue
        if info.get("is_investment"):
            # A member that names only an instrument ('First Lien Senior Secured Term Loan') is one the
            # fund's own wrapper reads as a category row (dispatch.category_marker_re): it names no
            # position, so a listed context that carries it takes the declared name (Barings 2023-06-30,
            # c-329: Finexvet's first tranche, 2,388, filed without the issuer). Any other member stays.
            marker = _category_marker(cik)
            if marker is None or not marker.search(str(info.get("investment_identifier", "")).strip()):
                continue
        info["investment_identifier"] = identifier
        info["is_investment"] = True
        named += 1
    return named


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


_UNTAGGED_RE = re.compile(r"(\d{10}-\d{2}-\d{6}) (\S+) (fair_value|cost|principal_amount) (-?\d+(?:\.\d+)?)")


@lru_cache(maxsize=1)
def _untagged_by_accession() -> dict[tuple[str, str], dict[str, dict[str, float]]]:
    from pipeline.source_encodings import load_encodings
    result: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for cik, encoding in load_encodings().items():
        for value in encoding.get("untagged_values", []):
            accession, context, name, number = _UNTAGGED_RE.fullmatch(value.strip()).groups()
            result.setdefault((cik, accession), {}).setdefault(context, {})[name] = float(number)
    return result


def fill_untagged_values(facts_by_context: dict[str, dict[str, Any]], filing_meta: dict[str, str]) -> int:
    """Give a context the value its printed row shows and its tags lack. Returns the number filled.

    A filer can print a row's fair value and tag only its cost and units (Sixth Street
    0000950170-25-021144: Elysium BidCo preference shares, printed '49,063 49,063', tagged with a
    cost of 49,063 and no fair value). A row with no fair value is not a position, so it was lost.
    The wrapper's ``source_encodings.untagged_values`` lists each one as
    'ACCESSION CONTEXT FIELD VALUE' with the printed row as evidence. Only a missing value is
    filled: a tagged value is never replaced, and a context with no facts at all is left alone.
    """
    cik = re.sub(r"\D", "", str(filing_meta.get("cik", ""))).zfill(10)
    listed = _untagged_by_accession().get((cik, str(filing_meta.get("accession_number", ""))))
    if not listed:
        return 0
    filled = 0
    for context, values in listed.items():
        facts = facts_by_context.get(context)
        if not facts:
            logger.warning("untagged value %s %s %s: the context carries no facts; left alone",
                           cik, filing_meta.get("accession_number", ""), context)
            continue
        for name, number in values.items():
            if facts.get(name) is None:
                facts[name] = number
                filled += 1
    return filled


def untagged_value(cik: Any, accession: Any, context: Any, field: str) -> float | None:
    """The value a wrapper declares for a field its filer printed and did not tag, else None."""
    owner = re.sub(r"\D", "", str(cik or "")).zfill(10)
    return _untagged_by_accession().get((owner, str(accession or "")), {}).get(str(context or ""), {}).get(field)


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
    from pipeline.bdc_filings import fair_value_aliases
    named = sorted("%s %s => %s" % (accession, context, identifier)
                   for (owner, accession), listed in _named_by_accession().items() if owner == cik
                   for context, identifier in listed.items())
    untagged = sorted("%s %s %s %s" % (accession, context, name, number)
                      for (owner, accession), listed in _untagged_by_accession().items() if owner == cik
                      for context, values in listed.items() for name, number in values.items())
    from pipeline.unfunded_commitments import nets_unfunded_rows
    netting = ["unfunded:net_of_tagged_commitment"] if nets_unfunded_rows(cik) else []
    from pipeline.schedule_row_tags import reads_schedule_row_tags
    from pipeline.rate_tag_reading import reads_margins
    if reads_margins(cik):
        netting.append("rates:coupon_with_margins")
    from pipeline.schedule_row_tags import schedule_row_tests
    netting.extend("rows:" + name for name in sorted(schedule_row_tests(cik)))
    return "|".join(combos + misdated + untagged + named + netting
                    + sorted("fv:" + name for name in fair_value_aliases(cik)))
