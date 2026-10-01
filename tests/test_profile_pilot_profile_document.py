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
