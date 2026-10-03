"""SP3 proper Task 9: profile_document_run on a fake main root (tmp_path only; git attestation stubbed).

Task 9 deviations from the literal task brief, following the current code and the task instructions where they
conflict with the brief's own pseudo-code (noted in task-9-report.md):
  - A1 (controller pre-flight ruling): the Q1-2026 census role is "verified_era", not "all:2026-03-31"; seed()
    below seeds that role for the Q1 row (the brief's literal seed() used "all:" + date for both rows).
  - I1/I3 (Task 7 review): the round trip goes through the document AS WRITTEN (pd.load_document), and the
    original file list comes from profile_roundtrip.filesystem_expected_paths, never from the documents.
  - A7/A8: the MAIN checkout's data/overrides is guarded read-only for the run (separately from the standard
    protected_session), and the build declares a typed workload, refusing (LeaseRefused) if it classifies heavy.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_document_run as run
from scripts.profile_pilot.paths import PathError
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths
from tests.test_profile_pilot_profile_families import STELLUS, write_tree, wrapper_v3
from tests.test_profile_pilot_profile_inception import Q1, Q4, census

CENSUS_RUN, REPLAY_RUN, AT = "stageb2-fakecensus", "sp1-replay-fake", "2026-10-01T12:00:00Z"


def oracle_record(cik, report_date, oracle_reason, *, status="accepted", confidence=0.9):
    """Every field load_bdc_xbrl_oracle_exceptions requires as non-empty (pipeline/bdc_xbrl_oracle_exceptions.py
    _REQUIRED_COLUMNS) -- the brief's literal two-field fixture predates that loader's hardening and the
    production loader now raises ValueError on it; profile_roundtrip.loader_parity calls that loader for real
    (I5), so the fixture must satisfy its schema."""
    return {"cik": cik, "report_date": report_date, "oracle_reason": oracle_reason, "wrapper_version": "v1",
           "status": status, "confidence": confidence, "reason": "test fixture", "evidence": "test fixture",
           "residual_risk": "none", "created_by": "test", "accepted_by": "test", "updated_at": report_date}


def seed(paths):
    data = paths.data_root
    write_tree(data / "overrides", {
        "bdc_xbrl_wrappers/" + STELLUS + ".json": wrapper_v3(STELLUS),
        "rate_convention/" + STELLUS + ".json": {"cik": STELLUS, "convention": "all_in", "target_quarter": Q1},
        "bdc_xbrl_oracle_exceptions.json": [
            oracle_record("0001111111", "2024-12-31", "x", status="proposed", confidence=0.5),
            oracle_record(STELLUS, Q4, "rate_outliers_detected")]})
    root = data / "pilot" / "filer_profile" / CENSUS_RUN
    rows = []
    # A1: Q4 gets a generic "all:" role (the real cohort's q1/q2 primary dates never fall on 2025-12-31 for
    # any of the 8 pilot filers); Q1 is always "verified_era" by construction of the fixed verified-era date.
    for date, role in ((Q4, "all:" + Q4), (Q1, "verified_era")):
        rel = "census/" + STELLUS + "/" + date + ".json"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        body = dict(complete=True, identity=dict(fingerprint="f" * 64), result=census(date)["doc"])
        path.write_text(json.dumps(body), encoding="ascii")
        rows.append(dict(cik=STELLUS, role=role, report_date=date, census_relative=rel,
                         census_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), fingerprint="f" * 64,
                         validation_verdict="pass"))
    (root / "results").mkdir(parents=True)
    (root / "results" / "authoritative.json").write_text(json.dumps(dict(fund_quarters=rows)), encoding="ascii")
    (root / "results" / "excluded.json").write_text(json.dumps(dict(fund_quarters=[])), encoding="ascii")
    replay = data / "pilot" / "filer_profile" / REPLAY_RUN / "results"
    replay.mkdir(parents=True)
    floors = {"fill_rate": dict(verdict="NO_POSITIVES"), "independent_totals": dict(verdict="FAIL")}
    (replay / "replay_q4_q1.json").write_text(json.dumps(dict(floors=floors)), encoding="ascii")


@pytest.fixture
def staged(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="sp3p-profile-test")
    seed(paths)
    monkeypatch.setattr(run, "attested_under", lambda main_root, rel, content: [])
    return paths


def build(paths):
    return run.run_stage(paths, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN, ciks=[STELLUS], recorded_at=AT)


def test_build_writes_documents_roundtrip_and_exit_test(staged):
    summary = build(staged)
    rr = staged.run_root
    doc = pd.load_document(rr / "profiles" / (STELLUS + ".json"))
    assert list(doc["wrapper_section"]["blocks"][0]["content"]["dispatch"]["prefix_rules"]) == ["Second Lien",
                                                                                                "First Lien"]
    assert doc["detection_claims"]["fill_rate"]["claim"] == "detection_not_claimed"
    assert (rr / "roundtrip" / "overrides" / "bdc_xbrl_oracle_exceptions.json").is_file()
    roundtrip = json.loads((rr / "results" / "roundtrip.json").read_text(encoding="ascii"))
    assert roundtrip["ok"] is True and roundtrip["counts"]["differs"] == 0 and roundtrip["loader_parity"]["ok"]
    body = json.loads((rr / "results" / "exit_test.json").read_text(encoding="ascii"))
    assert body["per_cik"][STELLUS]["criterion_1"] and body["per_cik"][STELLUS]["resolver"]
    assert body["verdict"] == "FAIL" and len(body["missing_filers"]) == 7   # a one-filer run never claims the 8
    assert summary["verdict"] == "FAIL"
    pinned = json.loads((rr / "manifest.json").read_text(encoding="ascii"))["inputs"]
    assert any(i["label"] == "overrides/rate_convention/" + STELLUS + ".json" for i in pinned)


def test_rerun_on_the_same_run_id_is_refused(staged):
    build(staged)
    with pytest.raises(PathError):
        build(staged)


def test_run_id_prefix_is_enforced(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-profile-x")
    with pytest.raises(PathError, match="sp3p-profile-"):
        run.run_stage(paths, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN)
    assert run.main(["build", "--data-root", str(paths.data_root), "--main-root", str(paths.main_repo_root),
                     "--run-id", "stageb-profile-x", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN]) == run.EXIT_REFUSED


def test_no_production_module_reads_profile_documents():
    for path in (CODE_ROOT / "pipeline").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ("data/profiles", "profile_document", "profile_inception"):
            assert needle not in text, (str(path), needle)


# ---------------------------------------------------------------- A7: MAIN checkout data/overrides guard


def test_main_overrides_change_during_the_run_is_caught(staged, monkeypatch):
    """A7: data/overrides of the MAIN checkout (here, the fake main root the build reads) is a read-only
    root specific to this CLI. Simulate another process writing there mid-build (the first per-filer
    collect_override_inputs call is a convenient, harmless hook point) and confirm the guard, not the
    ordinary stage logic, is what catches it."""
    original = run.pf.collect_override_inputs
    touched: dict = {}

    def spy(root, cik, hits):
        if not touched:
            (Path(root) / "sp3p_t9_concurrent_write.json").write_text("{}", encoding="ascii")
            touched["done"] = True
        return original(root, cik, hits)

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    with pytest.raises(run.PreservationError):
        build(staged)


def test_main_overrides_unchanged_run_does_not_trip_the_guard(staged):
    """Sanity companion to the test above: an ordinary run over the same root does not false-positive."""
    build(staged)


# ---------------------------------------------------------------- A8: typed workload, refused when heavy


def test_heavy_workload_without_a_lease_is_refused(staged, monkeypatch):
    monkeypatch.setattr(run.manifest, "classify_workload", lambda workload: True)
    with pytest.raises(run.LeaseRefused):
        build(staged)
    assert not (staged.run_root / "manifest.json").is_file()   # refused before the first write


def test_main_reports_refused_exit_code_for_a_heavy_workload(staged, monkeypatch):
    monkeypatch.setattr(run.manifest, "classify_workload", lambda workload: True)
    assert run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", staged.run_id, "--census-run-id", CENSUS_RUN, "--replay-run-id", REPLAY_RUN,
                     "--cik", STELLUS]) == run.EXIT_REFUSED
