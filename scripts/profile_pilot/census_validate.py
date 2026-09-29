"""Task 5: cross-check a census against the raw cached XBRL instance, fact by fact.

The census parser is lxml driven by census_collect.py. This validator re-reads the
same file with a DIFFERENT parser (stdlib ElementTree / expat) and its own traversal,
then checks identified source facts, by fact id or (QName, context id, occurrence),
not row counts:

- source:  sha256 and size of the bytes read equal the census before/after hashes;
- document: DocumentPeriodEndDate, DocumentType and entity identifiers;
- fact_inventory: every root-level source fact is in the census and vice versa
  (per QName/context multiset and document ordinal);
- contexts / comparative_contexts: period, entity and dimensions of every context;
  the comparative subset (period anchor != any DocumentPeriodEndDate of the SOURCE)
  plus its facts and the census `periods[].relation` labels;
- numeric_facts / rates: value (Decimal equality), unit, decimals, nil/invalid status
  and context of every numeric fact; the rate subset (interest_rate, pik_rate,
  interest_rate_floor, basis_spread) also re-checks every position rate field against
  the source facts it cites;
- text_facts: full-text sha256/length (long text) or exact text of every text, date,
  boolean and enumeration fact;
- footnotes: every footnote resource's text hash and the exact set of fact ids linked
  to it; or, when the census channel is `unsupported`, that the source really has no
  link:footnoteLink;
- explicit_rule_periods: a census position identified by a per-CIK explicit identity
  rule must sit inside that rule's evidenced periods (rules may apply only to the
  periods they were evidenced on).

Identity axes and economic periods are reported from the XML (not the cohort table);
the cohort table is recorded beside them for comparison only (`forced: false`).

    python -m scripts.profile_pilot.census_validate run --data-root D --run-id stageb-... [--scope light|heavy|all] [--only CIK:DATE]
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

VALIDATE_VERSION = "census-validate.v0.1"
XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"
LINK = "{http://www.xbrl.org/2003/linkbase}"
XLINK = "{http://www.w3.org/1999/xlink}"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
RATE_FIELDS = ("interest_rate", "pik_rate", "interest_rate_floor", "basis_spread")
MAX_MISMATCHES = 25
LOW_HISTORY_POSITIONS = 50  # spec 6.3 tolerance table: Q1 < 50 positions = low_history
# context_inventory.classify_context pins NexPoint's explicit-member identity to one
# evidenced instant in code (not in the EXPLICIT_MEMBER_RULES table).
INHERITED_PERIOD_PINS = {
    "0001588272": dict(rule="nexpoint_explicit_investee_and_instrument", periods=["2023-03-31"],
                       source="pipeline/context_inventory.py:classify_context (NexPoint branch)"),
}
VALIDATE_CODE = ("scripts/profile_pilot/census_validate.py", "scripts/profile_pilot/cohort.py",
                 "pipeline/explicit_contexts.py")


class SourceRefused(ValueError):
    """The source cannot be read safely (DTD/entities, byte bound, not an XBRL instance)."""


class ValidationFailed(RuntimeError):
    """A source cross-check failed: a stage failure, never cached as validated (ruling R24)."""

    def __init__(self, report: dict):
        super().__init__("source cross-check failed: " + ", ".join(
            sorted(n for n, c in report["checks"].items() if c["status"] == "fail")))
        self.report = report


def _ascii(text) -> str:
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


def _local(qname: str) -> str:
    return str(qname).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _joined(node) -> str:
    """Whitespace-normalised text of an element, text nodes joined by a space (the census
    contract for typed members and footnote resources)."""
    return " ".join(" ".join(node.itertext()).split())


def _dec(text):
    try:
        value = Decimal(str(text).strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


# ---------------------------------------------------------------- independent source reader

def _refuse_prolog_dtd(data: bytes) -> None:
    """Refuse a DOCTYPE anywhere in the prolog (before the root element)."""
    i, n = 0, len(data)
    if data.startswith(b"\xef\xbb\xbf"):
        i = 3
    while i < n:
        while i < n and data[i:i + 1] in (b" ", b"\t", b"\r", b"\n"):
            i += 1
        if data.startswith(b"<?", i):
            end = data.find(b"?>", i)
            i = n if end < 0 else end + 2
        elif data.startswith(b"<!--", i):
            end = data.find(b"-->", i)
            i = n if end < 0 else end + 3
        elif data.startswith(b"<!", i):
            raise SourceRefused("DOCTYPE/DTD declarations are not permitted in the source")
        else:
            return


def read_source(path, *, max_bytes: int = 120_000_000) -> dict:
    """Index one instance with the stdlib parser: contexts, root-level facts, footnote links."""
    path = Path(path)
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise SourceRefused("source exceeds byte bound " + str(max_bytes))
    _refuse_prolog_dtd(data)
    root = ET.fromstring(data)
    if root.tag != XBRLI + "xbrl":
        raise SourceRefused("root element is not xbrli:xbrl")
    contexts = {}
    for node in root.findall(XBRLI + "context"):
        period = node.find(XBRLI + "period")
        instant = period.find(XBRLI + "instant") if period is not None else None
        start = period.find(XBRLI + "startDate") if period is not None else None
        end = period.find(XBRLI + "endDate") if period is not None else None
        if instant is not None and start is None and end is None:
            shaped = dict(kind="instant", instant=(instant.text or "").strip())
        elif start is not None and end is not None and instant is None:
            shaped = dict(kind="duration", start=(start.text or "").strip(), end=(end.text or "").strip())
        elif period is not None and period.find(XBRLI + "forever") is not None:
            shaped = dict(kind="forever")
        else:
            shaped = dict(kind="unresolved")
        ident = node.find(XBRLI + "entity/" + XBRLI + "identifier")
        explicit, typed = [], []
        for member in node.iter():
            if member.tag == XBRLDI + "explicitMember":
                explicit.append([member.get("dimension", ""), (member.text or "").strip()])
            elif member.tag == XBRLDI + "typedMember":
                typed.append(dict(axis=member.get("dimension", ""), value=_joined(member)))
        contexts[node.get("id", "")] = dict(
            period=shaped, explicit=explicit, typed=typed,
            entity=dict(scheme=ident.get("scheme", "") if ident is not None else "",
                        identifier=(ident.text or "").strip() if ident is not None else ""))
    facts = []
    for node in root:
        if node.get("contextRef") is None:
            continue
        tag = node.tag
        facts.append(dict(ordinal=len(facts), namespace=tag[1:].split("}", 1)[0] if tag.startswith("{") else "",
                          local=_local(tag), id=node.get("id"), context=node.get("contextRef"),
                          unit=node.get("unitRef"), decimals=node.get("decimals"),
                          nil=node.get(XSI_NIL) in ("true", "1"), text=(node.text or "").strip(),
                          full="".join(node.itertext()).strip()))
    every = sum(1 for node in root.iter() if node.get("contextRef") is not None)
    links = root.findall(LINK + "footnoteLink")
    locators, notes, arcs = {}, {}, []
    for link in links:
        for node in link:
            label = node.get(XLINK + "label", "")
            if node.tag == LINK + "loc":
                locators[label] = node.get(XLINK + "href", "").split("#", 1)[-1]
            elif node.tag == LINK + "footnote":
                notes[label] = _joined(node)
            elif node.tag == LINK + "footnoteArc":
                arcs.append((node.get(XLINK + "from", ""), node.get(XLINK + "to", "")))
    dped = sorted({f["full"] for f in facts if f["local"] == "DocumentPeriodEndDate" and not f["nil"]})
    return dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), contexts=contexts, facts=facts,
                nested_facts=every - len(facts), footnote_links=len(links), locators=locators,
                footnotes=notes, arcs=arcs, dped=dped,
                document_types=sorted({f["full"] for f in facts if f["local"] == "DocumentType"}))


# ---------------------------------------------------------------- matching

class _Matcher:
    """Find the source fact a census fact claims to be: by fact id, else by (namespace,
    local name, context id) and occurrence order among census facts without an id."""

    def __init__(self, source: dict, census_facts: list):
        self.by_id = {f["id"]: f for f in source["facts"] if f["id"]}
        self.by_key: dict[tuple, list] = {}
        for f in source["facts"]:
            if not f["id"]:
                self.by_key.setdefault((f["namespace"], f["local"], f["context"]), []).append(f)
        self.slot: dict[int, dict | None] = {}
        seen: Counter = Counter()
        for fact in sorted(census_facts, key=lambda f: f["i"]):
            if fact.get("id"):
                self.slot[fact["i"]] = self.by_id.get(fact["id"])
                continue
            key = (fact.get("namespace") or "", _local(fact["qname"]), fact["context_id"])
            candidates = self.by_key.get(key, [])
            self.slot[fact["i"]] = candidates[seen[key]] if seen[key] < len(candidates) else None
            seen[key] += 1

    def raw(self, fact: dict):
        return self.slot.get(fact["i"])


def _check(name: str) -> dict:
    return dict(name=name, status="pass", checked=0, failed=0, mismatches=[], examples=[])


def _fail(check: dict, **detail) -> None:
    check["failed"] += 1
    check["status"] = "fail"
    if len(check["mismatches"]) < MAX_MISMATCHES:
        check["mismatches"].append({k: _ascii(v) if isinstance(v, str) else v for k, v in detail.items()})


def _compare_numeric(check: dict, fact: dict, raw, *, count: bool = True) -> None:
    if count:
        check["checked"] += 1
    ident = dict(fact_id=fact.get("id"), qname=fact["qname"], context_id=fact["context_id"])
    if raw is None:
        return _fail(check, problem="no_source_fact", **ident)
    problems = []
    if raw["local"] != _local(fact["qname"]) or raw["namespace"] != (fact.get("namespace") or ""):
        problems.append("qname")
    if raw["context"] != fact["context_id"]:
        problems.append("context")
    if raw["unit"] != fact.get("unit_ref"):
        problems.append("unit")
    if raw["decimals"] != fact.get("decimals"):
        problems.append("decimals")
    source_value = None if raw["nil"] else _dec(raw["text"])
    expected_status = "nil" if raw["nil"] else ("reported" if source_value is not None else "invalid")
    if fact.get("status") != expected_status:
        problems.append("status")
    elif expected_status == "reported":
        census_value = _dec(fact.get("value"))
        if census_value is None or census_value != source_value:
            problems.append("value")
        if fact.get("raw") != raw["text"][:1000]:
            problems.append("raw_text")
    if problems:
        return _fail(check, problem=",".join(problems), source_value=raw["text"][:60],
                     census_value=fact.get("value"), **ident)
    if len(check["examples"]) < 5 and fact.get("id"):
        check["examples"].append(dict(ident, value=fact.get("value"), source_text=raw["text"][:60]))


def _period_equal(census_period: dict, raw_period: dict) -> bool:
    keys = ("kind", "instant", "start", "end")
    return all(census_period.get(k) == raw_period.get(k) for k in keys)


def _anchor(period: dict):
    return period.get("instant") or period.get("end")


# ---------------------------------------------------------------- checks

def check_source(doc: dict, source: dict) -> dict:
    check = _check("source")
    check["checked"] = 1
    document = doc["document"]
    if not (source["sha256"] == document.get("sha256_before") == document.get("sha256_after")
            and source["bytes"] == document.get("bytes")):
        _fail(check, problem="source_hash_or_size", source_sha256=source["sha256"],
              census_sha256_before=document.get("sha256_before"), source_bytes=source["bytes"],
              census_bytes=document.get("bytes"))
    check["examples"].append(dict(sha256=source["sha256"], bytes=source["bytes"]))
    return check


def check_document(doc: dict, source: dict) -> dict:
    check = _check("document")
    meta = doc["document_metadata"]
    pairs = (("document_period_end_dates", source["dped"], meta.get("document_period_end_dates")),
             ("document_types", source["document_types"], meta.get("document_types")),
             ("entity_identifiers", sorted({c["entity"]["identifier"] for c in source["contexts"].values()}),
              meta.get("entity_identifiers")))
    for label, raw, census in pairs:
        check["checked"] += 1
        if list(raw) != list(census or []):
            _fail(check, problem=label, source=raw, census=census)
    check["document_type"] = source["document_types"]
    check["document_period_end_dates"] = source["dped"]
    return check


def check_fact_inventory(doc: dict, source: dict) -> dict:
    check = _check("fact_inventory")
    census_keys = Counter(((f.get("namespace") or ""), _local(f["qname"]), f["context_id"]) for f in doc["facts"])
    raw_keys = Counter((f["namespace"], f["local"], f["context"]) for f in source["facts"])
    check["checked"] = len(source["facts"])
    check["source_facts"], check["census_facts"] = len(source["facts"]), len(doc["facts"])
    check["source_nested_facts"] = source["nested_facts"]
    for key in sorted(set(census_keys) | set(raw_keys), key=str):
        if census_keys[key] != raw_keys[key]:
            _fail(check, problem="count", qname=key[1], namespace=key[0], context_id=key[2],
                  source=raw_keys[key], census=census_keys[key])
    ordinal_mismatch = 0
    by_i = {f["i"]: f for f in doc["facts"]}
    for raw in source["facts"]:
        fact = by_i.get(raw["ordinal"])
        if fact is None or (fact.get("id"), fact["context_id"], _local(fact["qname"])) != (
                raw["id"], raw["context"], raw["local"]):
            ordinal_mismatch += 1
    check["ordinal_mismatches"] = ordinal_mismatch
    if ordinal_mismatch:
        _fail(check, problem="document_ordinal", mismatched=ordinal_mismatch)
    if source["nested_facts"] and doc["channels"]["numeric_facts"]["state"] == "complete":
        _fail(check, problem="nested_facts_in_complete_census", nested=source["nested_facts"])
    return check


def _compare_context(check: dict, context: dict, raw) -> None:
    check["checked"] += 1
    if raw is None:
        return _fail(check, problem="no_source_context", context_id=context["id"])
    problems = []
    if not _period_equal(context["period"], raw["period"]):
        problems.append("period")
    if context["entity"] != raw["entity"]:
        problems.append("entity")
    if [list(d) for d in context["dimensions"]] != raw["explicit"]:
        problems.append("explicit_dimensions")
    if [dict(axis=d["axis"], value=d["value"]) for d in context["typed_dimensions"]] != raw["typed"]:
        problems.append("typed_dimensions")
    if problems:
        _fail(check, problem=",".join(problems), context_id=context["id"],
              census_period=context["period"], source_period=raw["period"])


def check_contexts(doc: dict, source: dict) -> dict:
    check = _check("contexts")
    census_ids = {c["id"] for c in doc["contexts"]}
    for context in doc["contexts"]:
        _compare_context(check, context, source["contexts"].get(context["id"]))
    for missing in sorted(set(source["contexts"]) - census_ids):
        _fail(check, problem="context_missing_from_census", context_id=missing)
    return check


def check_comparative_contexts(doc: dict, source: dict, matcher: _Matcher) -> dict:
    """Comparative = the context's period anchor is not a DocumentPeriodEndDate in the SOURCE."""
    check = _check("comparative_contexts")
    dped = set(source["dped"])
    raw_ids = sorted(cid for cid, c in source["contexts"].items()
                     if c["period"]["kind"] in ("instant", "duration") and _anchor(c["period"]) not in dped)
    census_by_id = {c["id"]: c for c in doc["contexts"]}
    facts_by_context: dict[str, list] = {}
    for fact in doc["facts"]:
        facts_by_context.setdefault(fact["context_id"], []).append(fact)
    raw_count = Counter(f["context"] for f in source["facts"])
    for cid in raw_ids:
        context = census_by_id.get(cid)
        if context is None:
            _fail(check, problem="comparative_context_missing", context_id=cid)
            continue
        _compare_context(check, context, source["contexts"][cid])
        census_facts = facts_by_context.get(cid, [])
        if len(census_facts) != raw_count[cid]:
            _fail(check, problem="fact_count", context_id=cid, source=raw_count[cid], census=len(census_facts))
        for fact in census_facts:
            if fact.get("unit_ref") is not None:  # counted as part of this context's check
                _compare_numeric(check, fact, matcher.raw(fact), count=False)
    for period in doc["periods"]:
        if period["kind"] not in ("instant", "duration"):
            continue
        expected = ("no_document_period_end" if not dped else
                    "document_period_end" if _anchor(period) in dped else "comparative")
        check["checked"] += 1
        if period["relation"] != expected:
            _fail(check, problem="relation", period=dict((k, period.get(k)) for k in ("kind", "instant", "start", "end")),
                  census=period["relation"], expected=expected)
    census_comparative = sorted(c["id"] for c in doc["contexts"]
                                if c["period"]["kind"] in ("instant", "duration")
                                and _anchor(c["period"]) not in dped)
    for extra in sorted(set(census_comparative) - set(raw_ids)):
        _fail(check, problem="comparative_context_not_in_source", context_id=extra)
    check["context_ids"] = raw_ids
    check["examples"] = [dict(context_id=cid, period=source["contexts"][cid]["period"],
                              facts=raw_count[cid]) for cid in raw_ids[:5]]
    return check


def check_numeric_facts(doc: dict, matcher: _Matcher) -> dict:
    check = _check("numeric_facts")
    for fact in doc["facts"]:
        if fact.get("unit_ref") is not None:
            _compare_numeric(check, fact, matcher.raw(fact))
    return check


def check_rates(doc: dict, source: dict, matcher: _Matcher) -> dict:
    check = _check("rates")
    rate_facts = [f for f in doc["facts"] if f.get("field") in RATE_FIELDS]
    text_valued = 0
    for fact in rate_facts:
        if fact.get("unit_ref") is None:  # e.g. Onex "1M SOFR + 7.00%" on a rate-named text concept
            text_valued += 1
            _compare_text(check, fact, matcher.raw(fact))
        else:
            _compare_numeric(check, fact, matcher.raw(fact))
    check["text_valued_rate_facts"] = text_valued
    qnames = {((f.get("namespace") or ""), _local(f["qname"])) for f in rate_facts}
    raw_count = sum(1 for f in source["facts"] if (f["namespace"], f["local"]) in qnames)
    check["source_facts_with_rate_qnames"] = raw_count
    if raw_count != len(rate_facts):
        _fail(check, problem="rate_qname_count", source=raw_count, census=len(rate_facts))
    by_i = {f["i"]: f for f in doc["facts"]}
    positions_checked = 0
    for position in doc["positions"]:
        for field in RATE_FIELDS:
            entry = position["fields"].get(field) or {}
            if entry.get("status") not in ("reported", "consistent_duplicate"):
                continue
            positions_checked += 1
            check["checked"] += 1
            value = _dec(entry.get("value"))
            for index in entry.get("fact_indices", []):
                fact = by_i.get(index)
                raw = matcher.raw(fact) if fact is not None else None
                if raw is not None and raw["unit"] is None:  # text-valued rate fact: exact text
                    backed = not raw["nil"] and raw["full"] == entry.get("value")
                else:
                    backed = (raw is not None and not raw["nil"] and value is not None
                              and _dec(raw["text"]) == value)
                if raw is None or raw["context"] != position["context_id"] or not backed:
                    _fail(check, problem="position_rate_not_backed", context_id=position["context_id"],
                          field=field, census_value=entry.get("value"),
                          source_value=None if raw is None else raw["text"][:60])
                    break
    check["position_rate_fields_checked"] = positions_checked
    check["rate_facts_checked"] = len(rate_facts)
    check["by_field"] = dict(Counter(f["field"] for f in rate_facts))
    return check


def _compare_text(check: dict, fact: dict, raw) -> bool:
    """Text/date/boolean/enumeration fact vs its source element; True when it matches."""
    check["checked"] += 1
    ident = dict(fact_id=fact.get("id"), qname=fact["qname"], context_id=fact["context_id"])
    if raw is None:
        _fail(check, problem="no_source_fact", **ident)
        return False
    if raw["nil"]:
        if fact.get("status") != "nil":
            _fail(check, problem="nil_status", census=fact.get("status"), **ident)
            return False
        return True
    if fact.get("status") != "reported" or raw["context"] != fact["context_id"]:
        _fail(check, problem="status_or_context", census=fact.get("status"), **ident)
        return False
    full = raw["full"]
    if fact.get("value_kind") == "text":
        ok = (hashlib.sha256(full.encode("utf-8")).hexdigest() == fact.get("text_sha256")
              and len(full) == fact.get("text_chars")
              and fact.get("raw") == (full if fact.get("text_stored") == "full" else full[:200]))
    else:
        ok = fact.get("raw") == full
    if not ok:
        _fail(check, problem="text", source_chars=len(full), census_chars=fact.get("text_chars"),
              source_prefix=full[:60], census_prefix=str(fact.get("raw"))[:60], **ident)
    return ok


def check_text_facts(doc: dict, matcher: _Matcher) -> dict:
    check = _check("text_facts")
    preferred = []
    for fact in doc["facts"]:
        if fact.get("unit_ref") is not None:
            continue
        raw = matcher.raw(fact)
        if _compare_text(check, fact, raw) and raw is not None and not raw["nil"] \
                and fact.get("value_kind") == "text" and fact.get("id"):
            preferred.append(dict(fact_id=fact.get("id"), qname=fact["qname"], context_id=fact["context_id"],
                                  chars=len(raw["full"]), sha256=fact.get("text_sha256"),
                                  prefix=_ascii(raw["full"][:60])))
    check["examples"] = sorted(preferred, key=lambda e: -e["chars"])[:5]
    return check


def check_footnotes(doc: dict, source: dict) -> dict:
    check = _check("footnotes")
    state = doc["channels"]["footnotes"]["state"]
    check["census_state"], check["raw_footnote_links"] = state, source["footnote_links"]
    resources = doc["footnotes"]["resources"]
    check["resources"] = []
    if state == "unsupported":
        check["checked"] = 1
        if source["footnote_links"] or resources:
            _fail(check, problem="unsupported_but_source_has_footnote_links", links=source["footnote_links"])
        return check
    if state != "complete":
        check["status"] = "not_applicable"
        return check
    by_i = {f["i"]: f for f in doc["facts"]}
    linked: dict[str, set] = {}
    for start, end in source["arcs"]:
        linked.setdefault(end, set()).add(source["locators"].get(start))
    if len(resources) != len(source["footnotes"]):
        _fail(check, problem="resource_count", source=len(source["footnotes"]), census=len(resources))
    for resource in resources:
        check["checked"] += 1
        text = source["footnotes"].get(resource["label"])
        census_ids = sorted(str(by_i[i].get("id")) for i in resource["fact_indices"] if i in by_i)
        raw_ids = sorted(str(x) for x in linked.get(resource["label"], set()) if x)
        ok = (text is not None and hashlib.sha256(text.encode("utf-8")).hexdigest() == resource["text_sha256"]
              and len(text) == resource["text_chars"] and census_ids == raw_ids)
        if not ok:
            _fail(check, problem="footnote", label=resource["label"], census_fact_ids=census_ids[:10],
                  source_fact_ids=raw_ids[:10])
        check["resources"].append(dict(label=resource["label"], text_prefix=_ascii((text or "")[:100]),
                                       fact_ids=census_ids[:20], linked_facts=len(census_ids),
                                       status="pass" if ok else "fail"))
    return check


def explicit_rule_periods(cik: str) -> dict:
    """The per-CIK explicit identity rule and the periods it was evidenced on."""
    from pipeline import explicit_contexts
    rule = explicit_contexts.rule_for(cik)
    if rule is not None:
        return dict(rule=rule.name, periods=sorted(rule.periods) if rule.periods else None,
                    source="pipeline/explicit_contexts.py:EXPLICIT_MEMBER_RULES",
                    note="classify_context calls explicit_member_dimensions, which does not apply rule.periods")
    pinned = INHERITED_PERIOD_PINS.get(str(cik).zfill(10))
    if pinned is not None:
        return dict(pinned)
    return dict(rule=None, periods=None, source=None)


def check_explicit_rule_periods(doc: dict, cik: str) -> dict:
    """Per-CIK explicit identity rules may apply only on the periods they were evidenced on."""
    check = _check("explicit_rule_periods")
    rule = explicit_rule_periods(cik)
    check["rule"] = rule
    if rule["rule"] is None:
        check["status"] = "not_applicable"
        return check
    for context in doc["contexts"]:
        if context.get("role") != "confirmed_position" or context.get("role_reason") != rule["rule"]:
            continue
        check["checked"] += 1
        instant = context["period"].get("instant")
        if rule["periods"] is not None and instant not in rule["periods"]:
            _fail(check, problem="explicit_rule_outside_evidenced_period", context_id=context["id"],
                  instant=instant, rule=rule["rule"], evidenced_periods=rule["periods"])
    return check


# ---------------------------------------------------------------- evidence (reported, not forced)

def identity_evidence(doc: dict, source: dict, cik: str) -> dict:
    dped = set(source["dped"])
    fv_contexts = {f["context"] for f in source["facts"] if f["local"] == "InvestmentOwnedAtFairValue"}
    typed, explicit_only = Counter(), Counter()
    for cid in fv_contexts:
        context = source["contexts"].get(cid)
        if context is None or context["period"].get("instant") not in dped:
            continue
        if context["typed"]:
            for dim in context["typed"]:
                typed[dim["axis"]] += 1
        else:
            explicit_only[" + ".join(sorted(d[0] for d in context["explicit"])) or "(none)"] += 1
    reasons = Counter(c.get("role_reason") for c in doc["contexts"]
                      if c.get("role") == "confirmed_position" and c["period"].get("instant") in dped)
    return dict(raw_fv_contexts_at_document_period_end=dict(
                    typed_axes=dict(typed), explicit_only=sum(explicit_only.values()),
                    explicit_only_axis_sets=dict(explicit_only.most_common(8))),
                census_position_role_reasons=dict(reasons), explicit_rule=explicit_rule_periods(cik),
                note="identity axes observed in the XML at the document period end; the cohort "
                     "table is not an input")


def economic_periods(doc: dict, source: dict) -> dict:
    dped = set(source["dped"])
    instants, durations = Counter(), Counter()
    per_context = Counter(f["context"] for f in source["facts"])
    for cid, context in source["contexts"].items():
        period = context["period"]
        if period["kind"] == "instant":
            instants[period["instant"]] += per_context[cid]
        elif period["kind"] == "duration":
            durations[(period["start"], period["end"])] += per_context[cid]
    fv_instants = Counter(source["contexts"][f["context"]]["period"].get("instant")
                          for f in source["facts"]
                          if f["local"] == "InvestmentOwnedAtFairValue" and f["context"] in source["contexts"])
    return dict(document_period_end_dates=sorted(dped),
                comparative_instants=sorted(i for i in instants if i not in dped),
                durations=[dict(start=s, end=e, facts=n,
                                relation="document_period_end" if e in dped else "comparative")
                           for (s, e), n in sorted(durations.items())],
                fair_value_instants={k: v for k, v in sorted(fv_instants.items(), key=lambda kv: str(kv[0]))})


def cohort_evidence(doc: dict, source: dict, cik: str, report_date: str) -> dict:
    from scripts.profile_pilot import cohort
    member = next((m for m in cohort.PILOT_COHORT if m.cik == cik), None)
    positions = doc["summary"]["position_observations_current"]
    out = dict(forced=False, observed=dict(document_period_end_dates=source["dped"],
                                           document_types=source["document_types"],
                                           positions_current=positions))
    if member is None:
        return dict(out, cohort=None)
    role = ("q1" if report_date == member.q1 else "q2" if report_date == member.q2 else
            "verified_era" if report_date == cohort.VERIFIED_ERA_QUARTER else None)
    forms = [f.strip() for f in member.spec_forms.split("->")]
    expected_form = forms[0] if role == "q1" else forms[1] if role == "q2" else None
    rows = member.rows_q1 if role == "q1" else member.rows_q2 if role == "q2" else None
    return dict(out, cohort=dict(filer=member.filer, role=role, spec_form=expected_form, rows=rows),
                agreement=dict(report_date_is_document_period_end=report_date in source["dped"],
                               form_matches_spec=None if expected_form is None
                               else expected_form in source["document_types"],
                               positions_match_rows=None if rows is None else rows == positions))


def validate_against_source(doc: dict, source_path, *, cik: str | None = None,
                            report_date: str | None = None) -> dict:
    """Cross-check one census document against its raw source file. Never edits the census."""
    started = time.perf_counter()
    source = read_source(source_path)
    cik = cik or doc["document"]["cik"]
    report_date = report_date or doc["document"]["report_date"]
    matcher = _Matcher(source, doc["facts"])
    checks = [check_source(doc, source), check_document(doc, source), check_fact_inventory(doc, source),
              check_contexts(doc, source), check_comparative_contexts(doc, source, matcher),
              check_numeric_facts(doc, matcher), check_rates(doc, source, matcher),
              check_text_facts(doc, matcher), check_footnotes(doc, source),
              check_explicit_rule_periods(doc, cik)]
    positions = doc["summary"]["position_observations_current"]
    report = dict(validate_version=VALIDATE_VERSION, cik=cik, report_date=report_date,
                  source=dict(path=str(source_path), sha256=source["sha256"], bytes=source["bytes"],
                              parser="xml.etree.ElementTree (expat); independent of the lxml collector"),
                  checks={c["name"]: c for c in checks},
                  identity=identity_evidence(doc, source, cik), economic_periods=economic_periods(doc, source),
                  cohort=cohort_evidence(doc, source, cik, report_date),
                  history=dict(positions_current=positions,
                               **{"class": "low_history" if positions < LOW_HISTORY_POSITIONS else "normal"},
                               rule="spec 6.3: Q1 < 50 positions is low_history"))
    report["verdict"] = "fail" if any(c["status"] == "fail" for c in checks) else "pass"
    report["tally"] = {c["name"]: dict(status=c["status"], checked=c["checked"], failed=c["failed"])
                       for c in checks}
    report["seconds"] = round(time.perf_counter() - started, 3)
    return report


# ---------------------------------------------------------------- cached stage and CLI

def validate_fund_quarter(paths, entry: dict, *, lease_factory, bounds=None) -> dict:
    """Validate the census at the CURRENT census identity through run_cached_stage.

    The validation identity includes the census result file record, so a regenerated
    census (new fingerprint path) is always re-validated. Ares/BCRED re-parses are heavy
    and run only under the shared lease.
    """
    from scripts.profile_pilot import census_run, manifest
    from scripts.profile_pilot.census import Bounds
    from scripts.profile_pilot.paths import PathError
    from scripts.profile_pilot.protection import LeaseRefused
    base = dict(cik=entry["cik"], report_date=entry["quarter"], role=entry.get("role"))
    if entry.get("status") != "selected":
        return dict(base, status="unavailable", reason=entry.get("reason"))
    planned = census_run.plan(paths, entry, bounds or Bounds())
    if planned["status"] != "planned":
        return dict(base, status="unavailable", reason=planned["status"])
    census_path = paths.run_root / planned["relative"]
    if not census_path.is_file():
        return dict(base, status="census_missing", census_fingerprint=planned["fingerprint"])
    census_fingerprint = json.loads(census_path.read_text(encoding="ascii")).get(
        "identity", {}).get("fingerprint")
    if census_fingerprint != planned["fingerprint"]:
        return dict(base, status="census_identity_mismatch", census_path=str(census_path),
                    reason="census at " + planned["relative"] + " has identity " + str(census_fingerprint)[:16]
                    + ", current code/config gives " + planned["fingerprint"][:16] + "; use a new run id")
    census_record = manifest.file_record(census_path, "run/" + planned["relative"])
    code = [manifest.file_record(paths.code_root / rel, "code/" + rel) for rel in VALIDATE_CODE]
    deps = dict(source=planned["source_record"], census=census_record, code=code,
                runtime=dict(python=sys.version.split()[0]))
    identity = manifest.cache_identity("census_validation", deps, collector_version=VALIDATE_VERSION)
    relative = "validation/" + entry["cik"] + "/" + entry["quarter"] + ".json"  # ruling R23
    census_run.refuse_other_identity(paths, relative, identity["fingerprint"])
    measured: dict = {}

    def compute():
        started = time.perf_counter()
        memory = census_run._PeakMemory()
        with memory:
            doc = json.loads(census_path.read_text(encoding="ascii"))["result"]
            report = validate_against_source(doc, planned["source"], cik=entry["cik"],
                                             report_date=entry["quarter"])
        measured.update(wall_seconds=round(time.perf_counter() - started, 3), **memory.result())
        report["measurement"] = dict(measured)
        report["census_path"] = str(census_path)
        report["census_fingerprint"] = census_fingerprint
        if report["verdict"] != "pass":  # ruling R24: a failed cross-check is never cached
            raise ValidationFailed(report)
        return report

    lease_state: dict = {}

    def lease():
        if lease_factory is None:
            raise LeaseRefused("no lease factory supplied")
        return census_run._RecordingLease(lease_factory(), lease_state)

    workload = planned["workload"]
    heavy = manifest.classify_workload(workload)
    common = dict(base, heavy=heavy, fingerprint=identity["fingerprint"], census_path=str(census_path))
    try:
        result = manifest.run_cached_stage(paths, relative, identity, compute, workload=workload,
                                           lease=lease if (heavy and lease_factory is not None) else None)
    except LeaseRefused as exc:
        return dict(common, status="lease_refused", reason=_ascii(str(exc)), lease=lease_state or None)
    except ValidationFailed as exc:
        report = exc.report
        failed = sorted(name for name, c in report["checks"].items() if c["status"] == "fail")
        receipt = census_run.write_receipt(paths, "validation_failures", entry, identity["fingerprint"], dict(
            status="validation_failed", verdict=report["verdict"], failed_checks=failed,
            mismatches={name: report["checks"][name]["mismatches"] for name in failed},
            tally=report["tally"], census_path=str(census_path), census_fingerprint=census_fingerprint,
            source=report["source"]))
        return dict(common, status="validation_failed", verdict=report["verdict"], receipt=receipt,
                    failed_checks=failed, tally=report["tally"], lease=lease_state or None)
    except (PathError, manifest.StageInvalidated) as exc:
        return dict(common, status="stage_invalidated", reason=_ascii(str(exc)))
    report = result["result"]
    return dict(common, status="validated", verdict=report["verdict"], cache=result["cache"],
                path=result["path"], lease=lease_state or None, tally=report["tally"],
                measurement=report.get("measurement"))


def run(paths, *, scope: str, only=None) -> dict:
    from scripts.profile_pilot import census_run, manifest, protection
    inventory = manifest.load_inventory(paths, "primary_quarter_inventory")
    ordered = census_run._selected(inventory["fund_quarters"], scope, only)
    head = manifest.git_head(paths.code_root)
    results, stopped = [], None
    for entry in ordered:
        if stopped and entry["cik"] in census_run.LARGE:
            results.append(dict(cik=entry["cik"], report_date=entry["quarter"], status="lease_refused",
                                reason="not attempted: " + stopped))
            continue
        got = validate_fund_quarter(paths, entry,
                                    lease_factory=lambda: protection.shared_heavy_lease(paths, head=head))
        results.append(got)
        print(_ascii("validate " + got["cik"] + " " + got["report_date"] + ": " + got["status"]
                     + (" verdict=" + got["verdict"] + " cache=" + got["cache"] + " "
                        + json.dumps({k: [v["checked"], v["failed"]] for k, v in got["tally"].items()},
                                     sort_keys=True)
                        if got["status"] == "validated" else
                        " (" + str(got.get("reason") or got.get("failed_checks"))[:160] + ")")),
              flush=True)
        if got["status"] == "lease_refused" and not stopped:
            stopped = "lease refused earlier in this run: " + str(got.get("reason"))[:200]
    counts = Counter(r["status"] + (":" + r["verdict"] if r.get("verdict") else "") for r in results)
    return dict(run_id=paths.run_id, scope=scope, only=list(only or []), git_head=head,
                validate_version=VALIDATE_VERSION, counts=dict(counts), results=results)


def _census_summaries(paths) -> dict:
    """census path -> the census run summary that COMPUTED it (cache miss)."""
    found: dict[str, str] = {}
    for summary in sorted((paths.run_root / "census").glob("run_summary_*.json")):
        body = json.loads(summary.read_text(encoding="ascii"))
        for item in body.get("results", []):
            if item.get("status") == "collected" and item.get("cache") == "miss":
                found.setdefault(str(Path(item["path"])), "census/" + summary.name)
    return found


def publish_results(paths, summary: dict, summary_relative: str) -> dict:
    """Write-once results/authoritative.json (validation verdict pass ONLY) and
    results/excluded.json (every other fund-quarter, with its reason). Task 6 reads only
    authoritative.json (ruling R23/R24)."""
    from scripts.profile_pilot import census_run
    from scripts.profile_pilot.paths import write_once_json
    computed_by = _census_summaries(paths)
    listed, excluded = [], []
    for item in summary["results"]:
        key = dict(cik=item["cik"], report_date=item["report_date"], role=item.get("role"))
        if item["status"] == "validated" and item.get("verdict") == "pass":
            census_path = Path(item["census_path"])
            body = json.loads(census_path.read_text(encoding="ascii"))
            ident = body["result"].get("cache_identity") or {}
            listed.append(dict(key, census_path=str(census_path),
                               census_relative="census/" + item["cik"] + "/" + item["report_date"] + ".json",
                               fingerprint=body["identity"]["fingerprint"],
                               collector_version=body["identity"]["collector_version"],
                               census_version=ident.get("census_version"),
                               detector_version=ident.get("detector_version"),
                               census_sha256=manifest_sha(census_path),
                               census_run_summary=computed_by.get(str(census_path)),
                               validation_verdict="pass", validation_path=item["path"],
                               validation_fingerprint=item["fingerprint"],
                               validation_run_summary=summary_relative))
        else:
            excluded.append(dict(key, reason=item["status"], detail=item.get("reason"),
                                 failed_checks=item.get("failed_checks"), receipt=item.get("receipt")))
    common = dict(run_id=paths.run_id, git_head=summary["git_head"], validate_version=VALIDATE_VERSION,
                  collector_version=census_run.COLLECTOR_VERSION)
    write_once_json(paths, "results/authoritative.json", dict(
        common, rule="validation verdict pass only; one census per fund-quarter at census/{cik}/{date}.json",
        fund_quarters=listed))
    write_once_json(paths, "results/excluded.json", dict(common, fund_quarters=excluded))
    return dict(listed=len(listed), excluded=len(excluded))


def manifest_sha(path) -> str:
    from scripts.profile_pilot.manifest import sha256_file
    return sha256_file(path)


def main(argv=None) -> int:
    import argparse
    from scripts.profile_pilot import protection
    from scripts.profile_pilot.paths import PathError, discover_main_root, resolve_paths, write_json
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("run")
    cmd.add_argument("--main-root", type=Path, default=None)
    cmd.add_argument("--data-root", type=Path, required=True)
    cmd.add_argument("--run-id", required=True)
    cmd.add_argument("--scope", choices=("light", "heavy", "all"), default="light")
    cmd.add_argument("--only", action="append", default=None, help="CIK:YYYY-MM-DD (repeatable)")
    args = parser.parse_args(argv)
    if not args.run_id.startswith(("stageb-", "stageb2-")):
        print("run id must start with stageb- or stageb2- (ruling R18; stageb2- per Task B2-2a)")
        return 4
    code_root = Path(__file__).resolve().parents[2]
    try:
        paths = resolve_paths(main_repo_root=args.main_root or discover_main_root(code_root),
                              data_root=args.data_root, code_root=code_root, run_id=args.run_id)
    except PathError as exc:
        print("PATH ERROR: " + _ascii(str(exc)))
        return 4
    try:
        conflicts = protection.process_conflicts()
    except Exception as exc:  # discovery failure is a refusal
        print("REFUSED: process discovery failed: " + _ascii(str(exc)))
        return 4
    if conflicts:
        print("REFUSED: other pytest/rebuild processes: " + _ascii(json.dumps(conflicts)))
        return 4
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    started = time.perf_counter()
    published = None
    with protection.protected_session(paths, receipt="verification/" + stamp + "_validate_"
                                      + args.scope + "_preservation.json"):
        summary = run(paths, scope=args.scope, only=args.only)
        summary["seconds"] = round(time.perf_counter() - started, 1)
        relative = "validation/run_summary_" + args.scope + "_" + stamp + ".json"
        summary["summary_path"] = relative
        target = write_json(paths, relative, summary)
        if args.scope == "all" and not args.only:
            try:
                published = publish_results(paths, summary, relative)
            except PathError as exc:
                print("REFUSED: results already published in this run root: " + _ascii(str(exc)))
                return 4
    print("summary: " + json.dumps(summary["counts"], sort_keys=True) + " | " + str(target))
    if published is not None:
        print("published: authoritative " + str(published["listed"]) + " | excluded "
              + str(published["excluded"]))
    bad = [r for r in summary["results"] if r["status"] not in ("validated", "unavailable")
           or r.get("verdict", "pass") != "pass"]
    if bad:
        print("FAILED: " + ", ".join(r["cik"] + ":" + r["report_date"] + "=" + r["status"] for r in bad))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
