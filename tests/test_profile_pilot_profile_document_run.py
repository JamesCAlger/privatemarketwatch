"""SP3 proper Task 9: profile_document_run on a fake main root (tmp_path only; git attestation stubbed).

Fix round 1 (review of dc74ef9) additions, grouped by finding id (F1-F11, M1-M2; see task-9-report.md's
"Fix round 1" section for the file:line map). Task 9 deviations from the literal task brief are unchanged
from the first round (A1 census role selection, I1/I3 round-trip sourcing, A7/A8 guard/workload) and are
not re-documented here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_document_run as run
from scripts.profile_pilot.paths import PathError
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths
from tests.test_profile_pilot_profile import detector, outcome, single_dialect
from tests.test_profile_pilot_profile_families import ARES, STELLUS, write_tree, wrapper_v3
from tests.test_profile_pilot_profile_inception import Q1, Q4, census

CENSUS_RUN, REPLAY_RUN, AT = "stageb2-fakecensus", "sp1-replay-fake", "2026-10-01T12:00:00Z"
IDENT = "us-gaap:InvestmentIdentifierAxis"


# ---------------------------------------------------------------- fixture builders


def oracle_record(cik, report_date, oracle_reason, *, status="accepted", confidence=0.9):
    """Every field load_bdc_xbrl_oracle_exceptions requires as non-empty (pipeline/bdc_xbrl_oracle_exceptions.py
    _REQUIRED_COLUMNS) -- the brief's literal two-field fixture predates that loader's hardening and the
    production loader now raises ValueError on it; profile_roundtrip.loader_parity calls that loader for real
    (I5), so the fixture must satisfy its schema."""
    return {"cik": cik, "report_date": report_date, "oracle_reason": oracle_reason, "wrapper_version": "v1",
           "status": status, "confidence": confidence, "reason": "test fixture", "evidence": "test fixture",
           "residual_risk": "none", "created_by": "test", "accepted_by": "test", "updated_at": report_date}


def _mini_doc(cik, date, *, delim=" | ", rows=4):
    """Like tests.test_profile_pilot_profile.mini_doc, but parameterised by cik (that module's own
    helper hard-codes CIK = STELLUS at module scope, including inside the dei:EntityCentralIndexKey fact
    profile.derive_profile cross-checks against `source["cik"]` -- it cannot be reused for any other
    pilot filer). Only what derive_profile reads."""
    identifiers = ["Borrower %d LLC%sTerm Loan" % (i, delim) for i in range(rows)]
    contexts, positions = [], []
    for i, ident in enumerate(identifiers):
        cid = "p%d" % i
        typed = [dict(axis=IDENT, value=ident)]
        contexts.append(dict(id=cid, period=dict(kind="instant", instant=date), dimensions=[],
                             typed_dimensions=typed, entity=dict(identifier=cik), role="confirmed_position"))
        positions.append(dict(observation_id="obs:" + cid, context_id=cid,
                              period=dict(kind="instant", instant=date),
                              identity=dict(typed_identifier=ident, dimensions=[], typed_dimensions=typed),
                              dimension_fields={},
                              fields={"fair_value": dict(status="reported", value="100",
                                                         concepts=["us-gaap:InvestmentOwnedAtFairValue"],
                                                         provenance="inherited",
                                                         inherited_from="pipeline/bdc_filings.py:CONCEPT_MAP")},
                              provenance="inherited",
                              inherited_from="pipeline/context_inventory.py:classify_context"))
    channels = {name: dict(state="complete") for name in
               ("contexts", "identifiers", "numeric_facts", "text_facts", "units")}
    channels["footnotes"] = dict(state="complete")
    return dict(
        document=dict(cik=cik, report_date=date, accession_number="0000000000-23-000001",
                      form_type="10-Q", role="q1"),
        document_metadata=dict(document_period_end_dates=[date]),
        channels=channels, contexts=contexts, positions=positions, periods=[],
        facts=[dict(i=0, qname="dei:EntityCentralIndexKey", field="entity_cik", context_id="dei",
                    status="reported", value=cik, provenance="derived", inherited_from=None)],
        fund_income=[], fund_balance=[], dependencies=[dict(name="concept_map")],
        detectors=dict(partition=detector([single_dialect(delim)]), subtotal=detector([]),
                       alternate_view=detector([]), non_disclosure=detector([])))


def _census_for(cik, date, *, delim=" | "):
    doc = _mini_doc(cik, date, delim=delim)
    source = dict(cik=cik, report_date=date, role="all:" + date,
                  census_relative="census/" + cik + "/" + date + ".json", census_sha256="0" * 64,
                  fingerprint="f" * 64, accession_number="0000000000-23-000001", form_type="10-Q")
    return dict(doc=doc, source=source)


def _git(main_root, *args):
    subprocess.run(["git", *args], cwd=main_root, check=True, capture_output=True)


def _git_init_and_commit(main_root):
    """F7: overrides_git_head/_dirty need a REAL git checkout; build_fake_main's fake main root is a
    plain directory tree. Scoped to this test module's own fixture only -- the shared helper other pilot
    stage tests use stays a non-git root."""
    _git(main_root, "init", "-q")
    _git(main_root, "config", "user.email", "test@example.com")
    _git(main_root, "config", "user.name", "test")
    _git(main_root, "add", "-A")
    _git(main_root, "commit", "-q", "-m", "seed")


def _authoritative_rows(cik, census_root, *, delim=" | "):
    rows = []
    for date, role in ((Q4, "all:" + Q4), (Q1, "verified_era")):
        rel = "census/" + cik + "/" + date + ".json"
        path = census_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        body = dict(complete=True, identity=dict(fingerprint="f" * 64), result=_census_for(cik, date, delim=delim)["doc"])
        path.write_text(json.dumps(body), encoding="ascii")
        rows.append(dict(cik=cik, role=role, report_date=date, census_relative=rel,
                         census_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), fingerprint="f" * 64,
                         validation_verdict="pass"))
    return rows


def _write_replay(paths):
    replay = paths.data_root / "pilot" / "filer_profile" / REPLAY_RUN / "results"
    replay.mkdir(parents=True, exist_ok=True)
    floors = {"fill_rate": dict(verdict="NO_POSITIVES"), "independent_totals": dict(verdict="FAIL")}
    (replay / "replay_q4_q1.json").write_text(json.dumps(dict(floors=floors)), encoding="ascii")


def seed(paths):
    """The single-filer (STELLUS) fixture used by most tests. F11: extended beyond wrapper + rate_convention
    + the shared oracle-exceptions file to also carry a B2 correction, an investigate-rules directory
    (unpadded CIK directory name, as it is on disk in main), an identifier_anchors file and an
    identifier_rate_grammars file."""
    data = paths.data_root
    unpadded = str(int(STELLUS))
    write_tree(data / "overrides", {
        "bdc_xbrl_wrappers/" + STELLUS + ".json": wrapper_v3(STELLUS),
        "rate_convention/" + STELLUS + ".json": {"cik": STELLUS, "convention": "all_in", "target_quarter": Q1},
        "bdc_xbrl_oracle_exceptions.json": [
            oracle_record("0001111111", "2024-12-31", "x", status="proposed", confidence=0.5),
            oracle_record(STELLUS, Q4, "rate_outliers_detected")],
        "agent_b2_corrections/" + STELLUS + "/comparative_period_filter.json":
            {"cik": STELLUS, "mechanism": "comparative_leak", "fix_class": "comparative_period_filter",
             "template": {"report_date": Q4}},
        "agent_investigate_rules/" + unpadded + "/fix1.json":
            {"cik": unpadded, "rule_id": "fix1", "rule_type": "row_add", "scope": {"quarters": [Q4]}},
        "identifier_anchors/" + STELLUS + ".json": {"anchors": [{"label": "secured", "regex": "secured"}]},
        "identifier_rate_grammars/" + STELLUS + ".json": {"cik": STELLUS, "dialect": "pipe_delimited"}})
    root = data / "pilot" / "filer_profile" / CENSUS_RUN
    rows = _authoritative_rows(STELLUS, root)
    (root / "results").mkdir(parents=True)
    (root / "results" / "authoritative.json").write_text(json.dumps(dict(fund_quarters=rows)), encoding="ascii")
    (root / "results" / "excluded.json").write_text(json.dumps(dict(fund_quarters=[])), encoding="ascii")
    _write_replay(paths)
    _git_init_and_commit(paths.main_repo_root)


def seed_cohort(paths):
    """F6: a full 8-filer fixture that reaches exit-test PASS -- every pilot CIK gets a matching wrapper,
    rate_convention and Q4/Q1 census (no breach-prone extras; F11's richer STELLUS-only fixture is not
    reused here to keep this fixture's correctness easy to reason about)."""
    from scripts.profile_pilot import census_published, cohort
    data = paths.data_root
    files = {}
    root = data / "pilot" / "filer_profile" / CENSUS_RUN
    rows = []
    for cik in cohort.PILOT_CIKS:
        extra = {}
        if cik in census_published.REPORTING_ENTITIES:
            # BCRED: without this, the wrapper carries no source_encodings.reporting_entity_suffixes, so
            # no partition_structure.reporting_entities entry exists and the code-mirror check in
            # consistency_contract breaches against census_published.REPORTING_ENTITIES.
            extra = dict(source_encodings=dict(
                reporting_entity_suffixes=list(census_published.REPORTING_ENTITIES[cik])))
        files["bdc_xbrl_wrappers/" + cik + ".json"] = wrapper_v3(cik, **extra)
        files["rate_convention/" + cik + ".json"] = {"cik": cik, "convention": "all_in", "target_quarter": Q1}
        rows += _authoritative_rows(cik, root)
    write_tree(data / "overrides", files)
    (root / "results").mkdir(parents=True)
    (root / "results" / "authoritative.json").write_text(json.dumps(dict(fund_quarters=rows)), encoding="ascii")
    (root / "results" / "excluded.json").write_text(json.dumps(dict(fund_quarters=[])), encoding="ascii")
    _write_replay(paths)
    _git_init_and_commit(paths.main_repo_root)


@pytest.fixture
def staged(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="sp3p-profile-test")
    seed(paths)
    monkeypatch.setattr(run, "attested_under", lambda main_root, rel, content: [])
    return paths


def build(paths, *, ciks=(STELLUS,)):
    return run.run_stage(paths, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN, ciks=list(ciks), recorded_at=AT)


# ---------------------------------------------------------------- brief's original tests (carried forward)


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


# ---------------------------------------------------------------- F1: honest workload, lease on heavy


def test_workload_record_uses_the_real_classifier_and_is_light_for_the_small_fixture(staged):
    """Not stubbed: the real manifest.classify_workload runs over the fixture's real (small) file sizes."""
    build(staged)
    body = json.loads((staged.run_root / "manifest.json").read_text(encoding="ascii"))
    workload = body["workload"]
    assert set(workload) == set(run.manifest.WORKLOAD_FIELDS)
    assert workload["ciks"] == [STELLUS] and workload["instance_count"] == 0 and workload["pipeline_cik_count"] == 0
    assert workload["est_bytes"] >= 300_000_000   # the 300e6 base alone, from write_profile's own formula
    assert body["heavy"] is False


def test_heavy_workload_without_a_lease_factory_is_refused(staged, monkeypatch):
    monkeypatch.setattr(run.manifest, "classify_workload", lambda workload: True)
    with pytest.raises(run.LeaseRefused):
        build(staged)
    assert not (staged.run_root / "manifest.json").is_file()   # refused before the first write


def test_main_reports_refused_exit_code_when_the_lease_itself_refuses(staged, monkeypatch):
    """main() now ALWAYS wires a real lease_factory (F1: 'run under the lease', not 'refuse when heavy').
    Forcing the real shared_heavy_lease adapter to refuse (rather than relying on this machine's actual
    process list, which is shared with other agents and not deterministic -- confirmed while developing
    this fix round, another session's pytest run was visible) is what deterministically exercises main()'s
    LeaseRefused -> EXIT_REFUSED mapping."""
    monkeypatch.setattr(run.manifest, "classify_workload", lambda workload: True)

    def refusing(paths_, *, head):
        raise run.LeaseRefused("synthetic: another heavy job holds the lease")

    monkeypatch.setattr(run.protection, "shared_heavy_lease", refusing)
    assert run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", staged.run_id, "--census-run-id", CENSUS_RUN, "--replay-run-id", REPLAY_RUN,
                     "--cik", STELLUS]) == run.EXIT_REFUSED


def test_heavy_workload_with_a_lease_factory_runs_under_the_real_lease(staged, monkeypatch):
    """F1: 'do not restructure to sequential loads' -- when heavy, the existing per-cik build loop runs
    unchanged, just inside the shared lease (profile_run's/census_run's own pattern), using the REAL
    shared_heavy_lease adapter (not a fake lease object)."""
    import os
    import psutil
    from scripts.profile_pilot import protection

    class Self:
        pid = os.getpid()
        info = dict(pid=os.getpid(), name="python.exe", cmdline=["python", "-m", "pytest"])

    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([Self()]))
    monkeypatch.setattr(run.manifest, "classify_workload", lambda workload: True)

    def lease_factory():
        return protection.shared_heavy_lease(staged, head="test")

    summary = run.run_stage(staged, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN, ciks=[STELLUS],
                            recorded_at=AT, lease_factory=lease_factory)
    assert summary["verdict"] == "FAIL"   # one filer of 8 -- same business outcome as the light path
    body = json.loads((staged.run_root / "manifest.json").read_text(encoding="ascii"))
    assert body["heavy"] is True


# ---------------------------------------------------------------- F2: validate before any verdict file


def test_pin_change_detected_before_any_verdict_file_is_written(staged, monkeypatch):
    monkeypatch.setattr(run.manifest, "verify_inputs",
                        lambda manifest: dict(ok=False, changed=["x"], missing=[], appeared=[], checked=1))
    with pytest.raises(run.StageInvalidated):
        build(staged)
    rr = staged.run_root
    assert not (rr / "results" / "exit_test.json").is_file()
    assert not (rr / "results" / "roundtrip.json").is_file()
    assert not (rr / "results" / "consistency.json").is_file()
    assert (rr / "manifest.json").is_file()   # the input ledger itself is not a verdict file


# ---------------------------------------------------------------- F3: exit codes


def test_main_reports_exit_2_for_a_preservation_failure(staged, monkeypatch, capsys):
    original = run.pf.collect_override_inputs

    def spy(root, cik, hits):
        out = original(root, cik, hits)
        if cik == STELLUS:
            (Path(root) / "rate_convention" / (STELLUS + ".json")).unlink()
        return out

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix1-preservation", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED
    out = capsys.readouterr().out
    assert "PRESERVATION FAILED" in out and "Traceback" not in out
    out.encode("ascii")


def test_main_reports_exit_3_for_an_unexpected_exception(staged, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("synthetic failure not in any mapped exception class")

    monkeypatch.setattr(run.profile_consistency, "exit_test", boom)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", staged.run_id, "--census-run-id", CENSUS_RUN, "--replay-run-id", REPLAY_RUN,
                     "--cik", STELLUS])
    assert code == run.EXIT_UNEXPECTED == 3
    out = capsys.readouterr().out
    assert "UNEXPECTED ERROR" in out and "RuntimeError" in out and "Traceback" not in out
    out.encode("ascii")


# ---------------------------------------------------------------- F4: per-family loader-parity tally


def test_loader_parity_tally_flags_a_family_with_fewer_compared_than_expected():
    parity = dict(bdc_xbrl_wrappers={"0001111111": "match"})   # only one of two expected ciks compared
    expected = ["bdc_xbrl_wrappers/0001111111.json", "bdc_xbrl_wrappers/0002222222.json"]
    tally, problems = run._loader_parity_tally(parity, expected)
    assert tally["bdc_xbrl_wrappers"] == dict(expected=2, compared=1)
    assert problems and "bdc_xbrl_wrappers" in problems[0]


def test_loader_parity_tally_includes_the_pooled_b2_compared_count():
    parity = dict(agent_b2_corrections=dict(status="match", compared=2))
    expected = ["agent_b2_corrections/0001901037/a.json", "agent_b2_corrections/0001901037/b.json"]
    tally, problems = run._loader_parity_tally(parity, expected)
    assert tally["agent_b2_corrections"] == dict(expected=2, compared=2)
    assert not problems


def test_real_build_loader_parity_tally_matches_the_filesystem(staged):
    """Integration companion: the real build's own tally (now including B2/rules/anchors/grammars from
    the F11-extended fixture) finds no shortfall."""
    build(staged)
    roundtrip = json.loads((staged.run_root / "results" / "roundtrip.json").read_text(encoding="ascii"))
    tally = roundtrip["loader_parity_tally"]
    for key, counts in tally.items():
        assert counts["compared"] == counts["expected"], (key, counts)


# ---------------------------------------------------------------- F5: verdict word + insufficient_evidence


def test_consistency_verdict_and_insufficient_evidence_are_published_outside_consistency_json(staged):
    build(staged)
    rr = staged.run_root
    exit_body = json.loads((rr / "results" / "exit_test.json").read_text(encoding="ascii"))
    row = exit_body["per_cik"][STELLUS]
    assert row["consistency_verdict"] in ("holds", "no_breach", "breach")
    assert isinstance(row["insufficient_evidence"], int) and row["insufficient_evidence"] >= 0


# ---------------------------------------------------------------- F6: failure-path coverage


def test_a_dropped_conversion_shows_missing_and_fails(staged, monkeypatch):
    original = run.rt.load_and_materialise
    dropped_rel = "rate_convention/" + STELLUS + ".json"

    def dropping(paths_, *, shared_originals):
        out = original(paths_, shared_originals=shared_originals)
        out.pop(dropped_rel, None)
        return out

    monkeypatch.setattr(run.rt, "load_and_materialise", dropping)
    summary = build(staged)
    rr = staged.run_root
    roundtrip = json.loads((rr / "results" / "roundtrip.json").read_text(encoding="ascii"))
    assert roundtrip["files"][dropped_rel] == "missing"
    assert roundtrip["ok"] is False
    assert summary["verdict"] == "FAIL"


def test_converted_disposition_without_a_hash_exits_2_via_inceptionerror(staged, monkeypatch):
    original = run.pf.collect_override_inputs

    def tampered(root, cik, hits):
        out = original(root, cik, hits)
        for d in out["disposition"]:
            if d["action"] == "wrapper_block":
                d["ordered_sha256"] = None
        return out

    monkeypatch.setattr(run.pf, "collect_override_inputs", tampered)
    with pytest.raises(run.pi.InceptionError):
        build(staged)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix1-inception", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED


def test_roundtriperror_from_loader_parity_tally_exits_2(staged, monkeypatch):
    original = run.rt.loader_parity

    def forcing_absent(root_, materialised_root_, ciks_):
        out = original(root_, materialised_root_, ciks_)
        out["rate_convention"] = {c: "absent" for c in out["rate_convention"]}
        return out

    monkeypatch.setattr(run.rt, "loader_parity", forcing_absent)
    with pytest.raises(run.rt.RoundTripError):
        build(staged)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix1-roundtrip", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED


def test_profiledocumenterror_on_reload_exits_2(staged, monkeypatch):
    original = run.translate._write_once_ordered

    def corrupting(paths_, relative, value):
        if relative.startswith("profiles/"):
            value = dict(value)
            del value["stubs"]
        return original(paths_, relative, value)

    monkeypatch.setattr(run.translate, "_write_once_ordered", corrupting)
    with pytest.raises(run.pd.ProfileDocumentError):
        build(staged)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix1-proddoc", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED


def test_census_q4_unavailable_branch_is_exercised_through_the_cli(staged):
    excluded_path = staged.data_root / "pilot" / "filer_profile" / CENSUS_RUN / "results" / "excluded.json"
    excluded_path.write_text(json.dumps(dict(fund_quarters=[
        dict(cik=ARES, report_date=Q4, reason="ambiguous_same_quarter_candidates",
            detail="two original filings")])), encoding="ascii")
    summary = run.run_stage(staged, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN, ciks=[ARES],
                            recorded_at=AT)
    doc = pd.load_document(staged.run_root / "profiles" / (ARES + ".json"))
    assert doc["ledger"][0]["detail"]["census_q4_unavailable"]["reason"] == "ambiguous_same_quarter_candidates"
    assert any(s["cause"] == "census_unavailable" for s in doc["stubs"])
    assert summary["per_cik"][ARES]["q1_census"] == "absent"


def test_main_runs_to_completion_on_a_fail_fixture(staged):
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix1-fail", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--cik", STELLUS])
    assert code == run.EXIT_FAIL


def test_main_runs_to_completion_on_a_pass_fixture(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="sp3p-profile-fix1-pass")
    seed_cohort(paths)
    monkeypatch.setattr(run, "attested_under", lambda main_root, rel, content: [])
    code = run.main(["build", "--data-root", str(paths.data_root), "--main-root", str(paths.main_repo_root),
                     "--run-id", paths.run_id, "--census-run-id", CENSUS_RUN, "--replay-run-id", REPLAY_RUN])
    exit_body = json.loads((paths.run_root / "results" / "exit_test.json").read_text(encoding="ascii"))
    assert exit_body["verdict"] == "PASS", exit_body
    assert code == 0


# ---------------------------------------------------------------- F7: overrides_git_head / overrides_dirty


def test_overrides_git_head_and_dirty_are_recorded_for_a_clean_checkout(staged):
    build(staged)
    body = json.loads((staged.run_root / "manifest.json").read_text(encoding="ascii"))
    assert isinstance(body["overrides_git_head"], str) and len(body["overrides_git_head"]) == 40
    assert body["overrides_dirty"] is False


def test_overrides_dirty_is_true_when_main_overrides_has_uncommitted_changes(staged):
    (staged.main_repo_root / "data" / "overrides" / "zz_untracked_marker.json").write_text(
        "{}", encoding="ascii")
    build(staged)
    body = json.loads((staged.run_root / "manifest.json").read_text(encoding="ascii"))
    assert body["overrides_dirty"] is True


def test_overrides_git_head_failure_is_a_refusal(staged, monkeypatch):
    original = run.manifest.git

    def failing(code_root, *args, **kwargs):
        if tuple(args[:2]) == ("rev-parse", "HEAD") and Path(code_root) == staged.main_repo_root:
            return subprocess.CompletedProcess(args, 128, b"", b"fatal: forced failure")
        return original(code_root, *args, **kwargs)

    monkeypatch.setattr(run.manifest, "git", failing)
    with pytest.raises(run.StageInvalidated):
        build(staged)


# ---------------------------------------------------------------- F8: MAIN overrides open-guard + inventory


def test_main_overrides_open_guard_blocks_a_write_immediately(staged, monkeypatch):
    original = run.pf.collect_override_inputs

    def spy(root, cik, hits):
        if cik == STELLUS:
            (Path(root) / "sp3p_t9_blocked_write.json").write_text("{}", encoding="ascii")
        return original(root, cik, hits)

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    with pytest.raises(AssertionError, match="profile pilot blocked a write"):
        build(staged)


def test_main_overrides_deletion_bypassing_open_is_caught_by_inventory(staged, monkeypatch):
    original = run.pf.collect_override_inputs

    def spy(root, cik, hits):
        out = original(root, cik, hits)
        if cik == STELLUS:
            (Path(root) / "rate_convention" / (STELLUS + ".json")).unlink()
        return out

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    with pytest.raises(run.PreservationError):
        build(staged)


def test_main_overrides_guard_receipt_records_a_clean_comparison(staged):
    build(staged)
    body = json.loads((staged.run_root / run.GUARD_RECEIPT_RELATIVE).read_text(encoding="ascii"))
    assert body["comparison"]["ok"] is True and body["verdict"] == "PASS"


# ---------------------------------------------------------------- F9: q1_census present/absent; Q4 ambiguity


def test_q1_census_present_is_published_per_filer(staged):
    summary = build(staged)
    assert summary["per_cik"][STELLUS]["q1_census"] == "present"
    exit_body = json.loads((staged.run_root / "results" / "exit_test.json").read_text(encoding="ascii"))
    assert exit_body["per_cik"][STELLUS]["q1_census"] == "present"


def test_select_census_row_refuses_more_than_one_match_for_a_report_date():
    fake_census = dict(rows={
        (STELLUS, "all:" + Q4): dict(report_date=Q4, census_relative="a"),
        (STELLUS, "verified_era"): dict(report_date=Q4, census_relative="b")})   # anomalous: misdated
    with pytest.raises(run.StageInvalidated, match="more than one"):
        run._select_census_row(fake_census, STELLUS, report_date=Q4)


# ---------------------------------------------------------------- F10: CENSUS_ROLES no longer admits q1/q2


def test_census_roles_does_not_admit_q1_or_q2():
    assert "q1" not in run.CENSUS_ROLES and "q2" not in run.CENSUS_ROLES
    assert run.CENSUS_ROLES == ("verified_era", "all:" + Q4)


# ---------------------------------------------------------------- M2: subset-run shared-file mention only


def test_subset_run_shared_mention_without_an_owned_record_is_not_a_false_missing(staged):
    (staged.main_repo_root / "data" / "overrides" / "bdc_aggregate_row_overrides.json").write_text(
        json.dumps({"overrides": [{"cik": "0001287750", "report_date": "2025-09-30",
                                   "match_text": "mentions 1901037 only in text"}]}), encoding="ascii")
    build(staged)
    roundtrip = json.loads((staged.run_root / "results" / "roundtrip.json").read_text(encoding="ascii"))
    assert "bdc_aggregate_row_overrides.json" not in roundtrip["files"]
    assert roundtrip["ok"] is True


# ---------------------------------------------------------------- M1 (companion kept as a real assertion above)
