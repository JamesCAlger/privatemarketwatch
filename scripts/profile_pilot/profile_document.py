"""SP3 proper: the filer profile document v1 (programme spec section 4).

One document per filer, layered over the Stage A envelope (scripts/profile_pilot/envelope.py), which stays the
bitemporal entry store and resolver: `events` is the append-only log and `entries` its materialized view. v1 adds
`admissions` (spec 4 admission state per entry; confidence copied from the source file, never a support; contract
status_basis always "provisional" in SP3), `stubs` (one explicit insufficient-evidence stub per grid key without an
accepted entry, with the evidence that would close it: criterion 1), `wrapper_section` (executable blocks,
D-consolidate), `corrections` (spec 4.2; one-off: valid_from == valid_to == report_date, outside the envelope because
envelope intervals are half-open), `partition_predicate`, `detection_claims`, `disposition` (spec 7.1 file mapping) and
a `ledger`.

entry_state() returns the four spec states: accepted/candidate from the admission record, superseded/retracted from
the event log. resolve() answers only from ACCEPTED entries; a key without one answers with its stub; equally
specific accepted entries raise ProfileAmbiguityError. Pure except reading the JSON Schemas and load_document().
"""
from __future__ import annotations

import copy
from functools import lru_cache
import json
from pathlib import Path

from scripts.profile_pilot import envelope
from scripts.profile_pilot.census import POSITION_FIELDS, POSITION_RATE, POSITION_VALUE

SCHEMA_NAME = "filer_profile_document_v1"
SCHEMA_FILE = "filer_profile_document_v1.schema.json"
ENTRY_SCHEMA_FILE = "filer_profile_v0.schema.json"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
CONVERTER_VERSION = "profile-document.v1"
INCEPTION_REPORT_DATE = "2025-12-31"
ADMISSION_STATES = ("candidate", "accepted")
LIFECYCLE_STATES = ("candidate", "accepted", "superseded", "retracted")
ADMISSION_BASES = ("inherited_production", "census_confirmed_next_quarter", "census_unconfirmed", "adopted_predicate")
SOURCE_KINDS = ("census", "override_file", "predicate_code")
STUB_CAUSES = ("no_source", "census_unavailable", "census_stub", "candidate_pending_confirmation")

# The coverage grid of criterion 1: per-field axes, then filer-level keys. Key names reuse the Stage B census keys
# where the census derives the axis (column_contract.* = source concept set), so census entries land on the grid.
FIELD_KEYS = (tuple("column_contract." + f for f in POSITION_FIELDS)
              + tuple("scale_unit." + f for f in POSITION_VALUE + POSITION_RATE)
              + tuple("meaning." + f for f in POSITION_RATE))
FILER_KEYS = ("identifier_format.delimiter", "identifier_format.alternate_delimiters",
              "identifier_format.field_order", "identifier_format.dialect", "identifier_format.anchors",
              "subtotals_and_headings.aggregate_labels", "subtotals_and_headings.non_private_markers",
              "subtotals_and_headings.prefix_rules",
              "fund_level_concepts.entity_cik", "fund_level_concepts.entity_registrant_name",
              "fund_level_concepts.investments_at_fair_value_concept",
              "partition_structure.published_basis", "partition_structure.reporting_entities",
              "income_proofs.principal_currency", "income_proofs.rate_units", "income_proofs.duration",
              "income_proofs.estimated_income_calibration")
GRID_KEYS = FIELD_KEYS + FILER_KEYS
AXIS_OF_SECTION = {"column_contract": "source_concept_set", "fund_level_concepts": "source_concept_set",
                   "scale_unit": "scale_and_unit", "meaning": "meaning",
                   "identifier_format": "identifier_format_and_dialect",
                   "subtotals_and_headings": "partition_structure", "partition_structure": "partition_structure",
                   "income_proofs": "income_proofs"}


class ProfileDocumentError(ValueError):
    """A profile document violates its schema or the v1 document contract."""


class ProfileAmbiguityError(ProfileDocumentError):
    """Two equally specific ACCEPTED entries answer one key for one row and report date."""


def admission(state, basis, *, source_kind, mechanism, confidence, source_author, recorded_at, run_id, source,
              witness=None, inception_evaluation) -> dict:
    if state not in ADMISSION_STATES or basis not in ADMISSION_BASES or source_kind not in SOURCE_KINDS:
        raise ProfileDocumentError("bad admission " + repr((state, basis, source_kind)))
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None
    return dict(state=state, basis=basis, source_kind=source_kind, mechanism=mechanism, confidence=confidence,
                provenance=dict(who=CONVERTER_VERSION, source_author=source_author, when=recorded_at,
                                run_id=run_id, source=source),
                witness=dict(witness or {}),
                contract=dict(status_basis="provisional", inception_evaluation=inception_evaluation))


def stub(cik, key, cause, closing_evidence, *, entry_id=None, detail=None) -> dict:
    if key not in GRID_KEYS or cause not in STUB_CAUSES or not closing_evidence:
        raise ProfileDocumentError("bad stub " + repr((key, cause, closing_evidence)))
    return dict(stub_id=cik + ":stub:" + key, key=key, cause=cause, closing_evidence=closing_evidence,
                entry_id=entry_id, detail=dict(detail or {}))


@lru_cache(maxsize=1)
def _validator():
    import jsonschema
    from referencing import Registry, Resource
    document = json.loads((SCHEMA_DIR / SCHEMA_FILE).read_text(encoding="ascii"))
    entry = json.loads((SCHEMA_DIR / ENTRY_SCHEMA_FILE).read_text(encoding="ascii"))
    registry = Registry().with_resources([(ENTRY_SCHEMA_FILE, Resource.from_contents(entry)),
                                          (SCHEMA_FILE, Resource.from_contents(document))])
    return jsonschema.Draft202012Validator(document, registry=registry)


def valid_at(entry: dict, report_date: str) -> bool:
    """Half-open valid interval [valid_from, valid_to) of an envelope entry contains report_date."""
    lo, hi = entry["valid_from"], entry["valid_to"]
    return (lo is None or lo <= report_date) and (hi is None or report_date < hi)


def _live(document: dict, report_date: str) -> list:
    return [e for e in envelope.materialize_entries(document["events"])
            if e["recorded_until"] is None and valid_at(e, report_date)]


def validate_document(document: dict) -> None:
    errors = sorted(_validator().iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        raise ProfileDocumentError("schema: " + "/".join(map(str, errors[0].absolute_path)) + ": "
                                   + errors[0].message[:300])
    try:
        envelope.validate_profile(document["events"], sample_rows={})
    except envelope.EnvelopeError as exc:
        raise ProfileDocumentError(str(exc)) from exc
    materialized = envelope.materialize_entries(document["events"])
    if materialized != document["entries"]:
        raise ProfileDocumentError("entries are not the materialized view of the event log")
    ids = {e["entry_id"] for e in materialized}
    if set(document["admissions"]) != ids:
        raise ProfileDocumentError("admissions must cover exactly the entries: "
                                   + repr(sorted(ids ^ set(document["admissions"]))[:5]))
    foreign = [i for i in ids if not i.startswith(document["cik"] + ":")]
    if foreign:
        raise ProfileDocumentError("entries of another filer: " + repr(foreign[:5]))
    keys = [s["key"] for s in document["stubs"]]
    if len(keys) != len(set(keys)):
        raise ProfileDocumentError("one stub per key")
    for s in document["stubs"]:
        if s["key"] not in GRID_KEYS:
            raise ProfileDocumentError("stub for a key outside the grid: " + s["key"])
        if s["entry_id"] is not None and s["entry_id"] not in ids:
            raise ProfileDocumentError("stub names an unknown entry: " + s["entry_id"])
    accepted = {e["key"] for e in _live(document, document["inception_report_date"])
                if document["admissions"][e["entry_id"]]["state"] == "accepted"}
    clash = sorted(set(keys) & accepted)
    if clash:
        raise ProfileDocumentError("stub for a key that has an accepted entry: " + repr(clash[:5]))
    blocks = [b["block_id"] for b in document["wrapper_section"]["blocks"]]
    if len(blocks) != len(set(blocks)):
        raise ProfileDocumentError("block ids must be unique")
    for b in document["wrapper_section"]["blocks"]:
        if b["supersedes"] is not None and b["supersedes"] not in blocks:
            raise ProfileDocumentError("block supersedes an unknown block: " + b["supersedes"])
    corr = [c["correction_id"] for c in document["corrections"]]
    if len(corr) != len(set(corr)):
        raise ProfileDocumentError("correction ids must be unique")
    for c in document["corrections"]:
        if c["kind"] == "one_off" and not (c["report_date"] and c["valid_from"] == c["valid_to"] == c["report_date"]
                                           and c["report_dates"] == [c["report_date"]]):
            raise ProfileDocumentError("one_off correction must have valid_from == valid_to == report_date: "
                                       + c["correction_id"])


def entry_state(document: dict, entry_id: str) -> str:
    entries = {e["entry_id"]: e for e in envelope.materialize_entries(document["events"])}
    if entry_id not in entries:
        raise ProfileDocumentError("unknown entry " + repr(entry_id))
    if entries[entry_id]["recorded_until"] is not None:
        return ("superseded" if any(e["supersedes"] == entry_id for e in entries.values()) else "retracted")
    return document["admissions"][entry_id]["state"]


def resolve(document: dict, key: str, report_date: str, row: dict | None = None, *, as_of: str | None = None) -> dict:
    entries = envelope.materialize_entries(document["events"], as_of)
    accepted = [e for e in entries if document["admissions"][e["entry_id"]]["state"] == "accepted"]
    try:
        found = envelope.resolve_for_row(accepted, row or {}, key, report_date, None, as_of)
    except envelope.AmbiguousResolutionError as exc:
        raise ProfileAmbiguityError(str(exc)) from exc
    if found.found:
        return {"status": "resolved", "entry": found.entry}
    hit = next((s for s in document["stubs"] if s["key"] == key), None)
    if hit is not None:
        return {"status": "stub", "stub": copy.deepcopy(hit)}
    return {"status": "no_entry"}


def coverage(document: dict, report_date: str) -> dict:
    live = _live(document, report_date)
    stubs = {s["key"]: s for s in document["stubs"]}
    out = {}
    for key in GRID_KEYS:
        mine = [e for e in live if e["key"] == key]
        out[key] = dict(entry_ids=[e["entry_id"] for e in mine],
                        accepted_entry_ids=[e["entry_id"] for e in mine
                                            if document["admissions"][e["entry_id"]]["state"] == "accepted"],
                        stub=copy.deepcopy(stubs.get(key)))
    return out


def load_document(path) -> dict:
    document = json.loads(Path(path).read_text(encoding="ascii"))
    validate_document(document)
    return document
