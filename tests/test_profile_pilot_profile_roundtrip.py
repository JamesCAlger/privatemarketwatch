"""SP3 proper Task 7: documents -> override shapes identical to the originals; production loader parity.

The real-shape test reads the worktree's git-tracked data/overrides (read-only) for the 8 pilot filers and writes
only under tmp_path. If the scan raises FamilyError on the real tree, STOP and report it: the disposition table is
not widened inside this task."""
from __future__ import annotations

import json

import pytest

from scripts.profile_pilot import cohort
from scripts.profile_pilot import profile_families as pf
from scripts.profile_pilot import profile_inception as pi
from scripts.profile_pilot import profile_roundtrip as rt
from tests.test_profile_pilot_paths import CODE_ROOT
from tests.test_profile_pilot_profile_families import STELLUS
from tests.test_profile_pilot_profile_inception import NOW, RUN, SHA, inception_inputs

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


def test_synthetic_round_trip_is_identical():
    doc, originals, shared = synthetic()
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    assert out["ok"] and out["counts"] == {"identical": 3, "differs": 0, "missing": 0, "extra": 0}
    assert rt.expected_paths([doc]) == sorted(originals)


def test_key_order_change_is_a_difference():
    doc, originals, shared = synthetic()
    block = doc["wrapper_section"]["blocks"][0]
    rules = block["content"]["dispatch"]["prefix_rules"]
    block["content"]["dispatch"]["prefix_rules"] = dict(reversed(list(rules.items())))
    out = rt.roundtrip_check(rt.materialise_overrides([doc], shared_originals=shared), originals)
    assert not out["ok"] and out["files"]["bdc_xbrl_wrappers/" + STELLUS + ".json"] == "differs"


def test_missing_pilot_record_breaks_the_tiling():
    doc, _, shared = synthetic()
    doc["corrections"] = []
    with pytest.raises(rt.RoundTripError, match="tile"):
        rt.materialise_overrides([doc], shared_originals=shared)


def test_missing_and_extra_files_are_reported():
    out = rt.roundtrip_check({"a.json": {}}, {"b.json": {}})
    assert out["files"] == {"a.json": "extra", "b.json": "missing"} and not out["ok"]


def real_documents():
    hits = pf.scan_overrides(REAL, cohort.PILOT_CIKS)
    docs = []
    for cik in cohort.PILOT_CIKS:
        inputs = pf.collect_override_inputs(REAL, cik, hits)
        inputs.update(attested_under={}, census_q4=None, census_q4_unavailable=None, census_q1=None, detection={},
                      predicate=dict(version="census-published.v2", code_sha256="0" * 64), code_mirror=[],
                      overrides_root="worktree data/overrides", replay_run_id="none")
        docs.append(pi.build_document(cik, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9"))
    return docs


def test_real_tracked_overrides_round_trip_and_load_identically(tmp_path):
    docs = real_documents()
    shared = {n: pf.read_json(REAL / n) for n in pf.SHARED_FILES if (REAL / n).is_file()}
    mat = rt.materialise_overrides(docs, shared_originals=shared)
    originals = {rel: pf.read_json(REAL / rel) for rel in rt.expected_paths(docs)}
    result = rt.roundtrip_check(mat, originals)
    assert result["ok"], {k: v for k, v in result["files"].items() if v != "identical"}
    assert result["counts"]["identical"] >= 30
    root = tmp_path / "materialised"
    for rel, value in mat.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    parity = rt.loader_parity(REAL, root, cohort.PILOT_CIKS)
    assert parity["ok"], parity
    assert set(parity["bdc_xbrl_wrappers"]) == set(cohort.PILOT_CIKS)
