"""Filer-profile entry envelope: immutable bitemporal history and executable applicability.

Pure validator/resolver library (spec 6.2). Not a database service, not a CLI.

Data model
----------
A profile's history is an append-only EVENT LOG (a plain list of dicts) whose
transaction timestamps are non-decreasing:

  {"event": "assert", "event_id": "assert:<entry_id>", "entry_id": <id>,
   "recorded_at": T, "entry": <immutable entry body>}
  {"event": "retract", "event_id": "retract:<entry_id>", "entry_id": <id>,
   "recorded_at": T}

An entry body is the spec 6.2 envelope minus ``recorded_until``. Bodies and
their evidence are never mutated. ``materialize_entries`` replays the log and
returns envelopes whose ``recorded_until`` is the retraction time (a
materialized view); ``supersedes`` / ``supersession_kind`` are written once, on
the replacement assertion.

Two clocks, never mixed: valid time is ISO report dates (``YYYY-MM-DD``) and
transaction time is ISO UTC timestamps (``YYYY-MM-DDTHH:MM:SSZ``). Both are
fixed-width after strict validation, so string comparison is chronological.
Both intervals are half-open (``from <= q < to``); null means unbounded.

Entry IDs: ``{cik}:{key}:{partition_tag}:{form_tag}:v{n}`` where
partition_tag is ``all`` or ``p`` + 12 hex of the canonical predicate hash,
form_tag is ``allforms`` or ``form=<form_type>`` (``formh=`` + hash for form
strings outside ``[A-Za-z0-9-]``), and ``n`` is the next unused version for
that prefix. Duplicates are rejected on replay regardless of how they arose.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "filer_profile_v0.schema.json"

ENTRY_FIELDS = ("entry_id", "key", "value", "form_type", "applies_to", "valid_from", "valid_to",
                "recorded_at", "recorded_until", "supersedes", "supersession_kind", "author",
                "status", "provenance", "inherited_from", "support", "evidence",
                "regression_pin")
BODY_FIELDS = tuple(f for f in ENTRY_FIELDS if f != "recorded_until")
AUTHORS = ("census", "agent", "human")
STATUSES = ("derived", "proposed", "verified", "promoted", "retired")
PROVENANCES = ("derived", "inherited")
SUPERSESSION_KINDS = ("correction", "change")

PREDICATE_FIELDS = {
    "axis_member": ("axis", "member"),
    "carrying_concept": ("field", "concept"),
    "segment_count": ("delimiter", "count"),
    "prefix": ("vocabulary",),
    "grammar_dialect": ("dialect",),
}
# Row position and context lists are evidence, never applicability predicates.
FORBIDDEN_PREDICATE_KINDS = frozenset({
    "row_ordinal", "row_ordinals", "row_number", "row_numbers", "row_range", "row_index",
    "row_list", "rows", "ordinal", "context_id", "context_ids", "context_list", "contexts"})
FORBIDDEN_PREDICATE_FIELDS = frozenset({
    "row", "rows", "ordinal", "ordinals", "row_number", "row_numbers", "row_range", "start",
    "end", "index", "context_id", "context_ids", "contexts", "ids"})

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_CIK_RE = re.compile(r"\d{10}")
_KEY_RE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)*")
_FORM_RE = re.compile(r"[A-Za-z0-9-]+")
_QNAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.-]*")
_FIELD_RE = re.compile(r"[a-z][a-z0-9_]*")


class EnvelopeError(ValueError):
    """An envelope, event log or query violates the spec 6.2 contract."""


class PredicateError(EnvelopeError):
    """An applies_to predicate cannot be admitted or evaluated."""


class UnknownPredicateError(PredicateError):
    """The predicate kind is not in the restricted vocabulary."""


class InvalidPredicateError(PredicateError):
    """A known predicate kind with a malformed body."""


class ForbiddenPredicateError(InvalidPredicateError):
    """Row ordinals, row ranges or context lists used as applicability."""


class PredicateEvaluationError(PredicateError):
    """The row lacks (or has a null in) the field a predicate needs; never read as 'no match'."""


class AmbiguousResolutionError(EnvelopeError):
    """Two equally specific entries apply to the same row and query."""


class OverlapError(EnvelopeError):
    """Equally specific entries overlap in some historical transaction slice."""


@dataclass(frozen=True)
class Resolution:
    """Typed resolver result: status is 'resolved' (entry set) or 'no_entry'."""

    status: str
    entry: dict | None = None

    @property
    def found(self) -> bool:
        return self.status == "resolved"


NO_ENTRY = Resolution("no_entry", None)


# ------------------------------------------------------------------ primitives

def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def _sha12(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("ascii")).hexdigest()[:12]


def _report_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise EnvelopeError(label + " must be an ISO report date YYYY-MM-DD, got " + repr(value))
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise EnvelopeError(label + " is not a real report date: " + repr(value)) from exc
    return value


def _opt_report_date(value: Any, label: str) -> str | None:
    return None if value is None else _report_date(value, label)


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _TS_RE.fullmatch(value):
        raise EnvelopeError(label + " must be an ISO UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got "
                            + repr(value))
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise EnvelopeError(label + " is not a real timestamp: " + repr(value)) from exc
    return value


def _contains(lo: str | None, hi: str | None, q: str) -> bool:
    """Half-open membership lo <= q < hi; callers pass one clock only."""
    return (lo is None or lo <= q) and (hi is None or q < hi)


def _overlaps(a_lo, a_hi, b_lo, b_hi) -> bool:
    return (a_lo is None or b_hi is None or a_lo < b_hi) and \
           (b_lo is None or a_hi is None or b_lo < a_hi)


# ------------------------------------------------------------------ predicates

def check_predicate(predicate: Any) -> None:
    """Admit null or one restricted structural predicate; raise otherwise."""
    if predicate is None:
        return
    if not isinstance(predicate, dict) or not isinstance(predicate.get("kind"), str):
        raise InvalidPredicateError("applies_to must be null or an object with a kind")
    kind = predicate["kind"]
    if kind in FORBIDDEN_PREDICATE_KINDS:
        raise ForbiddenPredicateError(kind + " is evidence, not an applicability predicate")
    if kind not in PREDICATE_FIELDS:
        raise UnknownPredicateError("unknown applies_to predicate kind " + repr(kind))
    fields = PREDICATE_FIELDS[kind]
    extra = set(predicate) - {"kind", *fields}
    if extra & FORBIDDEN_PREDICATE_FIELDS:
        raise ForbiddenPredicateError(kind + " predicate carries row/context selectors "
                                      + repr(sorted(extra)))
    missing = [f for f in fields if f not in predicate]
    if extra or missing:
        raise InvalidPredicateError(kind + " predicate fields must be exactly "
                                    + repr(list(fields)))
    if kind == "axis_member":
        if not all(isinstance(predicate[f], str) and _QNAME_RE.fullmatch(predicate[f])
                   for f in fields):
            raise InvalidPredicateError("axis_member needs axis and member QNames")
    elif kind == "carrying_concept":
        if not (isinstance(predicate["field"], str) and _FIELD_RE.fullmatch(predicate["field"])
                and isinstance(predicate["concept"], str)
                and _QNAME_RE.fullmatch(predicate["concept"])):
            raise InvalidPredicateError("carrying_concept needs a field name and a concept QName")
    elif kind == "segment_count":
        count = predicate["count"]
        if not (isinstance(predicate["delimiter"], str) and predicate["delimiter"]
                and isinstance(count, int) and not isinstance(count, bool) and count >= 1):
            raise InvalidPredicateError("segment_count needs a delimiter and a count >= 1")
    elif kind == "prefix":
        vocab = predicate["vocabulary"]
        if not (isinstance(vocab, list) and vocab and len(set(map(str, vocab))) == len(vocab)
                and all(isinstance(v, str) and v for v in vocab)):
            raise InvalidPredicateError("prefix needs a non-empty list of distinct strings")
    elif not (isinstance(predicate["dialect"], str) and predicate["dialect"]):
        raise InvalidPredicateError("grammar_dialect needs a dialect name")


def _canon_predicate(predicate: dict | None) -> str:
    if predicate is not None and predicate.get("kind") == "prefix":
        predicate = dict(predicate, vocabulary=sorted(predicate["vocabulary"]))
    return _canon(predicate)


def _row_text(row: dict, field: str, kind: str) -> str:
    if field not in row:
        raise PredicateEvaluationError("row has no " + repr(field) + " for " + kind)
    value = row[field]
    if value is None or (isinstance(value, float) and value != value):
        # A null is unknown, not "does not match": falling through here would send the
        # row silently to the null partition. Same explicit outcome as a missing field.
        raise PredicateEvaluationError(repr(field) + " is null; " + kind + " is unresolved "
                                       "for this row")
    if not isinstance(value, str):
        raise PredicateEvaluationError(repr(field) + " must be text for " + kind)
    return value


def _axis_member_matches(predicate: dict, row: dict) -> bool:
    axis, member = predicate["axis"], predicate["member"]
    if "dimensions" in row:
        pairs = row["dimensions"]
        if pairs is None:
            raise PredicateEvaluationError("'dimensions' is null; axis_member is unresolved "
                                           "for this row")
        if not isinstance(pairs, (list, tuple)) or not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in pairs):
            raise PredicateEvaluationError("row dimensions must be [axis, member] QName pairs")
        return any(p[0] == axis and p[1] == member for p in pairs)
    # dimensions_raw (bdc_holdings.csv) stores lower-cased axis and member local names.
    raw = _row_text(row, "dimensions_raw", "axis_member")
    axis_ln, member_ln = axis.split(":", 1)[1].lower(), member.split(":", 1)[1]
    for part in raw.split("|"):
        name, sep, value = part.partition("=")
        if sep and name.strip().lower() == axis_ln and value.strip() == member_ln:
            return True
    return False


def predicate_matches(predicate: dict | None, row: dict) -> bool:
    """Evaluate one admitted predicate against a raw row; missing fields raise."""
    check_predicate(predicate)
    if predicate is None:
        return True
    if not isinstance(row, dict):
        raise PredicateEvaluationError("rows must be dicts")
    kind = predicate["kind"]
    if kind == "axis_member":
        return _axis_member_matches(predicate, row)
    if kind == "carrying_concept":
        value = _row_text(row, predicate["field"] + "_concept", kind)
        concept = predicate["concept"]
        return bool(value) and (value == concept if ":" in value
                                else value == concept.split(":", 1)[1])
    if kind == "grammar_dialect":
        return _row_text(row, "grammar_dialect", kind) == predicate["dialect"]
    ident = _row_text(row, "investment_identifier", kind)
    if kind == "segment_count":
        segments = len(ident.split(predicate["delimiter"])) if ident else 0
        return segments == predicate["count"]
    return any(ident.startswith(p) for p in predicate["vocabulary"])


# ------------------------------------------------------------------ bodies

def _check_support(support: Any) -> None:
    def _int(v, lo):
        return isinstance(v, int) and not isinstance(v, bool) and v >= lo
    ok = isinstance(support, dict) and (
        (support.get("kind") == "prevalence" and set(support) == {"kind", "numerator", "denominator"}
         and _int(support["numerator"], 0) and _int(support["denominator"], 1)
         and support["numerator"] <= support["denominator"])
        or (support.get("kind") == "context_count" and set(support) == {"kind", "count"}
            and _int(support["count"], 0)))
    if not ok:
        raise EnvelopeError("support must be {kind: prevalence, numerator, denominator} or "
                            "{kind: context_count, count}; got " + repr(support))


def _check_evidence(evidence: Any) -> None:
    if not isinstance(evidence, list) or not evidence:
        raise EnvelopeError("evidence must be a non-empty list")
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str) or not item["kind"]:
            raise EnvelopeError("evidence items must be objects with a kind")
        if item["kind"] == "sample_rows" and not (
                isinstance(item.get("rows"), list) and item["rows"]
                and all(isinstance(r, dict) for r in item["rows"])):
            raise EnvelopeError("sample_rows evidence needs a non-empty list of row objects")
    _canon(evidence)


def _check_body(body: Any) -> None:
    if not isinstance(body, dict) or set(body) != set(BODY_FIELDS):
        got = set(body) if isinstance(body, dict) else set()
        raise EnvelopeError("entry body fields must be exactly the envelope fields; unexpected "
                            + repr(sorted(got - set(BODY_FIELDS))) + ", missing "
                            + repr(sorted(set(BODY_FIELDS) - got)))
    if not isinstance(body["entry_id"], str) or not body["entry_id"]:
        raise EnvelopeError("entry_id must be a non-empty string")
    if not isinstance(body["key"], str) or not _KEY_RE.fullmatch(body["key"]):
        raise EnvelopeError("key must be a dotted lower-case name: " + repr(body["key"]))
    try:
        _canon(body["value"])
    except (TypeError, ValueError) as exc:
        raise EnvelopeError("value must be plain JSON") from exc
    if body["form_type"] is not None and (not isinstance(body["form_type"], str)
                                          or not body["form_type"]):
        raise EnvelopeError("form_type must be null or a non-empty string")
    check_predicate(body["applies_to"])
    lo = _opt_report_date(body["valid_from"], "valid_from")
    hi = _opt_report_date(body["valid_to"], "valid_to")
    if lo is not None and hi is not None and hi <= lo:
        raise EnvelopeError("empty or reversed valid interval [" + lo + ", " + hi + ")")
    _timestamp(body["recorded_at"], "recorded_at")
    if (body["supersedes"] is None) != (body["supersession_kind"] is None):
        raise EnvelopeError("supersedes and supersession_kind must be set together")
    if body["supersession_kind"] not in (None, *SUPERSESSION_KINDS):
        raise EnvelopeError("unknown supersession_kind " + repr(body["supersession_kind"]))
    for field, allowed in (("author", AUTHORS), ("status", STATUSES),
                           ("provenance", PROVENANCES)):
        if body[field] not in allowed:
            raise EnvelopeError(field + " must be one of " + repr(allowed))
    inherited = body["inherited_from"]
    if (body["provenance"] == "inherited") != (isinstance(inherited, str) and bool(inherited)) \
            or (body["provenance"] == "derived" and inherited is not None):
        raise EnvelopeError("inherited_from must be set exactly when provenance is inherited")
    _check_support(body["support"])
    _check_evidence(body["evidence"])
    if body["regression_pin"] is not None:
        raise EnvelopeError("regression_pin must be null in the pilot")


# ------------------------------------------------------------------ replay

@dataclass
class _Log:
    bodies: dict  # entry_id -> body, in log order
    retracted_at: dict  # entry_id -> retraction timestamp


def _check_piece(old: dict, piece: dict) -> None:
    for field in ("key", "form_type"):
        if piece[field] != old[field]:
            raise EnvelopeError("supersedes " + old["entry_id"] + " but changes " + field)
    if _canon_predicate(piece["applies_to"]) != _canon_predicate(old["applies_to"]):
        raise EnvelopeError("supersedes " + old["entry_id"] + " but changes applies_to")


def _check_group(old: dict, pieces: list) -> None:
    kinds = {p["supersession_kind"] for p in pieces}
    old_id, lo, hi = old["entry_id"], old["valid_from"], old["valid_to"]
    if kinds == {"correction"} and len(pieces) == 1:
        new = pieces[0]
        if (new["valid_from"], new["valid_to"]) != (lo, hi):
            raise EnvelopeError("correction superseding " + old_id + " must keep its valid interval")
        if _canon(new["evidence"]) == _canon(old["evidence"]):
            raise EnvelopeError("correction superseding " + old_id + " needs fresh evidence")
        return
    if kinds == {"change"} and len(pieces) == 2:
        hist, new = sorted(pieces, key=lambda p: (p["valid_from"] is not None, p["valid_from"] or ""))
        q = new["valid_from"]
        if (hist["valid_from"], hist["valid_to"], new["valid_to"]) != (lo, q, hi) or q is None \
                or not ((lo is None or lo < q) and (hi is None or q < hi)):
            raise EnvelopeError("change superseding " + old_id + " must split its valid interval "
                                "at one boundary Q strictly inside it")
        if _canon(hist["value"]) != _canon(old["value"]) or \
                _canon(new["value"]) == _canon(old["value"]):
            raise EnvelopeError("change superseding " + old_id + " must keep the old value before "
                                "Q and carry a different value from Q")
        return
    raise EnvelopeError("supersession of " + old_id + " must be one correction or two change "
                        "pieces; got " + repr(sorted(kinds)) + " x" + str(len(pieces)))


def _replay(events: Any) -> _Log:
    """Validate the whole log and return its assertion bodies and retraction times."""
    if not isinstance(events, list):
        raise EnvelopeError("events must be a list")
    prev = None
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            raise EnvelopeError("event[" + str(i) + "] must be an object")
        ts = _timestamp(event.get("recorded_at"), "event[" + str(i) + "].recorded_at")
        if prev is not None and ts < prev:
            raise EnvelopeError("event log transaction timestamps must be non-decreasing: event["
                                + str(i) + "] at " + ts + " follows " + prev)
        prev = ts
    log = _Log({}, {})
    event_ids: set = set()
    groups: dict = {}
    for i, event in enumerate(events):
        ts, kind, target = event["recorded_at"], event.get("event"), event.get("entry_id")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise EnvelopeError("event[" + str(i) + "] needs an event_id")
        if event_id in event_ids:
            raise EnvelopeError("duplicate event_id " + repr(event_id))
        event_ids.add(event_id)
        if kind == "assert":
            if set(event) != {"event", "event_id", "entry_id", "recorded_at", "entry"}:
                raise EnvelopeError("malformed assert event[" + str(i) + "]")
            body = event["entry"]
            _check_body(body)
            if body["entry_id"] != target or body["recorded_at"] != ts:
                raise EnvelopeError("assert event[" + str(i) + "] disagrees with its entry body")
            if target in log.bodies:
                raise EnvelopeError("duplicate entry_id " + repr(target))
            sup = body["supersedes"]
            if sup is not None:
                if sup not in log.bodies or log.retracted_at.get(sup) != ts:
                    raise EnvelopeError(target + " supersedes " + repr(sup) + ", which was not "
                                        "asserted earlier and retracted at " + ts)
                _check_piece(log.bodies[sup], body)
                groups.setdefault(sup, []).append(body)
            log.bodies[target] = body
        elif kind == "retract":
            if set(event) != {"event", "event_id", "entry_id", "recorded_at"}:
                raise EnvelopeError("malformed retract event[" + str(i) + "]")
            if target not in log.bodies:
                raise EnvelopeError("retraction of unknown entry " + repr(target))
            if target in log.retracted_at:
                raise EnvelopeError(repr(target) + " is already retracted")
            if ts <= log.bodies[target]["recorded_at"]:
                raise EnvelopeError("recorded_until " + ts + " must be later than recorded_at "
                                    + log.bodies[target]["recorded_at"] + " for " + target)
            log.retracted_at[target] = ts
        else:
            raise EnvelopeError("event[" + str(i) + "] kind must be assert or retract")
    for sup, pieces in groups.items():
        _check_group(log.bodies[sup], pieces)
    return log


def _envelope(body: dict, until: str | None) -> dict:
    entry = copy.deepcopy(body)
    entry["recorded_until"] = until
    return {field: entry[field] for field in ENTRY_FIELDS}


def materialize_entries(events: list, as_of: str | None = None) -> list[dict]:
    """Envelopes for every assertion known at ``as_of`` (all, if None).

    ``recorded_until`` is the retraction time when that retraction was already
    recorded at ``as_of``; later events are invisible. Returned dicts are copies.
    """
    if as_of is not None:
        _timestamp(as_of, "as_of")
    log = _replay(events)
    out = []
    for entry_id, body in log.bodies.items():
        if as_of is not None and body["recorded_at"] > as_of:
            continue
        until = log.retracted_at.get(entry_id)
        if as_of is not None and until is not None and until > as_of:
            until = None
        out.append(_envelope(body, until))
    return out


# ------------------------------------------------------------------ writers

def _tags(cik: str, key: str, applies_to: dict | None, form_type: str | None) -> str:
    part = "all" if applies_to is None else "p" + _sha12(_canon_predicate(applies_to))
    if form_type is None:
        form = "allforms"
    elif _FORM_RE.fullmatch(form_type):
        form = "form=" + form_type
    else:
        form = "formh=" + _sha12(form_type)
    return cik + ":" + key + ":" + part + ":" + form + ":v"


def _next_id(log: _Log, prefix: str, taken: set) -> str:
    n = 1 + sum(1 for eid in log.bodies if eid.startswith(prefix))
    while prefix + str(n) in log.bodies or prefix + str(n) in taken:
        n += 1
    taken.add(prefix + str(n))
    return prefix + str(n)


def _assert_event(body: dict) -> dict:
    return {"event": "assert", "event_id": "assert:" + body["entry_id"],
            "entry_id": body["entry_id"], "recorded_at": body["recorded_at"], "entry": body}


def _append(events: list, new_events: list) -> list:
    out = copy.deepcopy(events) + copy.deepcopy(new_events)
    _replay(out)
    return out


def make_assertion(events: list, *, cik: str, key: str, value: Any, valid_from: str | None,
                   recorded_at: str, support: dict, evidence: list, valid_to: str | None = None,
                   form_type: str | None = None, applies_to: dict | None = None,
                   provenance: str = "derived", inherited_from: str | None = None) -> list:
    """Return a new log with one census/derived assertion appended."""
    log = _replay(events)
    if not isinstance(cik, str) or not _CIK_RE.fullmatch(cik):
        raise EnvelopeError("cik must be a 10-digit string: " + repr(cik))
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
        raise EnvelopeError("key must be a dotted lower-case name: " + repr(key))
    check_predicate(applies_to)
    if form_type is not None and (not isinstance(form_type, str) or not form_type):
        raise EnvelopeError("form_type must be null or a non-empty string")
    body = {"entry_id": _next_id(log, _tags(cik, key, applies_to, form_type), set()),
            "key": key, "value": value, "form_type": form_type, "applies_to": applies_to,
            "valid_from": valid_from, "valid_to": valid_to, "recorded_at": recorded_at,
            "supersedes": None, "supersession_kind": None, "author": "census",
            "status": "derived", "provenance": provenance, "inherited_from": inherited_from,
            "support": support, "evidence": evidence, "regression_pin": None}
    body = copy.deepcopy(body)
    _check_body(body)
    return _append(events, [_assert_event(body)])


def _live_target(log: _Log, entry_id: str) -> dict:
    if entry_id not in log.bodies:
        raise EnvelopeError("unknown entry " + repr(entry_id))
    if entry_id in log.retracted_at:
        raise EnvelopeError(repr(entry_id) + " is already retracted")
    cik = entry_id.split(":", 1)[0]
    if not _CIK_RE.fullmatch(cik):
        raise EnvelopeError("entry_id does not follow the {cik}:... scheme: " + repr(entry_id))
    return log.bodies[entry_id]


def _successor(old: dict, log: _Log, taken: set, recorded_at: str, kind: str, **fields) -> dict:
    body = copy.deepcopy(old)
    body.update(copy.deepcopy(fields))
    prefix = _tags(old["entry_id"].split(":", 1)[0], old["key"], old["applies_to"],
                   old["form_type"])
    body.update(entry_id=_next_id(log, prefix, taken), recorded_at=recorded_at,
                supersedes=old["entry_id"], supersession_kind=kind, author="census",
                status="derived", regression_pin=None)
    _check_body(body)
    return body


def _retract_event(entry_id: str, recorded_at: str) -> dict:
    return {"event": "retract", "event_id": "retract:" + entry_id, "entry_id": entry_id,
            "recorded_at": recorded_at}


def append_correction(events: list, entry_id: str, *, value: Any, recorded_at: str,
                      evidence: list, support: dict) -> list:
    """Retrospective correction: retract at T, replace over the same valid interval."""
    log = _replay(events)
    old = _live_target(log, entry_id)
    _timestamp(recorded_at, "recorded_at")
    _check_evidence(evidence)
    if _canon(evidence) == _canon(old["evidence"]):
        raise EnvelopeError("a correction requires fresh evidence, not the superseded evidence")
    new = _successor(old, log, set(), recorded_at, "correction", value=value,
                     evidence=evidence, support=support)
    return _append(events, [_retract_event(entry_id, recorded_at), _assert_event(new)])


def append_change(events: list, entry_id: str, *, effective_from: str, value: Any,
                  recorded_at: str, evidence: list, support: dict) -> list:
    """Genuine change at report date Q learned at T: split [from, Q) old, [Q, to) new.

    Q is the exclusive end of the historical piece and the inclusive start of the
    new piece; no day or quarter arithmetic is performed on it.
    """
    log = _replay(events)
    old = _live_target(log, entry_id)
    q = _report_date(effective_from, "effective_from")
    _timestamp(recorded_at, "recorded_at")
    lo, hi = old["valid_from"], old["valid_to"]
    if not ((lo is None or lo < q) and (hi is None or q < hi)):
        raise EnvelopeError("effective_from " + q + " must lie strictly inside the old valid "
                            "interval [" + str(lo) + ", " + str(hi) + ")")
    if _canon(value) == _canon(old["value"]):
        raise EnvelopeError("a change must carry a different value; same value as " + entry_id)
    _check_evidence(evidence)
    taken: set = set()
    hist = _successor(old, log, taken, recorded_at, "change", valid_to=q)
    new = _successor(old, log, taken, recorded_at, "change", valid_from=q, value=value,
                     evidence=evidence, support=support)
    return _append(events, [_retract_event(entry_id, recorded_at), _assert_event(hist),
                            _assert_event(new)])


# ------------------------------------------------------------------ validation

@lru_cache(maxsize=1)
def _entry_schema_validator():
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="ascii"))
    sub = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/entry"}
    return jsonschema.Draft202012Validator(sub)


def _check_slice(live: list, stamp: str, rows_by_key: dict) -> None:
    """Overlap check for one transaction slice.

    Only rows scoped to the key under check are evaluated: a row gathered for (or
    evidenced by) another key may legitimately lack the fields this key's predicates
    need, and must not abort validation of an unrelated key.
    """
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if a["key"] != b["key"] or a["form_type"] != b["form_type"]:
                continue
            if not _overlaps(a["valid_from"], a["valid_to"], b["valid_from"], b["valid_to"]):
                continue
            pa, pb = a["applies_to"], b["applies_to"]
            if (pa is None) != (pb is None):
                continue  # the null partition is an explicit fallback tier
            pair = a["entry_id"] + " and " + b["entry_id"]
            if pa is None or _canon_predicate(pa) == _canon_predicate(pb):
                raise OverlapError("slice " + stamp + ": " + pair + " are equally specific and "
                                   "overlap in valid time")
            rows = rows_by_key.get(a["key"], [])
            if not rows:
                raise OverlapError("slice " + stamp + ": " + pair + " overlap in valid time and "
                                   "are unprovably disjoint (no sample or evidence rows)")
            for row in rows:
                if predicate_matches(pa, row) and predicate_matches(pb, row):
                    raise OverlapError("slice " + stamp + ": a sample row is selected by both "
                                       + pair)


def validate_profile(events: list, sample_rows: list | dict | None = None) -> dict:
    """Validate the log, every materialized envelope and every transaction slice.

    The live set only changes at event timestamps, so checking the live set at
    each distinct timestamp also covers the state just before it (the previous
    slice, or the empty set before the first event). Partition overlap is
    checked by evaluating both predicates on the rows scoped to that key:
    ``sample_rows`` given as ``{key: [rows]}`` (per key), or as a plain list
    (rows for every key), plus the ``sample_rows`` evidence carried by the
    profile's own entries OF THAT KEY. Rows of other keys are never evaluated.
    """
    entries = materialize_entries(events)
    validator = _entry_schema_validator()
    for entry in entries:
        errors = sorted(validator.iter_errors(entry), key=lambda e: list(e.path))
        if errors:
            raise EnvelopeError("schema: " + entry["entry_id"] + ": " + errors[0].message)
    keys = {e["key"] for e in entries}
    if isinstance(sample_rows, dict):
        unknown = sorted(set(sample_rows) - keys)
        if unknown:
            raise EnvelopeError("sample_rows scoped to keys the profile does not have: "
                                + repr(unknown))
        rows_by_key = {k: list(sample_rows.get(k) or []) for k in keys}
    else:
        common = list(sample_rows or [])
        rows_by_key = {k: list(common) for k in keys}
    for entry in entries:
        for item in entry["evidence"]:
            if item["kind"] == "sample_rows":
                rows_by_key[entry["key"]].extend(item["rows"])
    if not all(isinstance(r, dict) for rows in rows_by_key.values() for r in rows):
        raise EnvelopeError("sample rows must be dicts")
    stamps = sorted({e["recorded_at"] for e in entries}
                    | {e["recorded_until"] for e in entries if e["recorded_until"]})
    for stamp in stamps:
        live = [e for e in entries if _contains(e["recorded_at"], e["recorded_until"], stamp)]
        _check_slice(live, stamp, rows_by_key)
    return {"events": len(events), "entries": len(entries), "slices": len(stamps)}


# ------------------------------------------------------------------ resolution

def resolve_for_row(entries: list, row: dict, key: str, report_date: str,
                    form_type: str | None, as_of: str | None) -> Resolution:
    """Resolve one key for one row at report date R as believed at wall clock as_of.

    as_of None means the current state (entries with no recorded_until).
    Precedence: matching partition > null partition; then exact form > all-form.
    Equally specific applicable entries raise AmbiguousResolutionError.
    """
    _report_date(report_date, "report_date")
    if as_of is not None:
        _timestamp(as_of, "as_of")
    for entry in entries:
        check_predicate(entry["applies_to"])
    ranked = []
    for entry in entries:
        if entry["key"] != key:
            continue
        if not _contains(entry["valid_from"], entry["valid_to"], report_date):
            continue
        if as_of is None:
            if entry["recorded_until"] is not None:
                continue
        elif not _contains(entry["recorded_at"], entry["recorded_until"], as_of):
            continue
        if entry["form_type"] is not None and entry["form_type"] != form_type:
            continue
        if not predicate_matches(entry["applies_to"], row):
            continue
        ranked.append(((entry["applies_to"] is not None, entry["form_type"] is not None), entry))
    if not ranked:
        return NO_ENTRY
    best = max(rank for rank, _ in ranked)
    top = [entry for rank, entry in ranked if rank == best]
    if len(top) > 1:
        raise AmbiguousResolutionError("equally specific entries apply to one row: "
                                       + ", ".join(e["entry_id"] for e in top))
    return Resolution("resolved", copy.deepcopy(top[0]))
