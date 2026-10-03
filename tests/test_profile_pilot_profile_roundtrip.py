"""SP3 proper Task 7: documents -> override shapes identical to the originals; production loader parity.

Fix round 1 (review on b76a0af): the round trip must see the SERIALISED document (I1), verify its own
recorded hashes rather than trust them (I2), compare against a FILESYSTEM-derived expected set rather than
a document-derived one (I3, the actual loss-detection guarantee), pinpoint every difference (I4), and make
loader_parity honest about absent files and report compared counts (I5), reading grammars/anchors with the
production encoding (I6).

The real-shape test reads the worktree's git-tracked data/overrides (read-only) for the 8 pilot filers and
writes only under tmp_path. If the scan raises FamilyError on the real tree, STOP and report it: the
disposition table is not widened inside this task."""
from __future__ import annotations

import json

import pytest

from scripts.profile_pilot import cohort
from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_families as pf
from scripts.profile_pilot import profile_inception as pi
from scripts.profile_pilot import profile_roundtrip as rt
from scripts.profile_pilot.translate import value_sha256
from tests.test_profile_pilot_paths import CODE_ROOT
from tests.test_profile_pilot_profile_families import STELLUS, wrapper_v3
from tests.test_profile_pilot_profile_inception import NOW, RUN, SHA, inception_inputs, totals_input

REAL = CODE_ROOT / "data" / "overrides"
ORACLE = "bdc_xbrl_oracle_exceptions.json"


def synthetic():
    mine = {"cik": STELLUS, "report_date": "2025-12-31", "oracle_reason": "rate_outliers_detected"}
    original = [{"cik": "0001111111", "report_date": "2024-12-31", "oracle_reason": "x"}, mine,
                {"cik": "0002222222", "report_date": "2025-03-31", "oracle_reason": "y"}]
    inputs = inception_inputs(shared={ORACLE: {"sha256": SHA, "records": [[1, mine]]}})
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    originals = {x["path"]: x["content"] for items in inputs["files"].values() for x in items}
    originals[ORACLE] = original
    return doc, originals, {ORACLE: original}


# ---------------------------------------------------------------- original Step-1 tests (unchanged behaviour)

def test_synthetic_round_trip_is_identical():
    doc, originals, shared = synthetic()
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    assert out["ok"] and out["counts"] == {"identical": 3, "differs": 0, "missing": 0, "extra": 0}
    assert rt.expected_paths([doc]) == sorted(originals)


def test_missing_pilot_record_breaks_the_tiling():
    doc, _, shared = synthetic()
    doc["corrections"] = []
    with pytest.raises(rt.RoundTripError, match="tile"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_missing_and_extra_files_are_reported():
    out = rt.roundtrip_check({"a.json": {}}, {"b.json": {}})
    assert out["files"] == {"a.json": "extra", "b.json": "missing"} and not out["ok"]


# ---------------------------------------------------------------- key-order differs (I4), now hash-consistent

def test_key_order_change_is_a_difference():
    # The mutated block recomputes its OWN hash anchors (content_sha256, source_files[].ordered_sha256) to
    # stay internally consistent -- this is "my regenerated content disagrees with the true original file
    # on disk", not "my document's own recorded hash is stale" (that is the separate I2 test below).
    doc, originals, shared = synthetic()
    block = doc["wrapper_section"]["blocks"][0]
    rules = block["content"]["dispatch"]["prefix_rules"]
    block["content"]["dispatch"]["prefix_rules"] = dict(reversed(list(rules.items())))
    block["content_sha256"] = value_sha256(block["content"])
    block["source_files"][0]["ordered_sha256"] = value_sha256(block["content"])
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    assert not out["ok"] and out["files"]["bdc_xbrl_wrappers/" + STELLUS + ".json"] == "differs"
    assert out["first_difference"]["bdc_xbrl_wrappers/" + STELLUS + ".json"].startswith(
        "/dispatch/prefix_rules")


# ---------------------------------------------------------------- I2: recorded hashes are verified, not trusted

def test_stale_block_content_sha256_raises():
    doc, _, shared = synthetic()
    block = doc["wrapper_section"]["blocks"][0]
    block["content_sha256"] = "0" * 64
    with pytest.raises(rt.RoundTripError, match="content_sha256"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_stale_source_files_ordered_sha256_raises():
    doc, _, shared = synthetic()
    block = doc["wrapper_section"]["blocks"][0]
    block["source_files"][0]["ordered_sha256"] = "0" * 64
    with pytest.raises(rt.RoundTripError, match="ordered_sha256"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_stale_disposition_ordered_sha256_raises():
    doc, _, shared = synthetic()
    for d in doc["disposition"]:
        if d["path"] == "rate_convention/" + STELLUS + ".json":
            d["ordered_sha256"] = "0" * 64
    with pytest.raises(rt.RoundTripError, match="ordered_sha256"):
        rt.materialise_overrides([doc], shared_originals=shared)


# ---------------------------------------------------------------- I4: generic comparator mechanics (every
# family's materialised content flows through the same roundtrip_check comparator, so these cover the
# mutation kinds -- changed scalar, reordered key, reordered list, int/float, removed key -- once, for every
# family that round-trips, rather than duplicating per-family fixtures)

FIRST_DIFFERENCE_CASES = [
    ("changed scalar", {"a": 1, "b": 2}, {"a": 1, "b": 3}, "/b"),
    ("reordered key", {"a": 1, "b": 2}, {"b": 2, "a": 1}, "/"),
    ("reordered list", {"a": [1, 2, 3]}, {"a": [3, 2, 1]}, "/a/0"),
    ("int changed to float", {"rate": 1}, {"rate": 1.0}, "/rate"),
    ("removed key", {"a": 1, "b": 2}, {"a": 1}, "/b"),
]


@pytest.mark.parametrize("label,materialised,original,pointer_prefix", FIRST_DIFFERENCE_CASES,
                         ids=[c[0] for c in FIRST_DIFFERENCE_CASES])
def test_first_difference_pinpoints_the_change(label, materialised, original, pointer_prefix):
    out = rt.roundtrip_check({"x.json": materialised}, {"x.json": original})
    assert out["files"]["x.json"] == "differs"
    assert out["first_difference"]["x.json"].startswith(pointer_prefix), out["first_difference"]


def test_identical_content_has_no_first_difference_entry():
    out = rt.roundtrip_check({"x.json": {"a": 1}}, {"x.json": {"a": 1}})
    assert out["files"]["x.json"] == "identical" and "x.json" not in out["first_difference"]


# ---------------------------------------------------------------- I4: one realistic case per converted family
# (hash-consistent mutations, so these test the comparator against the true original, not hash staleness)

def test_wrapper_block_differs_is_pinpointed():
    doc, originals, shared = synthetic()
    block = doc["wrapper_section"]["blocks"][0]
    block["content"]["dispatch"]["aggregate_markers"] = ["total portfolio"]
    block["content_sha256"] = value_sha256(block["content"])
    block["source_files"][0]["ordered_sha256"] = value_sha256(block["content"])
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    path = "bdc_xbrl_wrappers/" + STELLUS + ".json"
    assert out["files"][path] == "differs"
    assert out["first_difference"][path] == "/dispatch/aggregate_markers/0 value differs ('total portfolio' vs 'total investments')"


def test_inherited_entry_differs_is_pinpointed():
    # materialise_overrides re-derives entries from doc["events"] (envelope.materialize_entries), not
    # from the pre-computed doc["entries"] snapshot -- the event body is what must be mutated.
    doc, originals, shared = synthetic()
    event = next(e for e in doc["events"] if e["event"] == "assert" and e["entry"]["key"] == "meaning.interest_rate")
    event["entry"]["value"] = dict(event["entry"]["value"], convention="cash_leg")
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    path = "rate_convention/" + STELLUS + ".json"
    assert out["files"][path] == "differs"
    assert out["first_difference"][path] == "/convention value differs ('cash_leg' vs 'all_in')"


def test_b2_correction_differs_is_pinpointed():
    inputs = inception_inputs(extra_files={"agent_b2_corrections": [
        dict(path="agent_b2_corrections/" + STELLUS + "/zero_fill.json", sha256=SHA,
             content={"cik": STELLUS, "mechanism": "extraction_gap", "fix_class": "zero_fill",
                      "scope": {"quarters": ["2025-12-31"]}, "template": {"row_selector": {"row_id": "ROW-1"}}})]})
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    originals = {x["path"]: x["content"] for items in inputs["files"].values() for x in items}
    correction = next(c for c in doc["corrections"] if c["family"] == "agent_b2_corrections")
    correction["value"]["template"]["row_selector"]["row_id"] = "ROW-2"
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals={}), originals)
    path = "agent_b2_corrections/" + STELLUS + "/zero_fill.json"
    assert out["files"][path] == "differs"
    assert out["first_difference"][path] == "/template/row_selector/row_id value differs ('ROW-2' vs 'ROW-1')"


def test_shared_file_correction_differs_is_pinpointed():
    doc, originals, shared = synthetic()
    correction = next(c for c in doc["corrections"] if c["family"] == ORACLE)
    correction["value"]["oracle_reason"] = "something_else"
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    assert out["files"][ORACLE] == "differs"
    assert out["first_difference"][ORACLE] == "/1/oracle_reason value differs ('something_else' vs 'rate_outliers_detected')"


# ---------------------------------------------------------------- shared record_index integrity

def test_record_index_targeting_a_non_pilot_record_raises():
    doc, _, shared = synthetic()
    correction = next(c for c in doc["corrections"] if c["family"] == ORACLE)
    correction["source"]["record_index"] = 0   # belongs to cik 0001111111, not STELLUS
    with pytest.raises(rt.RoundTripError, match="non-pilot"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_duplicate_record_index_raises():
    doc, _, shared = synthetic()
    correction = next(c for c in doc["corrections"] if c["family"] == ORACLE)
    dup = dict(correction)
    doc["corrections"] = list(doc["corrections"]) + [dup]
    with pytest.raises(rt.RoundTripError, match="more than one"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_non_dict_shared_record_raises_round_trip_error_not_attributeerror():
    doc, originals, shared = synthetic()
    shared = {ORACLE: list(shared[ORACLE])}
    shared[ORACLE][0] = "not a record"
    with pytest.raises(rt.RoundTripError, match="not an object"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_unknown_wrapper_block_family_raises_round_trip_error():
    doc, _, shared = synthetic()
    doc["wrapper_section"]["blocks"][0]["family"] = "something_new"
    with pytest.raises(rt.RoundTripError, match="unknown wrapper block family"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_inherited_evidence_path_without_prefix_raises():
    # Same note as above: mutate the event body, not the doc["entries"] snapshot.
    doc, _, shared = synthetic()
    for e in doc["events"]:
        if e["event"] == "assert" and e["entry"]["key"] == "meaning.interest_rate":
            for item in e["entry"]["evidence"]:
                if item.get("kind") == "override_file" and item.get("value_is_file") is True:
                    item["path"] = item["path"][len("data/overrides/"):]   # strip the prefix
    with pytest.raises(rt.RoundTripError, match="prefix"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_round_trip_error_is_a_profile_document_error():
    assert issubclass(rt.RoundTripError, pd.ProfileDocumentError)


# ---------------------------------------------------------------- M1: a shared file the requested ciks never
# touch is not reported as a false "extra"

def test_unrelated_shared_file_is_not_emitted():
    doc, _, _ = synthetic()
    doc["corrections"] = [c for c in doc["corrections"] if c["family"] != ORACLE]
    unrelated = [{"cik": "0009999999", "report_date": "2024-12-31", "oracle_reason": "z"}]
    mat = rt.materialise_overrides([doc], shared_originals={ORACLE: unrelated})
    assert ORACLE not in mat


# ---------------------------------------------------------------- I1: the round trip must see the SERIALISED
# document, not just the in-memory one

def test_disk_round_trip_through_load_document_matches_in_memory():
    doc, originals, shared = synthetic()
    path = None

    def write(tmp_path, value, **kw):
        nonlocal path
        path = tmp_path / "doc.json"
        path.write_text(json.dumps(value, ensure_ascii=True, indent=2, **kw) + "\n", encoding="ascii")
        return path

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        p = write(Path(td), doc)
        mat_disk = rt.load_and_materialise([p], shared_originals=shared)
    mat_memory = rt.materialise_overrides([doc], shared_originals=shared)
    assert mat_disk == mat_memory


def test_sort_keys_serialisation_is_refused_by_the_recorded_hash(tmp_path):
    # A sort_keys writer reorders the wrapper content (dispatch.prefix_rules is first-match, so order is
    # behaviour). The reread document's block content no longer hashes to its own recorded content_sha256,
    # so I2 refuses it BEFORE any comparison with the originals -- a stronger outcome than a "differs" row.
    # (This test first expected "differs"; that is unreachable once I2 verifies the recorded hashes. The
    # comparator's own key-order detection is covered by test_key_order_change_is_a_difference.)
    doc, _, shared = synthetic()
    p = tmp_path / "doc.json"
    p.write_text(json.dumps(doc, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="ascii")
    with pytest.raises(rt.RoundTripError, match="content_sha256 is stale"):
        rt.load_and_materialise([p], shared_originals=shared)


def test_malformed_document_raises_round_trip_error_not_keyerror():
    # M2: a missing section or a wrong container type is a RoundTripError, never a bare KeyError/TypeError.
    doc, _, shared = synthetic()
    del doc["wrapper_section"]
    with pytest.raises(rt.RoundTripError, match="malformed document"):
        rt.materialise_overrides([doc], shared_originals=shared)
    doc2, _, shared2 = synthetic()
    with pytest.raises(rt.RoundTripError, match="malformed document"):
        rt.materialise_overrides([doc2], shared_originals={ORACLE: 7})


def test_rules_block_whose_files_do_not_match_its_source_files_raises():
    # I2: a rules block must carry a recorded hash for every file it regenerates.
    rule = {"cik": STELLUS, "rule_id": "x", "rule_type": "row_add", "scope": {"quarters": ["2025-12-31"]}}
    rel = "agent_investigate_rules/" + STELLUS + "/x.json"
    inputs = inception_inputs(extra_files={"agent_investigate_rules": [dict(path=rel, sha256=SHA, content=rule)]})
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    assert rel in rt.materialise_overrides([doc], shared_originals={})
    block = next(b for b in doc["wrapper_section"]["blocks"] if b["family"] == "agent_investigate_rules")
    block["source_files"] = []
    with pytest.raises(rt.RoundTripError, match="do not match its source_files"):
        rt.materialise_overrides([doc], shared_originals={})


# ---------------------------------------------------------------- I3: filesystem-derived expected set catches
# a loss the document-derived set would miss

def test_filesystem_expected_paths_catches_a_silently_dropped_file(tmp_path):
    root = tmp_path / "overrides"
    leaf = {"cik": STELLUS, "convention": "all_in", "target_quarter": "2026-03-31"}
    path = root / "rate_convention" / (STELLUS + ".json")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(leaf), encoding="utf-8")
    want = rt.filesystem_expected_paths(root, [STELLUS])
    assert want == ["rate_convention/" + STELLUS + ".json"]
    # A document that converted nothing for this filer (the bug this check exists to catch): its own
    # disposition-derived expected_paths is empty, so comparing materialised-vs-original using THAT set
    # would never see the loss. The filesystem-derived set still names the file as missing.
    empty_doc = dict(cik=STELLUS, disposition=[])
    assert rt.expected_paths([empty_doc]) == []
    originals = {rel: pf.read_json(root / rel) for rel in want}
    out = rt.roundtrip_check({}, originals)
    assert out["files"]["rate_convention/" + STELLUS + ".json"] == "missing"


def test_filesystem_expected_paths_shared_file_requires_a_mention():
    root = REAL
    want_mentioning = rt.filesystem_expected_paths(root, [STELLUS])
    assert ORACLE not in want_mentioning or any(
        pf.cik10(r.get("cik")) == STELLUS for r in pf.read_json(root / ORACLE))


# ---------------------------------------------------------------- M5: shared-file pilot record counts

def test_pilot_record_counts_reflects_the_corrections():
    doc, _, _ = synthetic()
    counts = rt.pilot_record_counts([doc])
    assert counts == {ORACLE: 1}


# ---------------------------------------------------------------- I5/I6: loader_parity honesty

ARES = "0001287750"


def _write_json(path, value, *, bom=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if bom else "utf-8"
    path.write_text(json.dumps(value), encoding=encoding)


def test_loader_parity_reports_absent_not_match_when_neither_tree_has_the_file(tmp_path):
    orig, mat = tmp_path / "orig", tmp_path / "mat"
    orig.mkdir()
    mat.mkdir()
    parity = rt.loader_parity(orig, mat, ["0009999999"])
    assert parity["identifier_anchors"]["0009999999"] == rt.ABSENT
    assert parity["identifier_rate_grammars"]["0009999999"] == rt.ABSENT
    assert parity["rate_convention"]["0009999999"] == rt.ABSENT
    assert parity["agent_investigate_rules"]["0009999999"] == rt.ABSENT
    assert parity["bdc_xbrl_wrappers"]["0009999999"] == rt.ABSENT
    assert parity["agent_b2_corrections"]["status"] == rt.ABSENT
    assert parity["ok"] is True


def test_loader_parity_edited_wrapper_prefix_rules_order_is_not_ok(tmp_path):
    orig, mat = tmp_path / "orig", tmp_path / "mat"
    w = wrapper_v3(ARES)
    _write_json(orig / "bdc_xbrl_wrappers" / (ARES + ".json"), w)
    edited = dict(w, dispatch=dict(w["dispatch"],
                                   prefix_rules=dict(reversed(list(w["dispatch"]["prefix_rules"].items())))))
    _write_json(mat / "bdc_xbrl_wrappers" / (ARES + ".json"), edited)
    parity = rt.loader_parity(orig, mat, [ARES])
    assert parity["bdc_xbrl_wrappers"][ARES] == rt.MISMATCH
    assert parity["ok"] is False
    assert "dispatch spec" in parity["wrapper_scope_note"]


def test_loader_parity_edited_b2_leaf_is_not_ok(tmp_path):
    orig, mat = tmp_path / "orig", tmp_path / "mat"
    leaf = {"cik": ARES, "mechanism": "extraction_gap", "fix_class": "zero_fill", "template": {"x": 1}}
    _write_json(orig / "agent_b2_corrections" / ARES / "zero_fill.json", leaf)
    _write_json(mat / "agent_b2_corrections" / ARES / "zero_fill.json", dict(leaf, template={"x": 2}))
    parity = rt.loader_parity(orig, mat, [ARES])
    assert parity["agent_b2_corrections"]["status"] == rt.MISMATCH
    assert parity["agent_b2_corrections"]["compared"] == 1
    assert parity["ok"] is False


def test_loader_parity_removed_rule_file_is_not_ok(tmp_path):
    orig, mat = tmp_path / "orig", tmp_path / "mat"
    rule_a = {"cik": ARES, "rule_id": "a", "rule_type": "row_add", "scope": {"quarters": ["2025-12-31"]}}
    rule_b = {"cik": ARES, "rule_id": "b", "rule_type": "row_add", "scope": {"quarters": ["2025-12-31"]}}
    _write_json(orig / "agent_investigate_rules" / ARES / "a.json", rule_a)
    _write_json(orig / "agent_investigate_rules" / ARES / "b.json", rule_b)
    _write_json(mat / "agent_investigate_rules" / ARES / "a.json", rule_a)
    parity = rt.loader_parity(orig, mat, [ARES])
    assert parity["agent_investigate_rules"][ARES] == rt.MISMATCH
    assert parity["ok"] is False


def test_loader_parity_edited_convention_is_not_ok(tmp_path):
    orig, mat = tmp_path / "orig", tmp_path / "mat"
    leaf = {"cik": ARES, "convention": "all_in"}
    _write_json(orig / "rate_convention" / (ARES + ".json"), leaf)
    _write_json(mat / "rate_convention" / (ARES + ".json"), dict(leaf, convention="cash_leg"))
    parity = rt.loader_parity(orig, mat, [ARES])
    assert parity["rate_convention"][ARES] == rt.MISMATCH
    assert parity["ok"] is False


def test_loader_parity_bom_prefixed_anchor_fixture_is_flagged(tmp_path):
    orig, mat = tmp_path / "orig", tmp_path / "mat"
    spec = {"anchors": [{"label": "DEBT", "regex": "^Debt"}]}
    _write_json(orig / "identifier_anchors" / (ARES + ".json"), spec)
    _write_json(mat / "identifier_anchors" / (ARES + ".json"), spec, bom=True)
    parity = rt.loader_parity(orig, mat, [ARES])
    assert parity["identifier_anchors"][ARES] not in (rt.MATCH, rt.ABSENT)
    assert parity["ok"] is False


def test_loader_parity_bom_prefixed_grammar_fixture_is_flagged(tmp_path):
    orig, mat = tmp_path / "orig", tmp_path / "mat"
    grammar = {"schema_version": "agentA-rate-grammar.v1", "cik": ARES, "extractors": []}
    _write_json(orig / "identifier_rate_grammars" / (ARES + ".json"), grammar)
    _write_json(mat / "identifier_rate_grammars" / (ARES + ".json"), grammar, bom=True)
    parity = rt.loader_parity(orig, mat, [ARES])
    assert parity["identifier_rate_grammars"][ARES] not in (rt.MATCH, rt.ABSENT)
    assert parity["ok"] is False


# ---------------------------------------------------------------- real tree (read-only data/overrides)

def real_documents():
    hits = pf.scan_overrides(REAL, cohort.PILOT_CIKS)
    docs = []
    for cik in cohort.PILOT_CIKS:
        inputs = pf.collect_override_inputs(REAL, cik, hits)
        # build_document requires exactly one of census_q4 / census_q4_unavailable (Task 6 fix round 1,
        # finding 5). This test supplies no census, so it says so explicitly.
        inputs.update(attested_under={}, census_q4=None,
                      census_q4_unavailable=dict(census_run_id="none", reason="unavailable",
                                                 detail="no census supplied to the round-trip test"),
                      census_q1=None, detection={},
                      predicate=dict(version="census-published.v2", code_sha256="0" * 64),
                      # No totals result is supplied either (final review I3): published_basis is then a
                      # candidate with a stub, which is the honest shape for a document built without one.
                      totals=totals_input(None, cik=cik), code_mirror=[],
                      overrides_root="worktree data/overrides", replay_run_id="none")
        docs.append(pi.build_document(cik, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9"))
    return docs


PINNED_FAMILY_COUNTS = {
    "bdc_xbrl_wrappers": 8, "agent_investigate_rules": 14, "agent_b2_corrections": 4,
    "identifier_anchors": 5, "identifier_rate_grammars": 5, "rate_convention": 2,
    "bdc_aggregate_row_overrides.json": 1, "bdc_xbrl_oracle_exceptions.json": 1,
}


def test_real_tracked_overrides_round_trip_and_load_identically(tmp_path):
    docs = real_documents()
    shared = {n: pf.read_json(REAL / n) for n in pf.SHARED_FILES if (REAL / n).is_file()}
    mat = rt.materialise_overrides(docs, shared_originals=shared)

    # I3: the expected set comes from the filesystem (scan_overrides), not from the documents.
    want = rt.filesystem_expected_paths(REAL, cohort.PILOT_CIKS)
    by_family = {}
    for rel in want:
        fam = rel if "/" not in rel else rel.split("/", 1)[0]
        by_family[fam] = by_family.get(fam, 0) + 1
    assert by_family == PINNED_FAMILY_COUNTS
    assert len(want) == sum(PINNED_FAMILY_COUNTS.values()) == 40
    # Sanity (not a gate): today nothing is lost, so the document-derived set agrees with the
    # filesystem-derived one. If a future bug makes build_document drop a file, this line -- not the
    # roundtrip_check below -- is what would catch the disagreement.
    assert set(rt.expected_paths(docs)) == set(want)

    originals = {rel: pf.read_json(REAL / rel) for rel in want}
    result = rt.roundtrip_check(mat, originals)
    assert result["ok"], {k: v for k, v in result["files"].items() if v != "identical"}
    assert result["counts"] == {"identical": 40, "differs": 0, "missing": 0, "extra": 0}
    assert not result["first_difference"]

    pilot_counts = rt.pilot_record_counts(docs)
    assert set(pilot_counts) <= set(pf.SHARED_FILES)
    assert all(n >= 1 for n in pilot_counts.values())

    # I1: the round trip must survive an actual write + reread, not just the in-memory document.
    doc_root = tmp_path / "documents"
    doc_root.mkdir()
    doc_paths = []
    for doc in docs:
        p = doc_root / (doc["cik"] + ".json")
        p.write_text(json.dumps(doc, ensure_ascii=True, indent=2) + "\n", encoding="ascii")
        doc_paths.append(p)
    mat_from_disk = rt.load_and_materialise(doc_paths, shared_originals=shared)
    assert mat_from_disk == mat

    root = tmp_path / "materialised"
    for rel, value in mat.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    parity = rt.loader_parity(REAL, root, cohort.PILOT_CIKS)
    assert parity["ok"], parity
    assert set(parity["bdc_xbrl_wrappers"]) == set(cohort.PILOT_CIKS)
    assert parity["counts"]["bdc_xbrl_wrappers"]["match"] == 8
    assert parity["counts"]["identifier_anchors"]["match"] == 5
    assert parity["counts"]["identifier_rate_grammars"]["match"] == 5
    assert parity["agent_b2_corrections"]["compared"] >= 1
    assert parity["bdc_xbrl_oracle_exceptions"]["status"] == rt.MATCH
    assert not any(str(v).startswith("error") for fam in ("identifier_anchors", "identifier_rate_grammars")
                   for v in parity[fam].values())
