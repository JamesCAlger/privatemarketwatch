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

A second reading, ``["net_of_other_commitment"]``, is for a filer that tags its commitments note
with us-gaap:OtherCommitment per issuer (dei:LegalEntityAxis) and facility (CreditFacilityAxis,
Revolver or Delayed Draw Term Loan) and prints no per-row cost (Manulife Private Credit Fund, 10-Q
for 2026-03-31: '4M Capital, Ltd., Revolver (C) - 06-18-27 528,000 528,000' in the schedule,
'4M Capital, Ltd. - $ 528,000' in the note, 'Less unfunded loan commitments (102,864,092)' under
the total; owner ruling D-091 'net each loan'). The issuer is the first cell of the printed note
row that holds the fact (cached page). Its amount goes first to that issuer's wholly undrawn rows
of the facility (no rate), each netted by its par while the par fits what is left; what is left
then goes to the issuer's one drawn row of the facility, or failing that to its one drawn row
marked '(C)' on the page, when that row's par covers it. Anything still left is logged and not
placed. A commitment tagged with the issuer and no facility (Founders Table Holdings LLC, 10-Q for
2026-06-30: 156,661 twice on one issuer context, printed under the delayed draw and revolver
columns) is placed only when it is exact: the issuer's wholly undrawn revolver / delayed draw rows'
pars sum to the tagged total, or each printed note cell matches the par of exactly as many such
rows as cells carry that figure; otherwise it is logged and left whole. ``source_encodings.unfunded_note_aliases`` ('NOTE NAME => SCHEDULE NAME') maps a note
spelling to the schedule's, used only when the note's own spelling names no schedule row. The
netting records the same event, so the re-verifier replays it.
"""
from __future__ import annotations

import html
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COMMITMENT_CONCEPT = "investmentcompanyfinancialcommitmenttoinvesteefutureamount"
OTHER_COMMITMENT_CONCEPT = "othercommitment"
NET_EVENT = "net_of_commitment:"
TAGGED_READING = "net_of_tagged_commitment"
OTHER_READING = "net_of_other_commitment"
_AMOUNT_RE = re.compile(r"-?\d+(?:\.\d+)?")
# CreditFacilityAxis member -> the facility words a schedule row of that facility prints
_FACILITY_WORDS = (("revolver", "revolver"), ("delayeddraw", "delayed draw"))
_ALIAS_RE = re.compile(r"\s*(.*?\S)\s*=>\s*(\S.*?)\s*")


@lru_cache(maxsize=1)
def _netting_ciks() -> frozenset[str]:
    from pipeline.source_encodings import load_encodings
    return frozenset(cik for cik, encoding in load_encodings().items()
                     if encoding.get("unfunded_rows") == [TAGGED_READING])


@lru_cache(maxsize=1)
def _other_commitment_ciks() -> frozenset[str]:
    from pipeline.source_encodings import load_encodings
    return frozenset(cik for cik, encoding in load_encodings().items()
                     if encoding.get("unfunded_rows") == [OTHER_READING])


@lru_cache(maxsize=1)
def _note_aliases_by_cik() -> dict[str, tuple[tuple[str, str], ...]]:
    from pipeline.source_encodings import load_encodings
    result = {}
    for cik, encoding in load_encodings().items():
        values = encoding.get("unfunded_note_aliases")
        if values:
            result[cik] = tuple(_ALIAS_RE.fullmatch(value).groups() for value in values)
    return result


def _cik10(cik: Any) -> str:
    return re.sub(r"\D", "", str(cik or "")).zfill(10)


def nets_unfunded_rows(cik: Any) -> bool:
    return _cik10(cik) in _netting_ciks()


def nets_other_commitment_rows(cik: Any) -> bool:
    return _cik10(cik) in _other_commitment_ciks()


def note_aliases(cik: Any) -> tuple[tuple[str, str], ...]:
    """The filer's (note spelling, schedule spelling) pairs, () when it lists none."""
    return _note_aliases_by_cik().get(_cik10(cik), ())


def reading_signature(cik: Any) -> list[str]:
    """Cache-key parts for the filer's unfunded-row reading; [] when it has none."""
    if nets_unfunded_rows(cik):
        return ["unfunded:" + TAGGED_READING]
    if nets_other_commitment_rows(cik):
        return ["unfunded:" + OTHER_READING] + ["unfunded_alias:%s => %s" % pair for pair in note_aliases(cik)]
    return []


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
    if nets_other_commitment_rows(filing_meta.get("cik", "")):
        return net_other_commitment_rows(tree, contexts, facts_by_context, filing_meta, record_events=record_events)
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


_ROW_SPLIT_RE = re.compile(r"<tr\b", re.I)
_ROW_END_RE = re.compile(r"</tr>", re.I)
_CELL_SPLIT_RE = re.compile(r"<td\b", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_NONFRACTION_RE = re.compile(r"<ix:nonFraction\b([^>]*)>", re.I)
_NAME_ATTR_RE = re.compile(r'\bname="([^"]*)"')
_CONTEXT_ATTR_RE = re.compile(r'\bcontextRef="([^"]*)"')
_C_MARK_RE = re.compile(r"\(C\)")


def _first_cell(row_html: str) -> str:
    for cell in _CELL_SPLIT_RE.split(row_html)[1:]:
        text = " ".join(html.unescape(_TAG_RE.sub(" ", cell.split(">", 1)[-1])).replace("\xa0", " ").split())
        if text:
            return text
    return ""


def page_rows(page_html: str) -> tuple[dict[str, str], dict[str, str]]:
    """First printed cell of the row holding each fact: (OtherCommitment contexts, fair-value contexts).

    A context whose facts sit on rows with different first cells is left out of the map.
    """
    note: dict[str, set[str]] = {}
    schedule: dict[str, set[str]] = {}
    for chunk in _ROW_SPLIT_RE.split(page_html)[1:]:
        if "OtherCommitment" not in chunk and "InvestmentOwnedAtFairValue" not in chunk:
            continue
        row = _ROW_END_RE.split(chunk, maxsplit=1)[0]
        first = None
        for attrs in _NONFRACTION_RE.findall(row):
            name, ref = _NAME_ATTR_RE.search(attrs), _CONTEXT_ATTR_RE.search(attrs)
            if not name or not ref:
                continue
            local = name.group(1).split(":")[-1]
            target = note if local == "OtherCommitment" else schedule if local == "InvestmentOwnedAtFairValue" else None
            if target is None:
                continue
            if first is None:
                first = _first_cell(row)
            target.setdefault(ref.group(1), set()).add(first)
    pick = lambda found: {ref: next(iter(cells)) for ref, cells in found.items() if len(cells) == 1 and next(iter(cells))}
    return pick(note), pick(schedule)


_NONFRACTION_VALUE_RE = re.compile(r"<ix:nonFraction\b([^>]*)>(.*?)</ix:nonFraction>", re.I | re.S)
_SCALE_ATTR_RE = re.compile(r'\bscale="(-?\d+)"')
_SIGN_ATTR_RE = re.compile(r'\bsign="-"')


def note_row_values(page_html: str) -> dict[str, tuple[float, ...]]:
    """The printed OtherCommitment cells of each context, when all of them sit on one row.

    Used for a commitment tagged with the issuer and no facility: the note row's cells give the
    per-facility split (Founders Table Holdings LLC 2026-06-30: 156,661 and 156,661). A cell that
    does not read as a positive number is left out; a context on two rows is left out.
    """
    found: dict[str, list[tuple[int, float]]] = {}
    for index, chunk in enumerate(_ROW_SPLIT_RE.split(page_html)[1:]):
        if "OtherCommitment" not in chunk:
            continue
        row = _ROW_END_RE.split(chunk, maxsplit=1)[0]
        for attrs, inner in _NONFRACTION_VALUE_RE.findall(row):
            name, ref = _NAME_ATTR_RE.search(attrs), _CONTEXT_ATTR_RE.search(attrs)
            if not name or not ref or name.group(1).split(":")[-1] != "OtherCommitment":
                continue
            text = html.unescape(_TAG_RE.sub("", inner)).replace(",", "").strip()
            if not _AMOUNT_RE.fullmatch(text) or _SIGN_ATTR_RE.search(attrs):
                continue
            scale = _SCALE_ATTR_RE.search(attrs)
            value = float(text) * (10 ** int(scale.group(1)) if scale else 1)
            if value > 0:
                found.setdefault(ref.group(1), []).append((index, value))
    return {ref: tuple(value for _index, value in cells) for ref, cells in found.items()
            if len({index for index, _value in cells}) == 1}


def _facility_words(dimensions_raw: str) -> str | None:
    for part in str(dimensions_raw or "").split("|"):
        axis, _, member = part.partition("=")
        if axis == "creditfacilityaxis":
            member = member.lower()
            return next((words for key, words in _FACILITY_WORDS if key in member), None)
    return None


def _has_rate(value: Any) -> bool:
    return isinstance(value, (int, float)) and value != 0


NO_FACILITY = "no facility"


def _place_issuer_only(amount: float, split: tuple[float, ...], undrawn: list[int],
                       rows: list[dict[str, Any]]) -> list[int] | None:
    """The wholly undrawn rows an issuer-only commitment covers exactly, else None.

    Either the rows' pars sum to the amount, or each printed note cell matches the par of
    exactly as many rows as cells carry that figure (so the rows are determined).
    """
    pars = [float(rows[i]["principal_amount"]) for i in undrawn]
    if undrawn and abs(sum(pars) - amount) <= 0.5:
        return list(undrawn)
    if not split or abs(sum(split) - amount) > 0.5:
        return None
    chosen: list[int] = []
    for value in sorted({round(v, 2) for v in split}):
        cells = sum(1 for v in split if abs(v - value) <= 0.5)
        matching = [i for i, par in zip(undrawn, pars) if abs(par - value) <= 0.5]
        if len(matching) != cells:
            return None
        chosen += matching
    return chosen or None


def allocate_other_commitments(commitments: list[tuple[str, str, float]], rows: list[dict[str, Any]],
                               aliases: tuple[tuple[str, str], ...] = (),
                               issuer_only: list[tuple[str, float, tuple[float, ...]]] = ()
                               ) -> tuple[list[tuple[dict[str, Any], float]], list[tuple[str, str, float]]]:
    """Place each (issuer, facility words, amount) on schedule rows of the same date.

    ``rows`` carry ``label`` (the printed first cell, else the identifier's last segment),
    ``principal_amount``, ``interest_rate`` and ``c_marked``. Returns (placements, left), where
    ``left`` holds each commitment's unplaced remainder (issuer, facility, amount). A row is netted once.

    ``issuer_only`` holds (issuer, amount, printed note cells) for a commitment tagged with the
    issuer and no facility (Manulife 10-Q 2026-06-30, Founders Table Holdings LLC: 156,661 twice on
    one issuer context, printed under the delayed draw and revolver columns). After the facility
    commitments it is placed only where it is exact (_place_issuer_only) on the issuer's wholly
    undrawn revolver / delayed draw rows, each netted by its par; otherwise it is left whole.
    """
    alias_of = {_name(note): _name(schedule) for note, schedule in aliases}
    labels = [_name(row.get("label")) for row in rows]

    def names(key: str) -> bool:
        return any(label == key or label.startswith(key + " ") for label in labels)

    def key_of(issuer: str) -> str:
        key = _name(issuer)
        if key and not names(key) and key in alias_of:
            key = alias_of[key]
        return key

    keys = [key_of(issuer) for issuer, _facility, _amount in commitments]
    issuer_only_keys = [key_of(issuer) for issuer, _amount, _split in issuer_only]
    # a row belongs to the longest issuer name it starts with ('Acme LLC Holdings' is not 'Acme LLC')
    owner: list[str | None] = []
    for label in labels:
        fits = [key for key in set(keys + issuer_only_keys) if key and (label == key or label.startswith(key + " "))]
        owner.append(max(fits, key=len) if fits else None)
    taken: set[int] = set()
    placements: list[tuple[dict[str, Any], float]] = []
    left: list[tuple[str, str, float]] = []
    for (issuer, facility, amount), key in zip(commitments, keys):
        candidates = [i for i, label in enumerate(labels)
                      if i not in taken and owner[i] == key and key and facility in label[len(key):]]
        remaining = amount
        for i in candidates:
            principal = rows[i].get("principal_amount")
            if (not _has_rate(rows[i].get("interest_rate")) and isinstance(principal, (int, float))
                    and 0 < principal <= remaining + 0.5):
                placements.append((rows[i], float(principal)))
                taken.add(i)
                remaining -= principal
        if abs(remaining) > 0.5:
            drawn = [i for i in candidates if i not in taken and _has_rate(rows[i].get("interest_rate"))]
            marked = [i for i in drawn if rows[i].get("c_marked")]
            for group in (drawn, marked):
                principal = rows[group[0]].get("principal_amount") if len(group) == 1 else None
                if isinstance(principal, (int, float)) and principal >= remaining - 0.5:
                    placements.append((rows[group[0]], round(remaining, 2)))
                    taken.add(group[0])
                    remaining = 0.0
                    break
        if abs(remaining) > 0.5:
            left.append((issuer, facility, remaining))
    for (issuer, amount, split), key in zip(issuer_only, issuer_only_keys):
        undrawn = [i for i, label in enumerate(labels)
                   if i not in taken and key and owner[i] == key
                   and any(words in label[len(key):] for _member, words in _FACILITY_WORDS)
                   and not _has_rate(rows[i].get("interest_rate"))
                   and isinstance(rows[i].get("principal_amount"), (int, float)) and rows[i]["principal_amount"] > 0]
        chosen = _place_issuer_only(amount, tuple(split), undrawn, rows)
        if chosen is None:
            left.append((issuer, NO_FACILITY, amount))
            continue
        for i in chosen:
            placements.append((rows[i], float(rows[i]["principal_amount"])))
            taken.add(i)
    return placements, left


def _schedule_rows(contexts: dict[str, dict[str, Any]], facts_by_context: dict[str, dict[str, Any]],
                   schedule_label: dict[str, str], period: str) -> list[dict[str, Any]]:
    """Schedule rows of one date, contexts the deduplication will merge taken as one row.

    The extractor's deduplication merges contexts with the same identifier and dimensions on one date
    (bdc_filings._DEDUP_KEY_COLUMNS) when at most one of them has a fair value. Manulife's 10-K for
    2024-12-31 tags Integrated Openings' delayed draw par on the dated context and its fair value on a
    context dated 2025-02-24 (re-dated by misdated_contexts): one printed row, two contexts.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for context in facts_by_context:
        info = contexts.get(context)
        if info and str(info.get("period", ""))[:10] == period:
            groups.setdefault((str(info.get("investment_identifier", "")), str(info.get("dimensions_raw", ""))),
                              []).append(context)
    rows = []
    for members in groups.values():
        valued = [c for c in members if isinstance(facts_by_context[c].get("fair_value"), (int, float))]
        for part in ([members] if len(valued) <= 1 else [[c] for c in members]):
            values = [facts_by_context[c] for c in part]
            printed = next((schedule_label[c] for c in part if schedule_label.get(c)), "")
            label = printed or str(contexts[part[0]].get("investment_identifier", "")).split("|")[-1].strip()
            first = lambda column: next((v[column] for v in values if v.get(column) is not None), None)
            rows.append({"label": label, "principal_amount": first("principal_amount"),
                         "interest_rate": first("interest_rate"), "c_marked": bool(_C_MARK_RE.search(printed)),
                         "_members": values})
    return rows


def net_other_commitment_rows(tree: Any, contexts: dict[str, dict[str, Any]],
                              facts_by_context: dict[str, dict[str, Any]], filing_meta: dict[str, str],
                              record_events: bool = True, html_cache_dir: Path | None = None) -> int:
    """The ``net_of_other_commitment`` reading (module docstring). Returns the number of rows netted."""
    from pipeline.bdc_filings import _local_name, _record_value_xform
    cik = _cik10(filing_meta.get("cik", ""))
    accession = str(filing_meta.get("accession_number", ""))
    tagged: list[tuple[str, str, float]] = []
    seen: set[str] = set()
    # issuer contexts with no CreditFacilityAxis: every fact is kept (Founders Table 2026-06-30 has two)
    issuer_only_facts: dict[str, list[float]] = {}
    for elem in tree.getroot().iter():
        if not isinstance(elem.tag, str) or _local_name(elem.tag).lower() != OTHER_COMMITMENT_CONCEPT:
            continue
        context = elem.get("contextRef") or ""
        info = contexts.get(context)
        text = (elem.text or "").strip()
        if not info or not _AMOUNT_RE.fullmatch(text) or float(text) <= 0:
            continue
        dimensions = str(info.get("dimensions_raw", ""))
        if "legalentityaxis=" in dimensions and "creditfacilityaxis=" not in dimensions:
            issuer_only_facts.setdefault(context, []).append(float(text))
            continue
        if context in seen:
            continue
        seen.add(context)
        if "legalentityaxis=" in dimensions:
            tagged.append((context, str(info.get("period", ""))[:10], float(text)))
    if not tagged and not issuer_only_facts:
        return 0
    if html_cache_dir is None:
        from pipeline.config import BDC_HTML_CACHE_DIR
        html_cache_dir = BDC_HTML_CACHE_DIR
    page = Path(html_cache_dir) / cik.lstrip("0") / (accession.replace("-", "") + ".html")
    if not page.exists():
        logger.warning("unfunded rows %s %s: no cached page for the commitments note; nothing netted", cik, accession)
        return 0
    page_html = page.read_text(encoding="utf-8", errors="replace")
    note_issuer, schedule_label = page_rows(page_html)
    printed_cells = note_row_values(page_html) if issuer_only_facts else {}
    by_period: dict[str, list[tuple[str, str, float]]] = {}
    issuer_only_by_period: dict[str, list[tuple[str, float, tuple[float, ...]]]] = {}
    unread = 0
    for context, period, amount in tagged:
        facility = _facility_words(contexts[context].get("dimensions_raw", ""))
        issuer = note_issuer.get(context, "")
        if not facility or not issuer:
            unread += 1
            continue
        by_period.setdefault(period, []).append((issuer, facility, amount))
    for context, amounts in issuer_only_facts.items():
        issuer = note_issuer.get(context, "")
        cells = printed_cells.get(context, ())
        if not issuer:
            unread += 1
            continue
        if cells and abs(sum(cells) - sum(amounts)) > 0.5:
            # the page and the instance disagree on the issuer's figures: the split is not used
            cells = ()
        period = str(contexts[context].get("period", ""))[:10]
        issuer_only_by_period.setdefault(period, []).append((issuer, sum(amounts), tuple(cells)))
    if unread:
        logger.warning("unfunded rows %s %s: %d tagged commitments with no printed issuer or facility; not placed",
                       cik, accession, unread)
    report_date = str(filing_meta.get("report_date") or "")[:10]
    periods = set(by_period) | set(issuer_only_by_period)
    if report_date:
        # the comparative column is not read: the 10-K for 2025-12-31 prints its 2024-12-31 amounts a row off
        # (P.J. Fitzpatrick's row carries PAK Quality Foods' 537,313 and 313,433), and staging drops comparatives
        periods = {period for period in periods if period == report_date}
    aliases = note_aliases(cik)
    netted = 0
    for period in sorted(periods):
        commitments = by_period.get(period, [])
        issuer_only = issuer_only_by_period.get(period, [])
        rows = _schedule_rows(contexts, facts_by_context, schedule_label, period)
        placements, left = allocate_other_commitments(commitments, rows, aliases, issuer_only)
        for row, amount in placements:
            event = NET_EVENT + repr(float(amount))
            for column in ("fair_value", "cost"):
                holders = [values for values in row["_members"] if isinstance(values.get(column), (int, float))]
                if len(holders) != 1:
                    continue
                value = holders[0][column]
                holders[0][column] = value - amount
                if record_events:
                    # every context of the row records the event: the deduplication fills the value into
                    # whichever context it keeps (a re-dated context's fair value into the dated one)
                    for values in row["_members"]:
                        _record_value_xform(values, column, value, event)
            netted += 1
        total = (sum(amount for _issuer, _facility, amount in commitments)
                 + sum(amount for _issuer, amount, _cells in issuer_only))
        unplaced = sum(amount for _issuer, _facility, amount in left)
        logger.info("unfunded rows %s %s %s: %d commitments %.0f, netted %d rows, unplaced %.0f in %d",
                    cik, accession, period, len(commitments) + len(issuer_only), total, len(placements),
                    unplaced, len(left))
        if left:
            logger.warning("unfunded rows %s %s %s: unplaced %s", cik, accession, period,
                           "; ".join("%s / %s %.0f" % item for item in left).encode("ascii", "replace").decode("ascii"))
    return netted


def net_offset(x_events: list) -> float:
    """The amount an extractor netting event subtracted from the tagged value."""
    return sum(float(code[len(NET_EVENT):]) for code in x_events or [] if str(code).startswith(NET_EVENT))
