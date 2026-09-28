"""Filer-profile pilot: immutable bitemporal entry history and executable applicability.

Covers spec 6.2 (envelope, applies_to partitions, two clocks, both supersession
kinds) and spec 8 deliverable 2 (as-of queries before/at/after the recording
time and the effective time for both kinds, finite intervals, correction after
change). Pure synthetic tests: no data roots are touched.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.profile_pilot import envelope as ev
from scripts.profile_pilot.envelope import (
    AmbiguousResolutionError,
    EnvelopeError,
    ForbiddenPredicateError,
    InvalidPredicateError,
    OverlapError,
    PredicateEvaluationError,
    UnknownPredicateError,
)

SCHEMA_PATH = (Path(__file__).resolve().parents[1] / "scripts" / "profile_pilot" / "schemas"
               / "filer_profile_v0.schema.json")

CIK = "0001901037"
KEY = "identifier_format.delimiter"
T0 = "2026-09-28T14:00:00Z"
T_MID = "2026-09-30T00:00:00Z"
T1 = "2026-10-01T09:00:00Z"
T_MID2 = "2026-10-15T00:00:00Z"
T2 = "2026-11-01T09:00:00Z"
T_AFTER = "2026-12-31T23:59:59Z"
T_BEFORE = "2026-01-01T00:00:00Z"

SUPPORT = {"kind": "prevalence", "numerator": 61, "denominator": 62}
EVID_A = [{"kind": "context_ids", "accession": "0001901037-24-000010", "ids": ["c-12", "c-13"]}]
EVID_B = [{"kind": "context_ids", "accession": "0001901037-25-000004", "ids": ["c-40"]}]
EVID_C = [{"kind": "context_ids", "accession": "0001901037-25-000020", "ids": ["c-77"]}]

PREFIX_LIEN = {"kind": "prefix", "vocabulary": ["First Lien", "Second Lien"]}
AXIS_EQUITY = {"kind": "axis_member", "axis": "us-gaap:InvestmentTypeAxis",
               "member": "us-gaap:EquitySecuritiesMember"}

ROW_LIEN = {"investment_identifier": "First Lien | Acme Corp | Term Loan",
            "dimensions_raw": "investmenttypeaxis=DebtSecuritiesMember|investmentidentifieraxis=x",
            "interest_rate_concept": "us-gaap:InvestmentInterestRate"}
ROW_EQUITY = {"investment_identifier": "Acme Holdings - Common Units",
              "dimensions_raw": "investmenttypeaxis=EquitySecuritiesMember",
              "interest_rate_concept": ""}
ROW_OTHER = {"investment_identifier": "Unitranche - Beta LLC",
             "dimensions_raw": "investmenttypeaxis=DebtSecuritiesMember",
             "interest_rate_concept": "us-gaap:InvestmentInterestRate"}
# Matched by BOTH the lien prefix and the equity axis member.
ROW_BOTH = {"investment_identifier": "First Lien | Gamma Inc | Preferred Equity",
            "dimensions_raw": "investmenttypeaxis=EquitySecuritiesMember",
            "interest_rate_concept": ""}


def _assert(events, value=" | ", **kw):
    params = dict(cik=CIK, key=KEY, value=value, valid_from="2022-09-30", recorded_at=T0,
                  support=SUPPORT, evidence=EVID_A)
    params.update(kw)
    return ev.make_assertion(events, **params)


def _live_value(events, report_date, as_of, row=None, form_type="10-K", key=KEY):
    entries = ev.materialize_entries(events)
    res = ev.resolve_for_row(entries, row or ROW_OTHER, key, report_date, form_type, as_of)
    return res


def _entry_validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="ascii"))
    sub = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/entry"}
    return jsonschema.Draft202012Validator(sub)


def _retraction(entry_id, recorded_at):
    return {"event": "retract", "event_id": "retract:" + entry_id, "entry_id": entry_id,
            "recorded_at": recorded_at}


# ------------------------------------------------------------ envelope basics

def test_make_assertion_produces_schema_valid_envelope_with_structured_id():
    events = _assert([])
    [entry] = ev.materialize_entries(events)
    assert entry["entry_id"] == CIK + ":" + KEY + ":all:allforms:v1"
    assert entry["recorded_until"] is None and entry["supersedes"] is None
    assert entry["author"] == "census" and entry["status"] == "derived"
    assert entry["regression_pin"] is None and entry["provenance"] == "derived"
    assert entry["support"] == SUPPORT and entry["evidence"] == EVID_A
    _entry_validator().validate(entry)
    assert ev.validate_profile(events)["entries"] == 1


def test_entry_ids_unique_across_partitions_forms_and_versions():
    events = _assert([])
    events = _assert(events, form_type="10-K", value=" / ")
    events = _assert(events, applies_to=PREFIX_LIEN, value=" ; ")
    events = _assert(events, applies_to=AXIS_EQUITY, form_type="10-K", value=" : ")
    events = _assert(events, value=" ~ ", valid_from="2019-12-31", valid_to="2020-12-31")
    ids = [e["entry_id"] for e in ev.materialize_entries(events)]
    assert len(set(ids)) == 5
    assert ids[0].endswith(":all:allforms:v1") and ids[4].endswith(":all:allforms:v2")
    assert ":form=10-K:" in ids[1]
    assert ids[2].split(":")[2] != ids[3].split(":")[2] != "all"


def test_schema_rejects_score_fields_nonnull_pin_and_unmeasured_support():
    validator = _entry_validator()
    [entry] = ev.materialize_entries(_assert([]))
    for mutate in (lambda e: e.update(confidence=0.9),
                   lambda e: e.update(regression_pin="tests/x.py::t"),
                   lambda e: e.update(support={"kind": "score", "value": 0.9}),
                   lambda e: e.update(support={"kind": "prevalence", "numerator": 3}),
                   lambda e: e.update(author="robot"),
                   lambda e: e.update(status="final"),
                   lambda e: e.update(applies_to={"kind": "row_ordinal", "rows": [1, 2]}),
                   lambda e: e.update(evidence=[])):
        bad = copy.deepcopy(entry)
        mutate(bad)
        assert not validator.is_valid(bad)
    ok = copy.deepcopy(entry)
    ok.update(author="human", status="promoted", support={"kind": "context_count", "count": 4})
    assert validator.is_valid(ok)


def test_make_assertion_rejects_unmeasured_support_and_empty_evidence():
    with pytest.raises(EnvelopeError, match="support"):
        _assert([], support={"kind": "prevalence", "numerator": 5, "denominator": 4})
    with pytest.raises(EnvelopeError, match="support"):
        _assert([], support={"kind": "prevalence", "numerator": 5, "denominator": 9,
                             "confidence": 0.8})
    with pytest.raises(EnvelopeError, match="evidence"):
        _assert([], evidence=[])


def test_empty_or_reversed_valid_interval_and_clock_mixing_rejected():
    with pytest.raises(EnvelopeError, match="valid interval"):
        _assert([], valid_from="2024-03-31", valid_to="2024-03-31")
    with pytest.raises(EnvelopeError, match="valid interval"):
        _assert([], valid_from="2024-03-31", valid_to="2023-12-31")
    with pytest.raises(EnvelopeError, match="report date"):
        _assert([], valid_from=T0)
    with pytest.raises(EnvelopeError, match="timestamp"):
        _assert([], recorded_at="2026-09-28")


# ------------------------------------------------------ retrospective correction

def test_correction_before_at_and_after_recording_time():
    base = _assert([])
    events = ev.append_correction(base, CIK + ":" + KEY + ":all:allforms:v1", value=" - ",
                                  recorded_at=T1, evidence=EVID_B, support=SUPPORT)
    old_id = CIK + ":" + KEY + ":all:allforms:v1"
    # Before T (at the original recording time and strictly between): original belief.
    for as_of in (T0, T_MID):
        res = _live_value(events, "2024-06-30", as_of)
        assert res.found and res.entry["value"] == " | " and res.entry["entry_id"] == old_id
    # At and after T: the replacement.
    for as_of in (T1, T_AFTER):
        res = _live_value(events, "2024-06-30", as_of)
        assert res.found and res.entry["value"] == " - "
        assert res.entry["supersedes"] == old_id
        assert res.entry["supersession_kind"] == "correction"
    # Before anything was recorded: explicit no-entry.
    assert not _live_value(events, "2024-06-30", T_BEFORE).found

    old, new = ev.materialize_entries(events)
    assert old["value"] == " | " and old["evidence"] == EVID_A  # never mutated
    assert old["recorded_at"] == T0 and old["recorded_until"] == T1
    assert new["recorded_at"] == T1 and new["recorded_until"] is None
    assert (new["valid_from"], new["valid_to"]) == (old["valid_from"], old["valid_to"])
    assert new["evidence"] == EVID_B
    validator = _entry_validator()
    validator.validate(old)
    validator.validate(new)
    ev.validate_profile(events)


def test_correction_requires_fresh_evidence():
    base = _assert([])
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    with pytest.raises(EnvelopeError, match="evidence"):
        ev.append_correction(base, old_id, value=" - ", recorded_at=T1, evidence=[],
                             support=SUPPORT)
    with pytest.raises(EnvelopeError, match="evidence"):
        ev.append_correction(base, old_id, value=" - ", recorded_at=T1,
                             evidence=copy.deepcopy(EVID_A), support=SUPPORT)


def test_correction_of_unknown_or_retracted_entry_rejected():
    base = _assert([])
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    with pytest.raises(EnvelopeError, match="unknown"):
        ev.append_correction(base, old_id + "x", value=" - ", recorded_at=T1, evidence=EVID_B,
                             support=SUPPORT)
    once = ev.append_correction(base, old_id, value=" - ", recorded_at=T1, evidence=EVID_B,
                                support=SUPPORT)
    with pytest.raises(EnvelopeError, match="already retracted"):
        ev.append_correction(once, old_id, value=" + ", recorded_at=T2, evidence=EVID_C,
                             support=SUPPORT)


# ------------------------------------------------------------- genuine change

def test_change_before_at_and_after_recording_time_and_effective_boundary():
    base = _assert([])
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    q = "2025-03-31"
    events = ev.append_change(base, old_id, effective_from=q, value=" - ", recorded_at=T1,
                              evidence=EVID_B, support=SUPPORT)
    # Before T: the original unsplit assertion, on both sides of Q.
    for as_of in (T0, T_MID):
        for report in ("2024-12-31", "2025-03-30", q, "2025-06-30"):
            res = _live_value(events, report, as_of)
            assert res.entry["entry_id"] == old_id and res.entry["value"] == " | "
            assert res.entry["valid_to"] is None
    # At and after T: split at Q. Q itself is new; dates before Q are old.
    for as_of in (T1, T_AFTER):
        at_q = _live_value(events, q, as_of)
        assert at_q.entry["value"] == " - " and at_q.entry["valid_from"] == q
        for report in ("2025-03-30", "2024-12-31", "2022-09-30"):
            before_q = _live_value(events, report, as_of)
            assert before_q.entry["value"] == " | " and before_q.entry["valid_to"] == q
            assert before_q.entry["entry_id"] != old_id
        for piece in (at_q.entry, _live_value(events, "2024-12-31", as_of).entry):
            assert piece["supersedes"] == old_id and piece["supersession_kind"] == "change"
            assert piece["recorded_at"] == T1
    # Nothing before the original valid_from, at any time.
    assert not _live_value(events, "2022-06-30", T_AFTER).found

    table = ev.materialize_entries(events)
    assert [e["recorded_until"] for e in table] == [T1, None, None]
    assert table[0]["valid_to"] is None and table[0]["value"] == " | "
    hist, new = table[1], table[2]
    assert (hist["valid_from"], hist["valid_to"]) == ("2022-09-30", q)
    assert (new["valid_from"], new["valid_to"]) == (q, None)
    assert hist["evidence"] == EVID_A and new["evidence"] == EVID_B
    for entry in table:
        _entry_validator().validate(entry)
    ev.validate_profile(events)


def test_change_preserves_finite_old_end():
    base = _assert([], valid_to="2026-03-31")
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    events = ev.append_change(base, old_id, effective_from="2024-06-30", value=" - ",
                              recorded_at=T1, evidence=EVID_B, support=SUPPORT)
    _, hist, new = ev.materialize_entries(events)
    assert (hist["valid_from"], hist["valid_to"]) == ("2022-09-30", "2024-06-30")
    assert (new["valid_from"], new["valid_to"]) == ("2024-06-30", "2026-03-31")
    assert _live_value(events, "2025-12-31", T1).entry["value"] == " - "
    assert not _live_value(events, "2026-03-31", T1).found  # half-open: end excluded
    assert not _live_value(events, "2026-03-31", T0).found
    ev.validate_profile(events)


@pytest.mark.parametrize("q", ["2022-09-30", "2021-12-31", "2026-03-31", "2027-03-31"])
def test_change_outside_old_interval_rejected(q):
    base = _assert([], valid_to="2026-03-31")
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    with pytest.raises(EnvelopeError, match="inside"):
        ev.append_change(base, old_id, effective_from=q, value=" - ", recorded_at=T1,
                         evidence=EVID_B, support=SUPPORT)


def test_change_rejects_timestamp_as_effective_date_and_same_value():
    base = _assert([])
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    with pytest.raises(EnvelopeError, match="report date"):
        ev.append_change(base, old_id, effective_from=T1, value=" - ", recorded_at=T1,
                         evidence=EVID_B, support=SUPPORT)
    with pytest.raises(EnvelopeError, match="same value"):
        ev.append_change(base, old_id, effective_from="2025-03-31", value=" | ",
                         recorded_at=T1, evidence=EVID_B, support=SUPPORT)
    with pytest.raises(EnvelopeError, match="evidence"):
        ev.append_change(base, old_id, effective_from="2025-03-31", value=" - ",
                         recorded_at=T1, evidence=[], support=SUPPORT)


def test_correction_after_change():
    base = _assert([])
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    changed = ev.append_change(base, old_id, effective_from="2025-03-31", value=" - ",
                               recorded_at=T1, evidence=EVID_B, support=SUPPORT)
    new_piece = ev.materialize_entries(changed)[2]
    events = ev.append_correction(changed, new_piece["entry_id"], value=" -- ",
                                  recorded_at=T2, evidence=EVID_C, support=SUPPORT)
    # Before T1: original; between T1 and T2: the change; at/after T2: corrected new piece.
    assert _live_value(events, "2025-06-30", T_MID).entry["value"] == " | "
    assert _live_value(events, "2025-06-30", T_MID2).entry["value"] == " - "
    for as_of in (T2, T_AFTER):
        res = _live_value(events, "2025-06-30", as_of)
        assert res.entry["value"] == " -- " and res.entry["supersedes"] == new_piece["entry_id"]
        assert res.entry["supersession_kind"] == "correction"
        assert (res.entry["valid_from"], res.entry["valid_to"]) == ("2025-03-31", None)
        # The historical piece is untouched by the correction.
        hist = _live_value(events, "2024-12-31", as_of).entry
        assert hist["value"] == " | " and hist["recorded_until"] is None
    table = ev.materialize_entries(events)
    assert len(table) == 4 and table[2]["recorded_until"] == T2
    assert ev.validate_profile(events)["slices"] == 3


# ------------------------------------------------ log integrity and immutability

def test_duplicate_entry_ids_rejected():
    events = _assert([])
    dup = copy.deepcopy(events[0])
    dup["recorded_at"] = T1
    dup["entry"]["recorded_at"] = T1
    with pytest.raises(EnvelopeError, match="duplicate"):
        ev.validate_profile(events + [dup])
    with pytest.raises(EnvelopeError, match="duplicate"):
        ev.materialize_entries(events + [dup])


def test_reordered_events_rejected():
    base = _assert([])
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    events = ev.append_correction(base, old_id, value=" - ", recorded_at=T1, evidence=EVID_B,
                                  support=SUPPORT)
    reordered = [events[1], events[2], events[0]]
    with pytest.raises(EnvelopeError, match="non-decreasing"):
        ev.validate_profile(reordered)
    with pytest.raises(EnvelopeError):
        ev.materialize_entries([events[0], events[2], events[1]])  # replacement before retraction
    with pytest.raises(EnvelopeError, match="non-decreasing"):
        _assert(events, recorded_at=T0)  # appending in the past


def test_invalid_retraction_references_and_nonmonotonic_bounds_rejected():
    events = _assert([])
    old_id = ev.materialize_entries(events)[0]["entry_id"]
    with pytest.raises(EnvelopeError, match="unknown"):
        ev.validate_profile(events + [_retraction("no-such-entry", T1)])
    with pytest.raises(EnvelopeError, match="already retracted"):
        ev.validate_profile(events + [_retraction(old_id, T1),
                                      dict(_retraction(old_id, T2), event_id="retract:again")])
    with pytest.raises(EnvelopeError, match="recorded_until"):
        ev.validate_profile(events + [_retraction(old_id, T0)])
    with pytest.raises(EnvelopeError, match="recorded_until"):
        ev.append_correction(events, old_id, value=" - ", recorded_at=T0, evidence=EVID_B,
                             support=SUPPORT)


def test_supersedes_must_reference_an_entry_retracted_at_the_same_time():
    events = _assert([])
    forged = copy.deepcopy(_assert([], valid_from="2023-03-31", recorded_at=T1)[0])
    forged["entry"]["supersedes"] = events[0]["entry_id"]
    forged["entry"]["supersession_kind"] = "correction"
    forged["entry"]["entry_id"] = forged["entry_id"] = CIK + ":" + KEY + ":all:allforms:v2"
    forged["event_id"] = "assert:" + forged["entry_id"]
    with pytest.raises(EnvelopeError, match="supersedes"):
        ev.validate_profile(events + [forged])


def test_inputs_are_never_mutated():
    evidence = copy.deepcopy(EVID_A)
    support = copy.deepcopy(SUPPORT)
    applies = copy.deepcopy(PREFIX_LIEN)
    snap_args = copy.deepcopy((evidence, support, applies))
    e1 = ev.make_assertion([], cik=CIK, key=KEY, value=" | ", valid_from="2022-09-30",
                           recorded_at=T0, support=support, evidence=evidence,
                           applies_to=applies)
    assert (evidence, support, applies) == snap_args
    snap = copy.deepcopy(e1)
    pid = ev.materialize_entries(e1)[0]["entry_id"]
    e2 = ev.append_change(e1, pid, effective_from="2025-03-31", value=" - ", recorded_at=T1,
                          evidence=EVID_B, support=SUPPORT)
    assert e1 == snap
    snap2 = copy.deepcopy(e2)
    e3 = ev.append_correction(e2, ev.materialize_entries(e2)[2]["entry_id"], value=" -- ",
                              recorded_at=T2, evidence=EVID_C, support=SUPPORT)
    assert e2 == snap2
    snap3 = copy.deepcopy(e3)
    entries = ev.materialize_entries(e3)
    ev.validate_profile(e3, sample_rows=[ROW_LIEN, ROW_OTHER])
    snap_entries = copy.deepcopy(entries)
    row = copy.deepcopy(ROW_LIEN)
    ev.resolve_for_row(entries, row, KEY, "2025-06-30", "10-K", T_AFTER)
    assert e3 == snap3 and entries == snap_entries and row == ROW_LIEN
    # Returned structures do not alias the log.
    entries[0]["evidence"][0]["ids"].append("c-999")
    entries[0]["value"] = "mutated"
    assert ev.materialize_entries(e3)[0]["evidence"] == EVID_A
    assert e3 == snap3
    assert EVID_A[0]["ids"] == ["c-12", "c-13"]


def test_materialize_as_of_hides_later_events():
    base = _assert([])
    old_id = ev.materialize_entries(base)[0]["entry_id"]
    events = ev.append_correction(base, old_id, value=" - ", recorded_at=T1, evidence=EVID_B,
                                  support=SUPPORT)
    known_then = ev.materialize_entries(events, as_of=T_MID)
    assert len(known_then) == 1 and known_then[0]["recorded_until"] is None
    assert len(ev.materialize_entries(events, as_of=T1)) == 2
    assert ev.materialize_entries(events, as_of=T_BEFORE) == []


# ---------------------------------------------------------- applicability

def _two_partitions():
    events = _assert([], applies_to=PREFIX_LIEN, value=" | ")
    return _assert(events, applies_to=AXIS_EQUITY, value=" - ")


def test_two_disjoint_mixed_format_partitions_resolve_per_row():
    events = _two_partitions()
    entries = ev.materialize_entries(events)
    lien = ev.resolve_for_row(entries, ROW_LIEN, KEY, "2024-06-30", "10-K", T1)
    equity = ev.resolve_for_row(entries, ROW_EQUITY, KEY, "2024-06-30", "10-K", T1)
    assert lien.entry["value"] == " | " and lien.entry["applies_to"] == PREFIX_LIEN
    assert equity.entry["value"] == " - " and equity.entry["applies_to"] == AXIS_EQUITY
    # A row neither partition selects, with no fallback: explicit no-entry, not None.
    other = ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-06-30", "10-K", T1)
    assert other is not None and other.found is False and other.entry is None
    assert other.status == "no_entry"
    ev.validate_profile(events, sample_rows=[ROW_LIEN, ROW_EQUITY, ROW_OTHER])


def test_null_partition_is_explicit_fallback_not_a_conflict():
    events = _two_partitions()
    events = _assert(events, value=" / ")
    entries = ev.materialize_entries(events)
    assert ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-06-30", "10-Q", T1).entry[
        "value"] == " / "
    assert ev.resolve_for_row(entries, ROW_LIEN, KEY, "2024-06-30", "10-Q", T1).entry[
        "value"] == " | "
    ev.validate_profile(events, sample_rows=[ROW_LIEN, ROW_EQUITY, ROW_OTHER])


def test_form_specific_precedence_over_all_forms_and_partition_over_form():
    events = _assert([], value=" / ")
    events = _assert(events, form_type="10-K", value=" |10K| ")
    entries = ev.materialize_entries(events)
    assert ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-06-30", "10-K", T1).entry[
        "value"] == " |10K| "
    assert ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-06-30", "10-Q", T1).entry[
        "value"] == " / "
    # Partition tier beats form tier: an all-form partition entry outranks a
    # form-specific null-partition entry.
    events = _assert(events, applies_to=PREFIX_LIEN, value=" p ")
    entries = ev.materialize_entries(events)
    assert ev.resolve_for_row(entries, ROW_LIEN, KEY, "2024-06-30", "10-K", T1).entry[
        "value"] == " p "
    # Within the partition tier, exact form still beats all-form.
    events = _assert(events, applies_to=PREFIX_LIEN, form_type="10-K", value=" pk ")
    entries = ev.materialize_entries(events)
    assert ev.resolve_for_row(entries, ROW_LIEN, KEY, "2024-06-30", "10-K", T1).entry[
        "value"] == " pk "
    assert ev.resolve_for_row(entries, ROW_LIEN, KEY, "2024-06-30", "10-Q", T1).entry[
        "value"] == " p "
    ev.validate_profile(events, sample_rows=[ROW_LIEN, ROW_OTHER])


def test_overlapping_prefix_and_axis_selectors_selecting_same_row_are_ambiguous():
    events = _two_partitions()
    entries = ev.materialize_entries(events)
    with pytest.raises(AmbiguousResolutionError):
        ev.resolve_for_row(entries, ROW_BOTH, KEY, "2024-06-30", "10-K", T1)
    # Validation finds it by evaluating the predicates, not by JSON equality.
    with pytest.raises(OverlapError, match="both"):
        ev.validate_profile(events, sample_rows=[ROW_LIEN, ROW_EQUITY, ROW_BOTH])
    # The same rows carried as evidence are used when no sample is supplied.
    evidence_rows = [{"kind": "sample_rows", "rows": [ROW_BOTH]}]
    with_evidence = _assert(events, value=" ? ", valid_from="2010-12-31",
                            valid_to="2011-12-31", evidence=evidence_rows)
    with pytest.raises(OverlapError):
        ev.validate_profile(with_evidence)


def test_different_prefix_vocabularies_selecting_same_row_are_ambiguous():
    events = _assert([], applies_to={"kind": "prefix", "vocabulary": ["First Lien"]})
    events = _assert(events, applies_to={"kind": "prefix",
                                         "vocabulary": ["Unitranche", "First Lien |"]},
                     value=" - ")
    entries = ev.materialize_entries(events)
    with pytest.raises(AmbiguousResolutionError):
        ev.resolve_for_row(entries, ROW_LIEN, KEY, "2024-06-30", "10-K", T1)
    with pytest.raises(OverlapError):
        ev.validate_profile(events, sample_rows=[ROW_OTHER, ROW_LIEN])
    # A sample that never exercises the overlap passes: the check is evidence-bound.
    ev.validate_profile(events, sample_rows=[ROW_OTHER, ROW_EQUITY])


def test_distinct_partitions_without_any_sample_rows_are_unproven():
    with pytest.raises(OverlapError, match="unprovab"):
        ev.validate_profile(_two_partitions())


def test_equally_specific_null_partition_entries_are_ambiguous():
    events = _assert([], value=" | ")
    events = _assert(events, value=" - ", valid_from="2024-03-31")
    entries = ev.materialize_entries(events)
    assert ev.resolve_for_row(entries, ROW_OTHER, KEY, "2023-06-30", "10-K", T1).entry[
        "value"] == " | "
    with pytest.raises(AmbiguousResolutionError):
        ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-06-30", "10-K", T1)
    with pytest.raises(OverlapError):
        ev.validate_profile(events)
    # Abutting half-open intervals do not overlap.
    ok = _assert([], value=" | ", valid_to="2024-03-31")
    ok = _assert(ok, value=" - ", valid_from="2024-03-31")
    ev.validate_profile(ok)


def test_historical_slice_overlap_is_caught_even_when_current_state_is_clean():
    events = _assert([], value=" | ")
    events = _assert(events, value=" - ", valid_from="2024-03-31")
    bad_id = ev.materialize_entries(events)[1]["entry_id"]
    events = events + [_retraction(bad_id, T1)]
    entries = ev.materialize_entries(events)
    # Current state is clean ...
    assert ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-06-30", "10-K", T_AFTER).entry[
        "value"] == " | "
    # ... but the slice recorded at T0 had two live overlapping entries.
    with pytest.raises(OverlapError, match=T0):
        ev.validate_profile(events)


def test_unknown_predicate_kind_raises_everywhere():
    with pytest.raises(UnknownPredicateError):
        _assert([], applies_to={"kind": "regex", "pattern": ".*"})
    events = _assert([], applies_to=PREFIX_LIEN)
    injected = copy.deepcopy(events)
    injected[0]["entry"]["applies_to"] = {"kind": "regex", "pattern": ".*"}
    with pytest.raises(UnknownPredicateError):
        ev.validate_profile(injected)
    entries = ev.materialize_entries(events)
    entries[0]["applies_to"] = {"kind": "regex", "pattern": ".*"}
    with pytest.raises(UnknownPredicateError):
        ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-06-30", "10-K", T1)


@pytest.mark.parametrize("predicate", [
    {"kind": "row_ordinal", "ordinals": [3, 4, 5]},
    {"kind": "row_range", "start": 10, "end": 40},
    {"kind": "context_ids", "ids": ["c-1", "c-2"]},
    {"kind": "prefix", "vocabulary": ["First Lien"], "rows": [1, 2]},
])
def test_row_ordinal_and_context_list_predicates_rejected(predicate):
    with pytest.raises(ForbiddenPredicateError):
        _assert([], applies_to=predicate)
    events = _assert([], applies_to=PREFIX_LIEN)
    injected = copy.deepcopy(events)
    injected[0]["entry"]["applies_to"] = predicate
    with pytest.raises(ForbiddenPredicateError):
        ev.validate_profile(injected, sample_rows=[ROW_LIEN])


def test_structural_predicate_vocabulary_evaluates_against_raw_rows():
    match = ev.predicate_matches
    assert match(AXIS_EQUITY, ROW_EQUITY) and not match(AXIS_EQUITY, ROW_LIEN)
    qname_row = {"dimensions": [["us-gaap:InvestmentTypeAxis", "us-gaap:EquitySecuritiesMember"]]}
    assert match(AXIS_EQUITY, qname_row)
    other_prefix = {"dimensions": [["us-gaap:InvestmentTypeAxis", "abc:EquitySecuritiesMember"]]}
    assert not match(AXIS_EQUITY, other_prefix)
    concept = {"kind": "carrying_concept", "field": "interest_rate",
               "concept": "us-gaap:InvestmentInterestRate"}
    assert match(concept, ROW_LIEN) and not match(concept, ROW_EQUITY)
    three = {"kind": "segment_count", "delimiter": " | ", "count": 3}
    assert match(three, ROW_LIEN) and not match(three, ROW_OTHER)
    assert not match(three, {"investment_identifier": ""})
    dialect = {"kind": "grammar_dialect", "dialect": "pipe3"}
    assert match(dialect, {"grammar_dialect": "pipe3"})
    assert not match(dialect, {"grammar_dialect": "dash2"})
    assert match(PREFIX_LIEN, ROW_LIEN) and not match(PREFIX_LIEN, ROW_OTHER)
    # A row that lacks the field a predicate needs cannot be silently unmatched.
    with pytest.raises(PredicateEvaluationError):
        match(dialect, ROW_LIEN)
    with pytest.raises(PredicateEvaluationError):
        match(PREFIX_LIEN, {"dimensions_raw": ""})
    with pytest.raises(InvalidPredicateError):
        ev.check_predicate({"kind": "segment_count", "delimiter": " | ", "count": 0})


@pytest.mark.parametrize("predicate, row", [
    ({"kind": "grammar_dialect", "dialect": "pipe3"}, {"grammar_dialect": None}),
    ({"kind": "grammar_dialect", "dialect": "pipe3"}, {"grammar_dialect": float("nan")}),
    (PREFIX_LIEN, {"investment_identifier": None}),
    ({"kind": "segment_count", "delimiter": " | ", "count": 3}, {"investment_identifier": None}),
    ({"kind": "carrying_concept", "field": "interest_rate",
      "concept": "us-gaap:InvestmentInterestRate"}, {"interest_rate_concept": None}),
    (AXIS_EQUITY, {"dimensions_raw": None}),
    (AXIS_EQUITY, {"dimensions": None}),
])
def test_null_predicate_field_is_unresolved_not_a_silent_non_match(predicate, row):
    with pytest.raises(PredicateEvaluationError, match="null"):
        ev.predicate_matches(predicate, row)


def test_null_dialect_never_falls_back_to_the_null_partition():
    dialect = {"kind": "grammar_dialect", "dialect": "pipe3"}
    events = _assert([], applies_to=dialect, value=" | ")
    events = _assert(events, value=" / ")  # the null-partition fallback
    entries = ev.materialize_entries(events)
    assert ev.resolve_for_row(entries, {"grammar_dialect": "dash2"}, KEY, "2024-06-30", "10-K",
                              T1).entry["value"] == " / "
    with pytest.raises(PredicateEvaluationError):
        ev.resolve_for_row(entries, {"grammar_dialect": None}, KEY, "2024-06-30", "10-K", T1)


def test_overlap_validation_scopes_rows_to_the_key_under_check():
    dialect_a = {"kind": "grammar_dialect", "dialect": "pipe3"}
    dialect_b = {"kind": "grammar_dialect", "dialect": "dash2"}
    other_key = "rate_convention.scale"
    events = _assert([], applies_to=dialect_a, value=" | ")
    events = _assert(events, applies_to=dialect_b, value=" - ",
                     evidence=[{"kind": "sample_rows", "rows": [{"grammar_dialect": "dash2"}]}])
    # An unrelated key whose evidence row has no grammar_dialect at all.
    events = _assert(events, key=other_key, value="percent",
                     evidence=[{"kind": "sample_rows", "rows": [ROW_LIEN]}])
    ev.validate_profile(events)
    # Per-key caller rows are scoped the same way; rows for another key are not evaluated.
    ev.validate_profile(events, sample_rows={KEY: [{"grammar_dialect": "pipe3"}],
                                             other_key: [ROW_OTHER]})
    # Rows for the key under check that lack the field still fail loudly.
    with pytest.raises(PredicateEvaluationError):
        ev.validate_profile(events, sample_rows={KEY: [ROW_LIEN]})
    with pytest.raises(EnvelopeError, match="does not have"):
        ev.validate_profile(events, sample_rows={"no.such_key": [ROW_LIEN]})
    # And a same-key row selected by both partitions is still an overlap.
    both = _assert(events, applies_to={"kind": "prefix", "vocabulary": ["First Lien"]},
                   value=" p ")
    with pytest.raises(OverlapError):
        ev.validate_profile(both, sample_rows={KEY: [dict(ROW_LIEN, grammar_dialect="pipe3")]})


def test_resolve_filters_both_clocks_and_rejects_mixed_clock_arguments():
    events = _assert([], valid_to="2024-03-31")
    entries = ev.materialize_entries(events)
    assert ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-03-30", "10-K", T0).found
    assert not ev.resolve_for_row(entries, ROW_OTHER, KEY, "2024-03-31", "10-K", T0).found
    assert not ev.resolve_for_row(entries, ROW_OTHER, KEY, "2022-06-30", "10-K", T0).found
    assert not ev.resolve_for_row(entries, ROW_OTHER, KEY, "2023-06-30", "10-K",
                                  T_BEFORE).found
    assert not ev.resolve_for_row(entries, ROW_OTHER, "other.key", "2023-06-30", "10-K",
                                  T0).found
    with pytest.raises(EnvelopeError, match="report date"):
        ev.resolve_for_row(entries, ROW_OTHER, KEY, T0, "10-K", T0)
    with pytest.raises(EnvelopeError, match="timestamp"):
        ev.resolve_for_row(entries, ROW_OTHER, KEY, "2023-06-30", "10-K", "2023-06-30")
