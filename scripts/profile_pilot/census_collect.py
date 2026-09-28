"""Task 4 collector seam: parse ONE cached XBRL instance once, under explicit bounds.

DTD/entity expansion and network access are disabled; byte, context, fact, text,
footnote-arc and time bounds are explicit; the source is hashed before and after.
Every context (instant AND duration, every comparative date) and every root-level
fact is retained with QName, context id, raw and typed value, nil/invalid status,
unit/currency and decimals. Channel completeness is explicit; a bounded or failed
collection is returned as such, never as a smaller complete census.

Inherited: `pipeline.monetary_units.unit_definition` (unit kind and currency).
Everything else here is new pilot code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
import time

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TEXT_INLINE_CHARS = 1000
TEXT_PREVIEW_CHARS = 200
CHANNELS = ("contexts", "units", "numeric_facts", "text_facts", "footnotes", "identifiers")
CHANNEL_STATES = ("complete", "truncated", "failed", "unsupported", "not_collected")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ENUM_TOKEN = re.compile(r"(https?://\S+#\S+|[A-Za-z_][\w.-]*:[A-Za-z_][\w.-]*)")


@dataclass(frozen=True)
class Bounds:
    max_bytes: int = 120_000_000
    max_contexts: int = 40_000
    max_facts: int = 400_000
    max_text_chars: int = 150_000_000
    max_footnote_arcs: int = 1_000_000
    timeout_seconds: float = 600.0


def _local(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if str(tag).startswith("{") else ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ascii(text: str) -> str:
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


# ---------------------------------------------------------------- collection

PARSE_CHUNK_BYTES = 1 << 20
CLOCK_EVERY = 256
# Collection stages in order; a time bound at a stage truncates it and every later channel.
STAGE_CHANNELS = (("parse", CHANNELS), ("contexts", ("contexts", "identifiers")), ("units", ("units",)),
                  ("facts", ("numeric_facts", "text_facts")), ("nested_scan", ("numeric_facts", "text_facts")),
                  ("text_facts", ("text_facts",)), ("footnotes", ("footnotes",)))


class TimeBound(Exception):
    """The collection time bound expired at `stage` (every stage checks the clock)."""

    def __init__(self, stage: str, seconds: float):
        super().__init__("time bound " + str(seconds) + " s exceeded during " + stage)
        self.stage, self.seconds = stage, seconds


class _Clock:
    """Wall-clock bound for the WHOLE collection: parse (per fed chunk), context and unit
    enumeration, fact and text loops, the nested-item scan and footnote arcs."""

    def __init__(self, seconds: float):
        self.started = time.monotonic()
        self.seconds = seconds

    def expired(self) -> bool:
        return time.monotonic() - self.started >= self.seconds

    def check(self, stage: str) -> None:
        if self.expired():
            raise TimeBound(stage, self.seconds)


def _channels(state: str, reason: str | None = None) -> dict:
    return {name: dict(state=state, reason=reason, count=0) for name in CHANNELS}


def _qname(node, qname: str) -> tuple[str, str]:
    """(namespace, qname as written) for a prefixed QName in element text/attribute."""
    prefix = qname.split(":", 1)[0] if ":" in qname else None
    return node.nsmap.get(prefix, ""), qname


def _prefixed(node) -> str:
    """Document-prefix QName of an element tag, e.g. 'us-gaap:InvestmentOwnedAtFairValue'."""
    namespace, local = _ns(node.tag), _local(node.tag)
    prefix = node.prefix
    if prefix is None:
        prefix = next((p for p, uri in (node.nsmap or {}).items() if uri == namespace and p), None)
    return (prefix + ":" + local) if prefix else local


def _collect_contexts(root, bounds: Bounds, channels: dict, internal: dict, clock) -> list:
    contexts = []
    clock.check("contexts")
    nodes = root.findall("{%s}context" % XBRLI)
    channels["contexts"]["count"] = len(nodes)
    if len(nodes) > bounds.max_contexts:
        channels["contexts"].update(state="truncated", reason="context bound " + str(bounds.max_contexts))
        nodes = nodes[: bounds.max_contexts]
    seen = set()
    for number, node in enumerate(nodes):
        if number % CLOCK_EVERY == 0:
            clock.check("contexts")
        cid = node.get("id", "")
        if not cid or cid in seen:
            channels["contexts"].update(state="failed", reason="missing or duplicate context id")
            continue
        seen.add(cid)
        instant = node.findall("{%s}period/{%s}instant" % (XBRLI, XBRLI))
        start = node.findall("{%s}period/{%s}startDate" % (XBRLI, XBRLI))
        end = node.findall("{%s}period/{%s}endDate" % (XBRLI, XBRLI))
        forever = node.findall("{%s}period/{%s}forever" % (XBRLI, XBRLI))
        if len(instant) == 1 and not (start or end or forever):
            period = dict(kind="instant", instant=(instant[0].text or "").strip())
        elif len(start) == 1 and len(end) == 1 and not (instant or forever):
            period = dict(kind="duration", start=(start[0].text or "").strip(),
                          end=(end[0].text or "").strip())
        elif forever and not (instant or start or end):
            period = dict(kind="forever")
        else:
            period = dict(kind="unresolved")
        ident = node.find("{%s}entity/{%s}identifier" % (XBRLI, XBRLI))
        entity = dict(scheme=(ident.get("scheme", "") if ident is not None else ""),
                      identifier=((ident.text or "").strip() if ident is not None else ""))
        explicit, typed, full = [], [], []
        for dim in node.iter("{%s}explicitMember" % XBRLDI, "{%s}typedMember" % XBRLDI):
            axis = dim.get("dimension", "")
            axis_ns, _ = _qname(dim, axis)
            if dim.tag.endswith("explicitMember"):
                member = (dim.text or "").strip()
                member_ns, _ = _qname(dim, member)
                explicit.append([axis, member])
                full.append(dict(axis=axis, axis_namespace=axis_ns, value=member, kind="explicit",
                                 member_namespace=member_ns))
            else:
                value = " ".join(" ".join(dim.itertext()).split())
                typed.append(dict(axis=axis, value=value))
                full.append(dict(axis=axis, axis_namespace=axis_ns, value=value, kind="typed",
                                 member_namespace=""))
        internal[cid] = full
        contexts.append(dict(id=cid, entity=entity, period=period, dimensions=explicit,
                             typed_dimensions=typed))
    return contexts


def _collect_units(root, channels: dict, clock) -> dict:
    from pipeline.monetary_units import unit_definition
    units = {}
    clock.check("units")
    for number, unit in enumerate(root.findall("{%s}unit" % XBRLI)):
        if number % CLOCK_EVERY == 0:
            clock.check("units")
        uid = unit.get("id", "")
        measures = [" ".join(" ".join(m.itertext()).split()) for m in unit.iter("{%s}measure" % XBRLI)]
        definition = unit_definition(unit)
        if uid in units:
            definition = dict(unit_kind="unresolved", currency=None)
        units[uid] = dict(unit_kind=definition["unit_kind"], currency=definition["currency"],
                          measures=measures, provenance="inherited",
                          inherited_from="pipeline/monetary_units.py:unit_definition")
    channels["units"]["count"] = len(units)
    return units


def _numeric(node) -> tuple[str, str | None]:
    if node.get(XSI_NIL) in ("true", "1"):
        return "nil", None
    try:
        value = Decimal((node.text or "").strip())
    except InvalidOperation:
        return "invalid", None
    return ("reported", str(value)) if value.is_finite() else ("invalid", None)


def collect_facts(root, contexts: dict, units: dict, bounds: Bounds, channels: dict,
                  clock: _Clock) -> tuple[list, list]:
    """Every root-level fact (element with contextRef), in document order.

    Numeric facts (with a unitRef) are typed here; the rest are returned as
    pending nodes for collect_text_facts. Facts past the bound are not read and
    both fact channels are marked truncated: absence is then unobservable.
    """
    facts, pending = [], []
    total = 0
    clock.check("facts")
    for node in root:
        if not isinstance(node.tag, str):
            continue
        context_ref = node.get("contextRef")
        if context_ref is None:
            continue
        total += 1
        if total % CLOCK_EVERY == 0:
            clock.check("facts")
        if total > bounds.max_facts:
            for name in ("numeric_facts", "text_facts"):
                channels[name].update(state="truncated", reason="fact bound " + str(bounds.max_facts))
            break
        record = dict(i=len(facts), id=node.get("id"), qname=_prefixed(node), namespace=_ns(node.tag),
                      context_id=context_ref, context_resolved=context_ref in contexts,
                      decimals=node.get("decimals"), precision=node.get("precision"),
                      unit_ref=node.get("unitRef"), lang=node.get(XML_LANG), field=None,
                      group="unknown", provenance="derived", inherited_from=None)
        if record["unit_ref"] is not None:
            status, value = _numeric(node)
            unit = units.get(record["unit_ref"])
            raw = (node.text or "").strip()
            record.update(value_kind="numeric", status=status, value=value, raw=raw[:TEXT_INLINE_CHARS],
                          unit_kind=unit["unit_kind"] if unit else "unresolved",
                          currency=unit["currency"] if unit else None)
            channels["numeric_facts"]["count"] += 1
        else:
            # Typed by collect_text_facts; stays not_collected if the text pass stops early.
            record.update(value_kind="text", status="not_collected", value=None, raw="")
            pending.append((len(facts), node))
        facts.append(record)
    return facts, pending


def scan_nested_facts(root, root_level: int, channels: dict, clock) -> int:
    """Ruling R21: facts are read at root level only (EDGAR forbids tuples). Any element
    carrying contextRef below root level is an unread fact, so both fact channels are
    downgraded to truncated and absence becomes unobservable."""
    clock.check("nested_scan")
    nested = int(root.xpath("count(//*[@contextRef])")) - root_level
    clock.check("nested_scan")
    if nested > 0:
        for name in ("numeric_facts", "text_facts"):
            channels[name].update(state="truncated", reason="nested item facts not collected: "
                                  + str(nested) + " (root-level fact iteration only; ruling R21)")
    return nested


def _text_kind(text: str) -> tuple[str, object]:
    if text in ("true", "false"):
        return "boolean", text == "true"
    if _DATE_RE.fullmatch(text):
        try:
            date.fromisoformat(text)
            return "date", text
        except ValueError:
            return "text", text
    tokens = text.split()
    if tokens and len(text) <= 4000 and all(_ENUM_TOKEN.fullmatch(t) for t in tokens) \
            and any("#" in t for t in tokens):
        return "enumeration", text
    return "text", text


def collect_text_facts(pending: list, facts: list, root, bounds: Bounds, channels: dict,
                       texts: dict, clock: _Clock) -> dict:
    """Type text/date/boolean/enumeration facts; record in-instance footnote arcs.

    Full text is kept in memory (`texts`, for detector search) within the text
    bound; the serialised census stores long text as a preview plus hash/length.
    Footnote channel: `complete` only when a link:footnoteLink is present and every
    arc was read; otherwise `unsupported` (no footnote linkbase resolver is built).
    """
    budget = bounds.max_text_chars
    clock.check("text_facts")
    for index, node in pending:
        record = facts[index]
        clock.check("text_facts")
        if node.get(XSI_NIL) in ("true", "1"):
            record.update(value_kind="text", status="nil", value=None, raw="")
            channels["text_facts"]["count"] += 1
            continue
        text = "".join(node.itertext()).strip()
        budget -= len(text)
        if budget < 0:
            channels["text_facts"].update(state="truncated", reason="text bound " + str(bounds.max_text_chars))
            record.update(value_kind="text", status="not_collected", value=None, raw="")
            continue
        kind, value = _text_kind(text)
        record.update(value_kind=kind, status="reported", value=value)
        if kind == "text":
            texts[index] = text
            record.update(text_chars=len(text), text_sha256=_sha_text(text))
            if len(text) > TEXT_INLINE_CHARS:
                record.update(value=text[:TEXT_PREVIEW_CHARS], raw=text[:TEXT_PREVIEW_CHARS],
                              text_stored="preview")
            else:
                record.update(raw=text, text_stored="full")
        else:
            record["raw"] = text
        channels["text_facts"]["count"] += 1
    return _collect_footnotes(root, facts, bounds, channels, texts, clock)


def _collect_footnotes(root, facts: list, bounds: Bounds, channels: dict, texts: dict, clock) -> dict:
    clock.check("footnotes")
    links = root.findall("{%s}footnoteLink" % LINK)
    empty = dict(resources=[], arcs=0, unresolved_locators=0, links=len(links))
    if not links:
        channels["footnotes"].update(state="unsupported", reason="no link:footnoteLink in instance; "
                                     "no footnote linkbase resolver (ruling 9)")
        return empty
    by_id = {f["id"]: f["i"] for f in facts if f.get("id")}
    resources, arcs, unresolved = {}, 0, 0
    locators: dict[str, str] = {}
    pairs = []
    seen_nodes = 0
    for link in links:
        for node in link:
            seen_nodes += 1
            if seen_nodes % CLOCK_EVERY == 0:
                clock.check("footnotes")
            if not isinstance(node.tag, str):
                continue
            local = _local(node.tag)
            label = node.get("{%s}label" % XLINK, "")
            if local == "loc":
                locators[label] = node.get("{%s}href" % XLINK, "").split("#", 1)[-1]
            elif local == "footnote":
                text = " ".join(" ".join(node.itertext()).split())
                resources[label] = dict(label=label, id=node.get("id"),
                                        role=node.get("{%s}role" % XLINK), lang=node.get(XML_LANG),
                                        text_chars=len(text), text_sha256=_sha_text(text),
                                        preview=text[:TEXT_PREVIEW_CHARS], fact_indices=[],
                                        provenance="derived", inherited_from=None)
                texts["footnote:" + label] = text
            elif local == "footnoteArc":
                arcs += 1
                if arcs > bounds.max_footnote_arcs:
                    channels["footnotes"].update(state="truncated",
                                                 reason="footnote arc bound " + str(bounds.max_footnote_arcs))
                    break
                pairs.append((node.get("{%s}from" % XLINK, ""), node.get("{%s}to" % XLINK, "")))
    for source, target in pairs:
        fact_index = by_id.get(locators.get(source, ""))
        if target not in resources or fact_index is None:
            unresolved += 1
            continue
        resources[target]["fact_indices"].append(fact_index)
    if channels["footnotes"]["state"] == "not_collected":
        facts_truncated = channels["numeric_facts"]["state"] == "truncated"
        channels["footnotes"].update(
            state="truncated" if facts_truncated else "complete",
            reason="fact channel truncated; arcs to unread facts unresolvable" if facts_truncated else None)
    channels["footnotes"]["count"] = len(resources)
    for resource in resources.values():
        resource["fact_indices"] = sorted(set(resource["fact_indices"]))
    return dict(resources=sorted(resources.values(), key=lambda r: r["label"]), arcs=arcs,
                unresolved_locators=unresolved, links=len(links))


def _parse_fed(path: Path, clock) -> tuple:
    """Feed the file to lxml in chunks, hashing exactly the bytes parsed and checking the
    clock after every chunk, so the time bound covers the parse itself."""
    from lxml import etree
    parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False,
                             dtd_validation=False, recover=False, huge_tree=True)
    digest = hashlib.sha256()
    clock.check("parse")
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(PARSE_CHUNK_BYTES), b""):
            digest.update(chunk)
            parser.feed(chunk)
            clock.check("parse")
    root = parser.close()
    return root, digest.hexdigest()


def collect_instance(path, *, bounds: Bounds = Bounds(), clock=None) -> dict:
    """Parse ONE instance once; return the raw collection plus in-memory texts.

    Never raises for source problems: a failed or bounded collection is returned
    with explicit channel states so no caller can mistake it for a complete census.
    The time bound covers every stage (parse chunks, contexts, units, facts, the
    nested-item scan, text typing, footnote arcs); when it expires, the stage in
    progress and every channel not yet finished are `truncated`.
    """
    from lxml import etree
    started = time.monotonic()
    clock = clock or _Clock(bounds.timeout_seconds)
    path = Path(path)
    channels = _channels("not_collected")
    out = dict(source=dict(path=str(path), sha256_before=None, sha256_parsed=None, sha256_after=None,
                           bytes=None),
               errors=[], contexts=[], units={}, facts=[], footnotes=dict(resources=[], arcs=0,
               unresolved_locators=0, links=0), channels=channels, _internal={}, _texts={},
               nested_facts=None)
    done: set[str] = set()
    try:
        before = path.stat()
        out["source"]["bytes"] = before.st_size
        if before.st_size > bounds.max_bytes:
            raise ValueError("source exceeds byte bound " + str(bounds.max_bytes))
        out["source"]["sha256_before"] = _sha256_file(path)
        root, parsed = _parse_fed(path, clock)
        out["source"]["sha256_parsed"] = parsed
        if parsed != out["source"]["sha256_before"]:
            raise ValueError("source changed between hashing and parsing")
        tree = root.getroottree()
        if tree.docinfo.doctype or tree.docinfo.internalDTD is not None:
            raise ValueError("DTD is not permitted in an XBRL instance")
        if root.tag != "{%s}xbrl" % XBRLI:
            raise ValueError("root element is not xbrli:xbrl")
        for name in CHANNELS:
            channels[name].update(state="not_collected", reason=None)
        channels["contexts"]["state"] = "complete"
        out["contexts"] = _collect_contexts(root, bounds, channels, out["_internal"], clock)
        channels["identifiers"].update(state=channels["contexts"]["state"],
                                       reason=channels["contexts"]["reason"],
                                       count=sum(len(c["typed_dimensions"]) for c in out["contexts"]))
        done |= {"contexts", "identifiers"}
        channels["units"]["state"] = "complete"
        out["units"] = _collect_units(root, channels, clock)
        done.add("units")
        context_ids = {c["id"] for c in out["contexts"]}
        for name in ("numeric_facts", "text_facts"):
            channels[name]["state"] = "complete"
        facts, pending = collect_facts(root, context_ids, out["units"], bounds, channels, clock)
        out["facts"] = facts
        if channels["numeric_facts"]["state"] == "complete":
            out["nested_facts"] = scan_nested_facts(root, len(facts), channels, clock)
        done.add("numeric_facts")
        out["footnotes"] = collect_text_facts(pending, facts, root, bounds, channels,
                                              out["_texts"], clock)
        done |= {"text_facts", "footnotes"}
        del tree, root
        after = path.stat()
        out["source"]["sha256_after"] = _sha256_file(path)
        if (before.st_size, before.st_mtime_ns, out["source"]["sha256_before"]) != (
                after.st_size, after.st_mtime_ns, out["source"]["sha256_after"]):
            raise ValueError("source changed during collection")
    except TimeBound as exc:
        for name in CHANNELS:
            if name not in done:
                channels[name].update(state="truncated", reason=_ascii(str(exc)))
        if exc.stage == "parse":
            out.update(contexts=[], facts=[], units={}, _internal={}, _texts={})
    except (OSError, ValueError, etree.XMLSyntaxError) as exc:
        out["errors"].append(_ascii(type(exc).__name__ + ": " + str(exc))[:500])
        for name in CHANNELS:
            channels[name].update(state="failed", reason="collection failed")
        out.update(contexts=[], facts=[], units={}, _internal={}, _texts={})
        out["footnotes"] = dict(resources=[], arcs=0, unresolved_locators=0, links=0)
    out["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return out


def collection_state(channels: dict, errors: list) -> str:
    if errors or any(ch["state"] == "failed" for ch in channels.values()):
        return "failed"
    if any(ch["state"] in ("truncated", "not_collected") for ch in channels.values()):
        return "incomplete"
    return "complete"
