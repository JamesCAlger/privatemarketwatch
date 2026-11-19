"""Streaming parser for an XBRL instance file.

parse_instance(path, accession=None) returns a dict of lists of tuples. Every tuple starts with the
accession and follows the column order of store.TABLES. Extra keys:
  filing_dei: one tuple (document_type, document_period_end_date, amendment_flag, fiscal_year_focus,
              fiscal_period_focus, registrant_name, dei_conflict)
  stats:      (name, value) pairs: facts, synthetic_ids, numeric_not_fit, numeric_rounded
No interpretation: nothing is dropped, nothing is reclassified.
"""
import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from lxml import etree

from . import dashed_accession

TEXT_LIMIT = 4000
NS_XBRLI = "http://www.xbrl.org/2003/instance"
NS_LINK = "http://www.xbrl.org/2003/linkbase"
NS_XBRLDI = "http://xbrl.org/2006/xbrldi"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
NIL_ATTR = "{%s}nil" % NS_XSI

NUMBER_RE = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
DEI_FIELDS = {
    "DocumentType": 0,
    "DocumentPeriodEndDate": 1,
    "AmendmentFlag": 2,
    "DocumentFiscalYearFocus": 3,
    "DocumentFiscalPeriodFocus": 4,
    "EntityRegistrantName": 5,
}
class InstanceError(ValueError):
    """The instance has elements that look like facts but are not read as facts."""


_QUANT = Decimal(1).scaleb(-10)
_LIMIT = Decimal(10) ** 28


def _split(tag):
    if tag.startswith("{"):
        ns, local = tag[1:].split("}", 1)
        return ns, local
    return "", tag


def _qname(elem):
    _, local = _split(elem.tag)
    return f"{elem.prefix}:{local}" if elem.prefix else local


def _collapse(text):
    return " ".join(text.split())


def _date(text):
    if not text:
        return None
    text = text.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _child(elem, ns, local):
    for c in elem:
        if isinstance(c.tag, str) and _split(c.tag) == (ns, local):
            return c
    return None


def _children(elem, ns, local):
    return [c for c in elem if isinstance(c.tag, str) and _split(c.tag) == (ns, local)]


def _text(elem):
    return "".join(elem.itertext())


def _parse_context(elem, accession):
    cid = elem.get("id")
    ent = _child(elem, NS_XBRLI, "entity")
    scheme = ident = None
    members = []
    if ent is not None:
        i = _child(ent, NS_XBRLI, "identifier")
        if i is not None:
            scheme, ident = i.get("scheme"), (i.text or "").strip()
        containers = [("segment", _child(ent, NS_XBRLI, "segment"))]
    else:
        containers = []
    containers.append(("scenario", _child(elem, NS_XBRLI, "scenario")))
    for name, cont in containers:
        if cont is None:
            continue
        for m in cont:
            if not isinstance(m.tag, str):
                continue
            ns, local = _split(m.tag)
            if ns != NS_XBRLDI or local not in ("explicitMember", "typedMember"):
                continue
            axis = m.get("dimension")
            if local == "explicitMember":
                members.append((axis, "explicit", (m.text or "").strip(), None, name))
            else:
                inner = next((c for c in m if isinstance(c.tag, str)), None)
                if inner is None:
                    members.append((axis, "typed", m.text or "", None, name))
                else:
                    members.append((axis, "typed", _text(inner), _qname(inner), name))
    period = _child(elem, NS_XBRLI, "period")
    ptype = inst = start = end = None
    if period is not None:
        if _child(period, NS_XBRLI, "instant") is not None:
            ptype, inst = "instant", _date(_text(_child(period, NS_XBRLI, "instant")))
        elif _child(period, NS_XBRLI, "forever") is not None:
            ptype = "forever"
        else:
            ptype = "duration"
            s, e = _child(period, NS_XBRLI, "startDate"), _child(period, NS_XBRLI, "endDate")
            start = _date(_text(s)) if s is not None else None
            end = _date(_text(e)) if e is not None else None
    ctx = (accession, cid, scheme, ident, ptype, inst, start, end, len(members))
    mem_rows = [(accession, cid, i, a, k, v, t, c) for i, (a, k, v, t, c) in enumerate(members)]
    return ctx, mem_rows


def _parse_unit(elem, accession):
    uid = elem.get("id")
    div = _child(elem, NS_XBRLI, "divide")
    if div is not None:
        num = _child(div, NS_XBRLI, "unitNumerator")
        den = _child(div, NS_XBRLI, "unitDenominator")
        numerator = "*".join((m.text or "").strip() for m in _children(num, NS_XBRLI, "measure")) if num is not None else None
        denominator = "*".join((m.text or "").strip() for m in _children(den, NS_XBRLI, "measure")) if den is not None else None
        return (accession, uid, numerator, denominator)
    measures = "*".join((m.text or "").strip() for m in _children(elem, NS_XBRLI, "measure"))
    return (accession, uid, measures, None)


def _to_decimal(text):
    """Returns (value, fits, rounded). value is None where it does not fit DECIMAL(38,10)."""
    if not NUMBER_RE.fullmatch(text):
        return None, False, False
    try:
        with localcontext() as c:
            c.prec = 80
            d = Decimal(text)
            q = d.quantize(_QUANT)
            if abs(q) >= _LIMIT:
                return None, True, False
            if q.is_zero():
                q = abs(q)  # DECIMAL has no negative zero; value_text keeps the sign as written
            return q, False, q != d
    except (InvalidOperation, ValueError, ArithmeticError):
        return None, True, False


def _bool(text):
    t = (text or "").strip().lower()
    if t in ("true", "1"):
        return True
    if t in ("false", "0"):
        return False
    return None


def parse_instance(path, accession=None):
    path = Path(path)
    if accession is None:
        accession = dashed_accession(path.stem)
    contexts, members, units, facts = [], [], [], []
    dei = []
    suspects = []
    stats = {"facts": 0, "synthetic_ids": 0, "numeric_not_fit": 0, "numeric_rounded": 0}
    parser_events = etree.iterparse(
        str(path), events=("start", "end"), huge_tree=True, remove_comments=True,
        resolve_entities=False, no_network=True)
    depth = 0
    root = None
    for event, elem in parser_events:
        if event == "start":
            depth += 1
            if depth == 1:
                root = elem
            continue
        if depth != 2 and isinstance(elem.tag, str) and elem.get("contextRef") is not None:
            suspects.append(_qname(elem))
        if depth == 2 and isinstance(elem.tag, str):
            ns, local = _split(elem.tag)
            if ns == NS_XBRLI and local == "context":
                ctx, mem = _parse_context(elem, accession)
                contexts.append(ctx)
                members.extend(mem)
            elif ns == NS_XBRLI and local == "unit":
                units.append(_parse_unit(elem, accession))
            elif ns not in (NS_XBRLI, NS_LINK):
                if elem.get("contextRef") is not None:
                    _fact(elem, ns, local, accession, facts, dei, stats)
                else:
                    suspects.append(_qname(elem))
        if depth == 2:
            elem.clear()
            while elem.getprevious() is not None:
                del root[0]
        depth -= 1
    if suspects:
        shown = ", ".join(suspects[:5])
        raise InstanceError(
            f"{accession}: {len(suspects)} element(s) look like facts but are not read as facts "
            f"(no contextRef on a root child, or contextRef below the root's children): {shown}")
    stats["facts"] = len(facts)
    member_count = {c[1]: c[8] for c in contexts}
    return {
        "filing_dei": [_filing_dei(dei, member_count)],
        "context": contexts,
        "context_member": members,
        "unit": units,
        "tagged_fact": facts,
        "stats": list(stats.items()),
    }


def _fact(elem, ns, local, accession, facts, dei, stats):
    index = len(facts)
    fid = elem.get("id")
    synthetic = fid is None
    if synthetic:
        fid = f"noid:{index}"
        stats["synthetic_ids"] += 1
    unit_id = elem.get("unitRef")
    is_nil = (elem.get(NIL_ATTR) or "").strip().lower() in ("true", "1")
    full = "" if is_nil else _text(elem).strip()
    numeric = None
    numeric_candidate = False
    if unit_id is not None and not is_nil and NUMBER_RE.fullmatch(full):
        numeric_candidate = True
        numeric, not_fit, rounded = _to_decimal(full)
        if not_fit:
            stats["numeric_not_fit"] += 1
        if rounded:
            stats["numeric_rounded"] += 1
    truncated = len(full) > TEXT_LIMIT and not numeric_candidate
    value_text = None if is_nil else (full[:TEXT_LIMIT] if truncated else full)
    facts.append((
        accession, fid, index, synthetic, _qname(elem), ns, local, elem.get("contextRef"), unit_id,
        value_text, numeric, elem.get("decimals"), elem.get("precision"), is_nil,
        len(full), hashlib.sha256(full.encode("utf-8")).hexdigest(), truncated))
    if ns.startswith("http://xbrl.sec.gov/dei/") and local in DEI_FIELDS and not is_nil:
        dei.append((local, full, elem.get("contextRef")))


def _filing_dei(dei, member_count):
    values = {}
    conflict = False
    for local, text, cid in dei:
        if member_count.get(cid) != 0:
            continue
        if local in values:
            if values[local] != text:
                conflict = True
        else:
            values[local] = text
    row = [None] * 6
    for local, text in values.items():
        i = DEI_FIELDS[local]
        if i == 1:
            row[i] = _date(text)
        elif i == 2:
            row[i] = _bool(text)
        else:
            row[i] = text
    return tuple(row) + (conflict,)
