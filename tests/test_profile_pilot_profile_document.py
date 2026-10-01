"""SP3 proper Task 3: filer profile document v1 (schema, admission states, resolver). Pure synthetic tests."""
from __future__ import annotations

import copy
import json

import pytest

from scripts.profile_pilot import envelope
from scripts.profile_pilot import profile_document as pd

CIK = "0001901037"
NOW = "2026-10-01T12:00:00Z"
LATER = "2026-10-02T12:00:00Z"
RUN = "sp3p-profile-test"
FILE = "rate_convention/" + CIK + ".json"
Q4 = "2025-12-31"


def inherited_events(events=(), key="meaning.interest_rate", value=None, sha="b" * 64):
    path = "data/overrides/" + FILE
    return envelope.make_assertion(
        list(events), cik=CIK, key=key, value=value or {"convention": "all_in"}, valid_from=None, recorded_at=NOW,
        support={"kind": "inherited_file", "path": path, "sha256": sha},
        evidence=[{"kind": "override_file", "path": path, "sha256": sha, "value_is_file": True}],
        provenance="inherited", inherited_from=path + "@" + sha[:12], author="agent", status="promoted")


def adm(state="accepted"):
    return pd.admission(state, "inherited_production", source_kind="override_file",
                        mechanism="rate_convention override file", confidence=0.9, source_author="agent",
                        recorded_at=NOW, run_id=RUN, source="data/overrides/" + FILE,
                        inception_evaluation="none_available")


def one_off(report_date=Q4, **over):
    c = dict(correction_id=CIK + ":corr:b2:001", kind="one_off", family="agent_b2_corrections",
             mechanism="extraction_gap", fix_class="all_pik_normalization", report_date=report_date,
             valid_from=report_date, valid_to=report_date, report_dates=[report_date], target={"row_id": "ROW-1"},
             row_keyed=True, value={"cik": CIK},
             source=dict(path="agent_b2_corrections/" + CIK + "/all_pik_normalization.json", sha256="c" * 64,
                         record_index=None),
             pre_image=dict(status="unchecked", reason="criterion 5 runs in sub-project 6"),
             recurrence_group=None, promotion=None, state="accepted", admission_basis="inherited_production",
             confidence=0.9, provenance=dict(who=pd.CONVERTER_VERSION, source_author="agent", when=NOW, run_id=RUN,
                                             source="data/overrides/agent_b2_corrections"),
             recorded_at=NOW, recorded_until=None, supersedes=None)
    c.update(over)
    return c


def minimal_document(*, state="accepted", stub_all=True):
    events = inherited_events()
    entries = envelope.materialize_entries(events)
    eid = entries[0]["entry_id"]
    stubs = []
    if stub_all:
        for key in pd.GRID_KEYS:
            if key == "meaning.interest_rate":
                if state == "candidate":
                    stubs.append(pd.stub(CIK, key, "candidate_pending_confirmation", "owner sign-off of " + eid,
                                         entry_id=eid))
                continue
            stubs.append(pd.stub(CIK, key, "no_source", "a filing citation for " + key))
    return dict(schema=pd.SCHEMA_NAME, schema_version=1, document_version=1, cik=CIK,
                inception_report_date=pd.INCEPTION_REPORT_DATE, recorded_at=NOW, run_id=RUN,
                code=dict(git_head="2a218e9", converter_version=pd.CONVERTER_VERSION),
                events=events, entries=entries, admissions={eid: adm(state)}, stubs=stubs,
                wrapper_section=dict(blocks=[]), corrections=[],
                partition_predicate=dict(census_published_version="census-published.v2",
                                         published_basis_entry_id=None, reporting_entities_entry_id=None,
                                         code_mirror=dict(path="scripts/profile_pilot/census_published.py",
                                                          constant="REPORTING_ENTITIES", value=[])),
                detection_claims={}, disposition=[],
                ledger=[dict(event="document_created", at=NOW, run_id=RUN, detail={})])


def bounded_events(valid_from="2025-12-31", valid_to="2026-03-31", key="scale_unit.fair_value", value=None):
    return envelope.make_assertion(list(), cik=CIK, key=key, value=value or {"unit": "USD"}, valid_from=valid_from,
                                   valid_to=valid_to, recorded_at=NOW,
                                   support={"kind": "context_count", "count": 1},
                                   evidence=[{"kind": "owner_ruling", "ref": "R1"}])


def _bounded_doc(valid_from, valid_to, key="scale_unit.fair_value"):
    events = bounded_events(valid_from, valid_to, key)
    entries = envelope.materialize_entries(events)
    eid = entries[0]["entry_id"]
    return dict(minimal_document(stub_all=False), events=events, entries=entries, admissions={eid: adm()},
                stubs=[])


def block(block_id, *, supersedes=None):
    return dict(block_id=block_id, family="bdc_xbrl_wrapper", version=1, content={}, content_sha256="d" * 64,
                source_files=[dict(path="x.json", sha256="e" * 64, ordered_sha256="e" * 64)],
                valid_from=None, valid_to=None, recorded_at=NOW, recorded_until=None, supersedes=supersedes,
                supersession_kind=("correction" if supersedes else None),
                attested_under=[], evidence=[{"kind": "override_file"}], expressibility=None)


def _with_extra_admission(d):
    d["admissions"] = dict(d["admissions"], **{"9999999999:bogus:key:all:allforms:v1": adm()})


def _with_foreign_entry(d):
    events = envelope.make_assertion(d["events"], cik="0000000002", key="meaning.pik_rate",
                                     value={"convention": "cash"}, valid_from=None, recorded_at=NOW,
                                     support={"kind": "context_count", "count": 1},
                                     evidence=[{"kind": "owner_ruling", "ref": "R1"}])
    entries = envelope.materialize_entries(events)
    new_eid = next(e["entry_id"] for e in entries if e["entry_id"] not in d["admissions"])
    d.update(events=events, entries=entries, admissions=dict(d["admissions"], **{new_eid: adm()}))


def _with_overlapping_entry(d):
    events = inherited_events(d["events"], value={"convention": "cash"})
    entries = envelope.materialize_entries(events)
    new_eid = next(e["entry_id"] for e in entries if e["entry_id"] not in d["admissions"])
    d.update(events=events, entries=entries, admissions=dict(d["admissions"], **{new_eid: adm()}))


def _with_stub_key_outside_grid(d):
    d["stubs"].append(dict(stub_id=CIK + ":stub:not_a_grid.key", key="not_a_grid.key", cause="no_source",
                           closing_evidence="x", entry_id=None, detail={}))


def _with_stub_naming_unknown_entry(d):
    d["stubs"].append(pd.stub(CIK, "meaning.interest_rate", "no_source", "x", entry_id="bogus:entry:id"))


def _with_stub_wrong_key(d):
    eid = d["entries"][0]["entry_id"]
    d["stubs"] = [s for s in d["stubs"] if s["key"] != "scale_unit.fair_value"]
    d["stubs"].append(pd.stub(CIK, "scale_unit.fair_value", "no_source", "x", entry_id=eid))


def _with_stub_naming_accepted_entry(d):
    eid = d["entries"][0]["entry_id"]
    d["stubs"].append(pd.stub(CIK, "meaning.interest_rate", "no_source", "x", entry_id=eid))


def _with_stub_wrong_cik(d):
    d["stubs"] = [s for s in d["stubs"] if s["key"] != "scale_unit.cost"]
    d["stubs"].append(dict(stub_id="0000000000:stub:scale_unit.cost", key="scale_unit.cost", cause="no_source",
                           closing_evidence="x", entry_id=None, detail={}))


def _with_duplicate_block_ids(d):
    d["wrapper_section"]["blocks"] = [block("blk:1"), block("blk:1")]


def _with_block_superseding_unknown_block(d):
    d["wrapper_section"]["blocks"] = [block("blk:2", supersedes="blk:missing")]


def _with_correction_superseding_unknown_correction(d):
    d.update(corrections=[one_off(supersedes="corr:missing")])


def test_grid_shape():
    assert len(pd.FIELD_KEYS) == 39 and len(pd.FILER_KEYS) == 17 and len(pd.GRID_KEYS) == 56
    assert len(set(pd.GRID_KEYS)) == 56
    assert {k.split(".", 1)[0] for k in pd.GRID_KEYS} <= set(pd.AXIS_OF_SECTION)


def test_schema_enums_match_the_module_constants():
    schema = json.loads((pd.SCHEMA_DIR / pd.SCHEMA_FILE).read_text(encoding="ascii"))
    d = schema["$defs"]
    assert tuple(d["admission"]["properties"]["state"]["enum"]) == pd.ADMISSION_STATES
    assert tuple(d["admission"]["properties"]["basis"]["enum"]) == pd.ADMISSION_BASES
    assert tuple(d["admission"]["properties"]["source_kind"]["enum"]) == pd.SOURCE_KINDS
    assert tuple(d["stub"]["properties"]["cause"]["enum"]) == pd.STUB_CAUSES
    assert tuple(d["correction"]["properties"]["state"]["enum"]) == pd.LIFECYCLE_STATES


def test_minimal_document_validates_and_resolves():
    doc = minimal_document()
    pd.validate_document(doc)
    hit = pd.resolve(doc, "meaning.interest_rate", Q4)
    assert hit["status"] == "resolved" and hit["entry"]["value"] == {"convention": "all_in"}
    miss = pd.resolve(doc, "scale_unit.fair_value", Q4)
    assert miss["status"] == "stub" and miss["stub"]["cause"] == "no_source"
    bare = minimal_document(stub_all=False)
    pd.validate_document(bare)
    assert pd.resolve(bare, "scale_unit.fair_value", Q4) == {"status": "no_entry"}


def test_candidates_are_invisible_to_resolve():
    doc = minimal_document(state="candidate")
    pd.validate_document(doc)
    eid = doc["entries"][0]["entry_id"]
    out = pd.resolve(doc, "meaning.interest_rate", Q4)
    assert out["status"] == "stub" and out["stub"]["entry_id"] == eid
    assert pd.entry_state(doc, eid) == "candidate"
    cov = pd.coverage(doc, Q4)["meaning.interest_rate"]
    assert cov["entry_ids"] == [eid] and cov["accepted_entry_ids"] == []


def test_entry_state_superseded_and_retracted():
    doc = minimal_document()
    eid = doc["entries"][0]["entry_id"]
    events = envelope.append_correction(doc["events"], eid, value={"convention": "cash"}, recorded_at=LATER,
                                        evidence=[{"kind": "owner_ruling", "ref": "R99"}],
                                        support={"kind": "context_count", "count": 1})
    corrected = dict(doc, events=events, entries=envelope.materialize_entries(events))
    new = [e["entry_id"] for e in corrected["entries"] if e["entry_id"] != eid][0]
    corrected["admissions"] = dict(doc["admissions"], **{new: adm()})
    pd.validate_document(corrected)
    assert pd.entry_state(corrected, eid) == "superseded" and pd.entry_state(corrected, new) == "accepted"
    retract = doc["events"] + [{"event": "retract", "event_id": "retract:" + eid, "entry_id": eid,
                                "recorded_at": LATER}]
    gone = dict(doc, events=retract, entries=envelope.materialize_entries(retract))
    pd.validate_document(gone)
    assert pd.entry_state(gone, eid) == "retracted"


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(admissions={}), "admissions"),
    (lambda d: d["stubs"].append(dict(d["stubs"][0])), "one stub per key"),
    (lambda d: d["stubs"].append(pd.stub(CIK, "meaning.interest_rate", "no_source", "x")), "accepted entry"),
    (lambda d: d.update(entries=[]), "materialized view"),
    (lambda d: d.update(corrections=[one_off(valid_to="2026-03-31")]), "one_off"),
    (lambda d: d.update(corrections=[one_off(), one_off()]), "correction ids"),
    (lambda d: d.update(schema="filer_profile_document_v0"), "schema"),
    (_with_extra_admission, "admissions"),
    (_with_foreign_entry, "another filer"),
    (_with_stub_key_outside_grid, "outside the grid"),
    (_with_stub_naming_unknown_entry, "unknown entry"),
    (_with_stub_wrong_key, "different key"),
    (_with_stub_naming_accepted_entry, "accepted entry"),
    (_with_stub_wrong_cik, "stub_id must carry"),
    (_with_duplicate_block_ids, "block ids"),
    (_with_block_superseding_unknown_block, "unknown block"),
    (_with_overlapping_entry, "overlap"),
    (lambda d: d.update(corrections=[one_off(report_date=None, kind="multi_quarter", valid_from=None,
                                             valid_to=None, report_dates=[Q4])]), "multi_quarter"),
    (lambda d: d.update(corrections=[one_off(report_date=None, kind="undated", valid_from=None, valid_to=None,
                                             report_dates=[Q4])]), "undated"),
    (lambda d: d.update(corrections=[one_off(target={})]), "row_id"),
    (_with_correction_superseding_unknown_correction, "unknown correction"),
    (lambda d: d.update(partition_predicate=dict(d["partition_predicate"], published_basis_entry_id="bogus:id")),
     "published_basis_entry_id"),
    (lambda d: d.update(partition_predicate=dict(d["partition_predicate"], reporting_entities_entry_id="bogus:id")),
     "reporting_entities_entry_id"),
])
def test_validate_rejects(mutate, message):
    doc = copy.deepcopy(minimal_document())
    mutate(doc)
    with pytest.raises(pd.ProfileDocumentError, match=message):
        pd.validate_document(doc)


def test_unknown_stub_key_is_refused_at_construction():
    with pytest.raises(pd.ProfileDocumentError):
        pd.stub(CIK, "not_a_grid.key", "no_source", "x")


def test_equally_specific_accepted_entries_raise_ambiguity():
    events = inherited_events(inherited_events(), value={"convention": "cash"})
    entries = envelope.materialize_entries(events)
    doc = dict(minimal_document(), events=events, entries=entries,
               admissions={e["entry_id"]: adm() for e in entries})
    with pytest.raises(pd.ProfileAmbiguityError):
        pd.resolve(doc, "meaning.interest_rate", Q4)


def test_load_document_round_trips(tmp_path):
    doc = minimal_document()
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    assert pd.load_document(path) == doc


# ---- Fix round 1 ----

def test_valid_at_boundaries():
    bounded = dict(valid_from="2025-12-31", valid_to="2026-03-31")
    assert pd.valid_at(bounded, "2025-12-31") is True
    assert pd.valid_at(bounded, "2026-03-31") is False
    assert pd.valid_at(bounded, "2025-12-30") is False
    unbounded = dict(valid_from=None, valid_to=None)
    assert pd.valid_at(unbounded, "1900-01-01") is True
    assert pd.valid_at(unbounded, "2999-01-01") is True


def test_coverage_and_resolve_respect_the_half_open_valid_interval():
    doc = _bounded_doc("2025-12-31", "2026-03-31")
    eid = doc["entries"][0]["entry_id"]
    assert pd.resolve(doc, "scale_unit.fair_value", "2025-12-31")["status"] == "resolved"
    assert pd.resolve(doc, "scale_unit.fair_value", "2026-03-31") == {"status": "no_entry"}
    assert pd.resolve(doc, "scale_unit.fair_value", "2025-12-30") == {"status": "no_entry"}
    cov_in = pd.coverage(doc, "2025-12-31")["scale_unit.fair_value"]
    assert cov_in["entry_ids"] == [eid] and cov_in["accepted_entry_ids"] == [eid]
    cov_out_hi = pd.coverage(doc, "2026-03-31")["scale_unit.fair_value"]
    assert cov_out_hi["entry_ids"] == [] and cov_out_hi["accepted_entry_ids"] == []
    cov_out_lo = pd.coverage(doc, "2025-12-30")["scale_unit.fair_value"]
    assert cov_out_lo["entry_ids"] == [] and cov_out_lo["accepted_entry_ids"] == []


def test_valid_at_null_bounds_are_unbounded_in_resolve():
    doc = minimal_document()
    assert pd.resolve(doc, "meaning.interest_rate", "1900-01-01")["status"] == "resolved"
    assert pd.resolve(doc, "meaning.interest_rate", "2999-01-01")["status"] == "resolved"


def test_resolve_as_of_before_and_after_a_retraction():
    doc = minimal_document()
    eid = doc["entries"][0]["entry_id"]
    events = doc["events"] + [{"event": "retract", "event_id": "retract:" + eid, "entry_id": eid,
                               "recorded_at": LATER}]
    doc = dict(doc, events=events)
    assert pd.resolve(doc, "meaning.interest_rate", Q4, as_of=NOW)["status"] == "resolved"
    assert pd.resolve(doc, "meaning.interest_rate", Q4, as_of=LATER) == {"status": "no_entry"}


def test_resolve_rejects_predicate_evaluation_error_as_profile_document_error():
    events = envelope.make_assertion(list(), cik=CIK, key="meaning.pik_rate", value={"convention": "cash"},
                                     valid_from=None, recorded_at=NOW,
                                     support={"kind": "context_count", "count": 1},
                                     evidence=[{"kind": "owner_ruling", "ref": "R1"}],
                                     applies_to={"kind": "grammar_dialect", "dialect": "x"})
    entries = envelope.materialize_entries(events)
    eid = entries[0]["entry_id"]
    doc = dict(minimal_document(stub_all=False), events=events, entries=entries, admissions={eid: adm()}, stubs=[])
    with pytest.raises(pd.ProfileDocumentError, match="grammar_dialect"):
        pd.resolve(doc, "meaning.pik_rate", Q4)


def test_resolve_rejects_bad_report_date():
    doc = minimal_document()
    with pytest.raises(pd.ProfileDocumentError, match="report_date"):
        pd.resolve(doc, "meaning.interest_rate", "not-a-date")


def test_resolve_rejects_unknown_off_grid_key():
    doc = minimal_document()
    with pytest.raises(pd.ProfileDocumentError, match="not on the grid"):
        pd.resolve(doc, "not_a_grid.key", Q4)


def test_resolve_allows_off_grid_key_carried_by_an_entry():
    events = envelope.make_assertion(list(), cik=CIK, key="wrapper_only.custom_axis", value={"x": 1},
                                     valid_from=None, recorded_at=NOW,
                                     support={"kind": "context_count", "count": 1},
                                     evidence=[{"kind": "owner_ruling", "ref": "R1"}])
    entries = envelope.materialize_entries(events)
    eid = entries[0]["entry_id"]
    doc = dict(minimal_document(stub_all=False), events=events, entries=entries, admissions={eid: adm()}, stubs=[])
    out = pd.resolve(doc, "wrapper_only.custom_axis", Q4)
    assert out["status"] == "resolved"


def test_admission_stores_non_numeric_confidence_in_witness_raw():
    a = pd.admission("accepted", "inherited_production", source_kind="override_file", mechanism="m",
                     confidence="high", source_author="agent", recorded_at=NOW, run_id=RUN, source="s",
                     inception_evaluation="none_available")
    assert a["confidence"] is None and a["witness"]["confidence_raw"] == "high"


def test_admission_stores_prose_confidence_in_witness_raw():
    prose = "fairly confident given the override file's internal consistency"
    a = pd.admission("accepted", "inherited_production", source_kind="override_file", mechanism="m",
                     confidence=prose, source_author="agent", recorded_at=NOW, run_id=RUN, source="s",
                     inception_evaluation="none_available")
    assert a["confidence"] is None and a["witness"]["confidence_raw"] == prose


def test_admission_numeric_confidence_is_unaffected():
    a = adm()
    assert a["confidence"] == 0.9 and "confidence_raw" not in a["witness"]


def test_admission_rejects_out_of_range_confidence():
    with pytest.raises(pd.ProfileDocumentError, match="range"):
        pd.admission("accepted", "inherited_production", source_kind="override_file", mechanism="m",
                     confidence=1.5, source_author="agent", recorded_at=NOW, run_id=RUN, source="s",
                     inception_evaluation="none_available")


def test_admission_rejects_nan_confidence():
    with pytest.raises(pd.ProfileDocumentError, match="NaN"):
        pd.admission("accepted", "inherited_production", source_kind="override_file", mechanism="m",
                     confidence=float("nan"), source_author="agent", recorded_at=NOW, run_id=RUN, source="s",
                     inception_evaluation="none_available")


def test_load_document_rejects_bad_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="ascii")
    with pytest.raises(pd.ProfileDocumentError, match="JSON"):
        pd.load_document(path)


def test_load_document_rejects_non_ascii_bytes(tmp_path):
    path = tmp_path / "bad.json"
    path.write_bytes(b'{"x": "\xc3\xa9"}')
    with pytest.raises(pd.ProfileDocumentError, match="ASCII"):
        pd.load_document(path)
