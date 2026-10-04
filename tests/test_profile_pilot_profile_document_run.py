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
from tests.test_profile_pilot_profile_inception import Q1, Q4, census, totals_results

CENSUS_RUN, REPLAY_RUN, AT = "stageb2-fakecensus", "sp1-replay-fake", "2026-10-01T12:00:00Z"
TOTALS_RUN = "stageb2-backtest-fake"
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


def _totals_path(paths):
    return paths.data_root / "pilot" / "filer_profile" / TOTALS_RUN / "results" / "backtest_results.json"


def _write_totals(paths, outcomes, residuals=None):
    """Final review I3: the pinned independent-totals results (m2_backtest's backtest_results.json shape).
    `outcomes` maps cik -> a fair_value status, a {mode: status} dict, or None for 'no pair evaluated at the
    inception date' (the NexPoint / TCW shape). `residuals` (owner ruling 2) maps cik -> fair-value residual
    in percent (a number or a {mode: number} dict); default as in totals_results."""
    results = {}
    for cik, fair_value in outcomes.items():
        if fair_value is not None:
            results.update(totals_results(cik, fair_value, residual=(residuals or {}).get(cik)))
    path = _totals_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(note="test fixture", results=results, yields={})), encoding="ascii")


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
    _write_totals(paths, {STELLUS: "holds"})
    _git_init_and_commit(paths.main_repo_root)


NO_Q4_CENSUS = "0001588272"   # NexPoint: no authoritative Q4-2025 census in the run of record


def seed_cohort(paths, *, no_q4_census=(), totals=None, totals_residuals=None):
    """F6: a full 8-filer fixture that reaches exit-test PASS -- every pilot CIK gets a matching wrapper,
    rate_convention and Q4/Q1 census (no breach-prone extras; F11's richer STELLUS-only fixture is not
    reused here to keep this fixture's correctness easy to reason about).

    Final review I4: that all-compared shape never occurs in the real data. `no_q4_census` names filers in
    the REAL shape (NexPoint / TCW): no authoritative Q4 census, listed as excluded, so no census-derived
    entry exists and nothing in their wrapper can be compared. `totals` overrides the per-filer pinned
    independent-totals outcome (default: holds where a Q4 census exists, no pair at all where it does not)."""
    from scripts.profile_pilot import census_published, cohort
    data = paths.data_root
    files = {}
    root = data / "pilot" / "filer_profile" / CENSUS_RUN
    rows = []
    excluded = []
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
        mine = _authoritative_rows(cik, root)
        if cik in no_q4_census:
            mine = [r for r in mine if r["report_date"] != Q4]
            excluded.append(dict(cik=cik, report_date=Q4, reason="ambiguous_same_quarter_candidates",
                                 detail="two original filings"))
        rows += mine
    write_tree(data / "overrides", files)
    (root / "results").mkdir(parents=True)
    (root / "results" / "authoritative.json").write_text(json.dumps(dict(fund_quarters=rows)), encoding="ascii")
    (root / "results" / "excluded.json").write_text(json.dumps(dict(fund_quarters=excluded)), encoding="ascii")
    _write_replay(paths)
    outcomes = {cik: (None if cik in no_q4_census else "holds") for cik in cohort.PILOT_CIKS}
    outcomes.update(totals or {})
    _write_totals(paths, outcomes, totals_residuals)
    _git_init_and_commit(paths.main_repo_root)


@pytest.fixture
def staged(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="sp3p-profile-test")
    seed(paths)
    monkeypatch.setattr(run, "attested_under", lambda main_root, rel, content: [])
    return paths


def build(paths, *, ciks=(STELLUS,)):
    return run.run_stage(paths, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN,
                         totals_run_id=TOTALS_RUN, ciks=list(ciks), recorded_at=AT)


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
        run.run_stage(paths, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN, totals_run_id=TOTALS_RUN)
    assert run.main(["build", "--data-root", str(paths.data_root), "--main-root", str(paths.main_repo_root),
                     "--run-id", "stageb-profile-x", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN]) == run.EXIT_REFUSED


def test_no_production_module_reads_profile_documents():
    for path in (CODE_ROOT / "pipeline").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ("data/profiles", "profile_document", "profile_inception"):
            assert needle not in text, (str(path), needle)


# ---------------------------------------------------------------- F1: honest workload, lease on heavy


def test_workload_record_uses_the_real_classifier_and_is_light_for_the_small_fixture(staged):
    """Not stubbed: the real manifest.classify_workload runs over the fixture's real (small) file sizes.
    Fix round 2 (R4): pin the EXACT expected est_bytes from the fixture's own Q4+Q1 census file sizes
    (the formula under test), not a floor that would pass even if the per-filer sum were wrong."""
    census_dir = staged.data_root / "pilot" / "filer_profile" / CENSUS_RUN / "census" / STELLUS
    census_bytes = (census_dir / (Q4 + ".json")).stat().st_size + (census_dir / (Q1 + ".json")).stat().st_size
    expected_est_bytes = int(300e6 + 20 * census_bytes)
    build(staged)
    body = json.loads((staged.run_root / "manifest.json").read_text(encoding="ascii"))
    workload = body["workload"]
    assert set(workload) == set(run.manifest.WORKLOAD_FIELDS)
    assert workload["ciks"] == [STELLUS] and workload["instance_count"] == 0 and workload["pipeline_cik_count"] == 0
    assert workload["est_bytes"] == expected_est_bytes
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
                     "--totals-run-id", TOTALS_RUN,
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

    summary = run.run_stage(staged, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN,
                            totals_run_id=TOTALS_RUN, ciks=[STELLUS],
                            recorded_at=AT, lease_factory=lease_factory)
    assert summary["verdict"] == "FAIL"   # one filer of 8 -- same business outcome as the light path
    body = json.loads((staged.run_root / "manifest.json").read_text(encoding="ascii"))
    assert body["heavy"] is True
    # R4 (fix round 2): prove the lease was actually RELEASED, not just that the build completed --
    # a second, independent acquisition succeeding proves the module-level _PROCESS_LEASE lock and the
    # pseudo-candidate were both cleaned up by the first `with lease_factory() as lease: ...` block.
    with protection.shared_heavy_lease(staged, head="test-again") as lease2:
        protection.assert_lease_held(lease2)


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
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
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
                     "--totals-run-id", TOTALS_RUN,
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


def test_loader_parity_tally_flags_a_shortfall_in_the_pooled_b2_compared_count():
    """R4 (fix round 2): a FAILING pooled agent_b2_corrections case, companion to the passing one above."""
    parity = dict(agent_b2_corrections=dict(status="mismatch", compared=1))
    expected = ["agent_b2_corrections/0001901037/a.json", "agent_b2_corrections/0001901037/b.json"]
    tally, problems = run._loader_parity_tally(parity, expected)
    assert tally["agent_b2_corrections"] == dict(expected=2, compared=1)
    assert problems and "agent_b2_corrections" in problems[0]


EXPECTED_LOADER_PARITY_FAMILIES = {"bdc_xbrl_wrappers", "agent_investigate_rules", "rate_convention",
                                   "identifier_anchors", "identifier_rate_grammars", "agent_b2_corrections",
                                   "bdc_xbrl_oracle_exceptions"}


def test_real_build_loader_parity_tally_matches_the_filesystem(staged):
    """Integration companion: the real build's own tally (now including B2/rules/anchors/grammars from
    the F11-extended fixture) covers all seven tallied families (fix round 2, R4) and finds no shortfall
    in any of them."""
    build(staged)
    roundtrip = json.loads((staged.run_root / "results" / "roundtrip.json").read_text(encoding="ascii"))
    tally = roundtrip["loader_parity_tally"]
    assert set(tally) == EXPECTED_LOADER_PARITY_FAMILIES
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
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
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
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
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
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED


def test_census_q4_unavailable_branch_is_exercised_through_the_cli(staged):
    excluded_path = staged.data_root / "pilot" / "filer_profile" / CENSUS_RUN / "results" / "excluded.json"
    excluded_path.write_text(json.dumps(dict(fund_quarters=[
        dict(cik=ARES, report_date=Q4, reason="ambiguous_same_quarter_candidates",
            detail="two original filings")])), encoding="ascii")
    summary = run.run_stage(staged, census_run_id=CENSUS_RUN, replay_run_id=REPLAY_RUN,
                            totals_run_id=TOTALS_RUN, ciks=[ARES],
                            recorded_at=AT)
    doc = pd.load_document(staged.run_root / "profiles" / (ARES + ".json"))
    assert doc["ledger"][0]["detail"]["census_q4_unavailable"]["reason"] == "ambiguous_same_quarter_candidates"
    assert any(s["cause"] == "census_unavailable" for s in doc["stubs"])
    assert summary["per_cik"][ARES]["q1_census"] == "absent"


def test_main_runs_to_completion_on_a_fail_fixture(staged):
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix1-fail", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
    assert code == run.EXIT_FAIL


def test_main_runs_to_completion_on_a_pass_fixture(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="sp3p-profile-fix1-pass")
    seed_cohort(paths)
    monkeypatch.setattr(run, "attested_under", lambda main_root, rel, content: [])
    code = run.main(["build", "--data-root", str(paths.data_root), "--main-root", str(paths.main_repo_root),
                     "--run-id", paths.run_id, "--census-run-id", CENSUS_RUN, "--replay-run-id", REPLAY_RUN,
                     "--totals-run-id", TOTALS_RUN])
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
    """Fix round 3 (R2): run_stage itself now converts the open-guard's bare AssertionError to
    PreservationError (matching its exact message prefix) before it ever leaves run_stage -- this test
    originally (fix round 1, F8) asserted the raw AssertionError; updated to match the new, narrower
    conversion. The guard still blocks the write itself (the write never completes either way)."""
    original = run.pf.collect_override_inputs

    def spy(root, cik, hits):
        if cik == STELLUS:
            (Path(root) / "sp3p_t9_blocked_write.json").write_text("{}", encoding="ascii")
        return original(root, cik, hits)

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    with pytest.raises(run.PreservationError, match="profile pilot blocked a write"):
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


# ---------------------------------------------------------------- Fix round 2 (re-review of 8919347)

# ---------------------------------------------------------------- R1: no PASS verdict on disk after exit 2


def test_create_bypassing_open_mid_run_leaves_no_verdict_file_and_exits_2(staged, monkeypatch):
    """R1: Path.touch() uses os.open, not io.open/builtins.open, so it bypasses the open-guard entirely
    (F8's companion test, test_main_overrides_open_guard_blocks_a_write_immediately, only proves an
    open()-based write is blocked). The pre-write guard comparison (not the one in `finally`, which runs
    after results/exit_test.json would already exist) is what must catch this."""
    original = run.pf.collect_override_inputs

    def spy(root, cik, hits):
        if cik == STELLUS:
            (Path(root) / "sp3p_t9fix2_bypassed_create.json").touch()
        return original(root, cik, hits)

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    run_id = "sp3p-profile-fix2-r1-create"
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", run_id, "--census-run-id", CENSUS_RUN, "--replay-run-id", REPLAY_RUN,
                     "--totals-run-id", TOTALS_RUN,
                     "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED
    run_root = staged.data_root / "pilot" / "filer_profile" / run_id
    assert not (run_root / "results" / "exit_test.json").is_file()
    assert not (run_root / "results" / "roundtrip.json").is_file()
    assert not (run_root / "results" / "consistency.json").is_file()
    # manifest.json is an input ledger, not a verdict file, and is written before the per-cik loop runs
    assert (run_root / "manifest.json").is_file()


def test_pre_write_guard_check_fires_even_when_pins_still_verify_ok(staged, monkeypatch):
    """Isolates R1's new pre-write guard comparison from F2's pin re-verify (manifest.verify_inputs only
    tracks files that were already PINNED; a brand-new file is invisible to it). Stubs verify_inputs to
    always report ok=True, so if the pre-write guard comparison did not exist, the run would proceed to
    write verdict files; it must not."""
    monkeypatch.setattr(run.manifest, "verify_inputs",
                        lambda manifest: dict(ok=True, changed=[], missing=[], appeared=[], checked=0))
    original = run.pf.collect_override_inputs

    def spy(root, cik, hits):
        if cik == STELLUS:
            (Path(root) / "sp3p_t9fix2_unpinned_new_file.json").touch()
        return original(root, cik, hits)

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    with pytest.raises(run.PreservationError):
        build(staged)
    rr = staged.run_root
    assert not (rr / "results" / "exit_test.json").is_file()
    assert not (rr / "results" / "roundtrip.json").is_file()
    assert not (rr / "results" / "consistency.json").is_file()


# ---------------------------------------------------------------- R2: guard-block / vanished-pin -> exit 2


def test_main_overrides_open_guard_block_exits_2_not_3(staged, monkeypatch):
    original = run.pf.collect_override_inputs

    def spy(root, cik, hits):
        if cik == STELLUS:
            (Path(root) / "sp3p_t9fix2_blocked_write.json").write_text("{}", encoding="ascii")
        return original(root, cik, hits)

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix2-r2-guard", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED


def test_vanishing_pinned_census_file_mid_build_exits_2_not_3(staged, monkeypatch):
    """A pinned input OUTSIDE the MAIN-overrides guard (the census file, under data/pilot/filer_profile/,
    not data/overrides/) vanishing mid-build raises a raw FileNotFoundError that nothing else catches --
    before this fix it fell through to the generic `except Exception` (exit 3)."""
    original = run.pf.collect_override_inputs
    census_path = (staged.data_root / "pilot" / "filer_profile" / CENSUS_RUN / "census" / STELLUS
                  / (Q4 + ".json"))

    def spy(root, cik, hits):
        out = original(root, cik, hits)
        if cik == STELLUS:
            census_path.unlink()
        return out

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix2-r2-pin", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED


# ---------------------------------------------------------------- M1 (companion kept as a real assertion above)


# ---------------------------------------------------------------- Fix round 3 (re-review of dd176ff)
# Narrows fix round 2's R2 (a blanket `except (AssertionError, OSError)` in main()) to convert only the
# two intended mechanisms, AT THEIR OWN SITE inside run_stage, into PreservationError/StageInvalidated.
# main() no longer has any AssertionError/OSError clause at all.


def test_oserror_on_a_verdict_write_exits_3_not_2(staged, monkeypatch):
    """A disk-full/permission OSError on one of the three FINAL results/*.json writes is a genuinely
    unexpected failure, not a pinned-input or guard-blocked-write condition -- it must exit 3."""
    original = run.write_once_json

    def failing(paths_, relative, value):
        if relative == "results/roundtrip.json":
            raise OSError("synthetic: disk full")
        return original(paths_, relative, value)

    monkeypatch.setattr(run, "write_once_json", failing)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix3-verdict-write", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
    assert code == run.EXIT_UNEXPECTED == 3


def test_missing_git_executable_resolving_overrides_head_stays_exit_2(staged, monkeypatch):
    """A missing git EXECUTABLE raises OSError (FileNotFoundError) from subprocess.run itself, before
    any CompletedProcess exists for the existing `done.returncode != 0` check to see -- distinct from
    test_overrides_git_head_failure_is_a_refusal (fix round 1), which simulates git running and failing.
    F7's original intent (a git failure resolving the MAIN checkout's overrides state is a refusal) must
    hold for this case too."""
    original = run.manifest.git

    def missing_git(code_root, *args, **kwargs):
        if tuple(args[:2]) == ("rev-parse", "HEAD") and Path(code_root) == staged.main_repo_root:
            raise FileNotFoundError(2, "No such file or directory: 'git'")
        return original(code_root, *args, **kwargs)

    monkeypatch.setattr(run.manifest, "git", missing_git)
    with pytest.raises(run.StageInvalidated):
        build(staged)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix3-missing-git", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
    assert code == run.EXIT_INVALIDATED


def test_bare_assertionerror_from_elsewhere_exits_3_not_2(staged, monkeypatch):
    """A bare AssertionError that does NOT match the open-guard's own message is unrelated and must not
    be swept into exit 2 -- it is exactly the kind of future/unrelated `assert` the narrowing guards
    against."""
    def boom(*a, **k):
        raise AssertionError("unrelated assertion, nothing to do with the overrides guard")

    monkeypatch.setattr(run.profile_consistency, "exit_test", boom)
    code = run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", "sp3p-profile-fix3-bare-assert", "--census-run-id", CENSUS_RUN,
                     "--replay-run-id", REPLAY_RUN, "--totals-run-id", TOTALS_RUN, "--cik", STELLUS])
    assert code == run.EXIT_UNEXPECTED == 3


def test_guard_blocked_write_still_exits_2_under_the_narrowed_mapping(staged, monkeypatch):
    """One of the two intended cases, re-asserted under the new narrower mechanism (conversion inside
    run_stage, not a blanket clause in main()) -- companion to test_main_overrides_open_guard_block_exits_2_not_3
    (fix round 2), which already covers this through main(); this one asserts the PreservationError
    conversion directly against run_stage."""
    original = run.pf.collect_override_inputs

    def spy(root, cik, hits):
        if cik == STELLUS:
            (Path(root) / "sp3p_t9fix3_blocked_write.json").write_text("{}", encoding="ascii")
        return original(root, cik, hits)

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    with pytest.raises(run.PreservationError):
        build(staged)


def test_vanishing_pinned_input_still_exits_2_under_the_narrowed_mapping(staged, monkeypatch):
    """The other intended case, re-asserted directly against run_stage: a pinned census file vanishing
    mid-build raises StageInvalidated (via _reading_pinned_inputs), not a raw FileNotFoundError."""
    original = run.pf.collect_override_inputs
    census_path = (staged.data_root / "pilot" / "filer_profile" / CENSUS_RUN / "census" / STELLUS
                  / (Q4 + ".json"))

    def spy(root, cik, hits):
        out = original(root, cik, hits)
        if cik == STELLUS:
            census_path.unlink()
        return out

    monkeypatch.setattr(run.pf, "collect_override_inputs", spy)
    with pytest.raises(run.StageInvalidated, match="vanished or became unreadable"):
        build(staged)


# ---------------------------------------------------------------- Fix round 4 (re-review of 928998a)
# The reads of inputs that BECOME pinned (override scan, census listings, the census excluded content,
# the replay record + content, the predicate code record) sat outside _reading_pinned_inputs, so an
# OSError there exited 3. They are reads of pinned inputs like any other: exit 2.


def _main_exit(staged, run_id):
    return run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                     "--run-id", run_id, "--census-run-id", CENSUS_RUN, "--replay-run-id", REPLAY_RUN,
                     "--totals-run-id", TOTALS_RUN,
                     "--cik", STELLUS])


def _file_record_failing_for(monkeypatch, label_prefix, *, unlink_after=False):
    original = run.manifest.file_record

    def patched(path, label):
        if not label.startswith(label_prefix):
            return original(path, label)
        if unlink_after:
            record = original(path, label)
            Path(path).unlink()
            return record
        raise PermissionError(13, "synthetic: access denied", str(path))

    monkeypatch.setattr(run.manifest, "file_record", patched)


def test_replay_file_vanishing_between_record_and_read_exits_2(staged, monkeypatch):
    _file_record_failing_for(monkeypatch, "replay/", unlink_after=True)
    with pytest.raises(run.StageInvalidated, match="vanished or became unreadable"):
        build(staged)


def test_replay_file_vanishing_exits_2_through_main(staged, monkeypatch):
    _file_record_failing_for(monkeypatch, "replay/", unlink_after=True)
    assert _main_exit(staged, "sp3p-profile-fix4-replay-vanish") == run.EXIT_INVALIDATED


def test_replay_file_unreadable_when_hashed_exits_2(staged, monkeypatch):
    _file_record_failing_for(monkeypatch, "replay/")
    assert _main_exit(staged, "sp3p-profile-fix4-replay-unreadable") == run.EXIT_INVALIDATED


def test_predicate_file_read_failing_exits_2(staged, monkeypatch):
    _file_record_failing_for(monkeypatch, "code/")
    assert _main_exit(staged, "sp3p-profile-fix4-predicate") == run.EXIT_INVALIDATED


def test_census_excluded_file_read_failing_exits_2(staged, monkeypatch):
    """The excluded listing is hashed inside load_authoritative_census and its CONTENT is read by
    run_stage afterwards; it vanishing in between is a pinned input vanishing."""
    original = run.lineage.load_authoritative_census

    def vanishing(*args, **kwargs):
        out = original(*args, **kwargs)
        Path(out["excluded"]["path"]).unlink()
        return out

    monkeypatch.setattr(run.lineage, "load_authoritative_census", vanishing)
    assert _main_exit(staged, "sp3p-profile-fix4-excluded") == run.EXIT_INVALIDATED


def test_override_scan_read_failing_exits_2(staged, monkeypatch):
    """scan_overrides reads every override file's content before any of them is pinned."""
    def failing(root, ciks):
        raise PermissionError(13, "synthetic: access denied", str(root))

    monkeypatch.setattr(run.pf, "scan_overrides", failing)
    assert _main_exit(staged, "sp3p-profile-fix4-scan") == run.EXIT_INVALIDATED


# ---------------------------------------------------------------- final whole-branch review: C1, C2, I3, I4


def _cohort_main(tmp_path, monkeypatch, run_id, **seed_kw):
    paths = fake_paths(tmp_path, run_id=run_id)
    seed_cohort(paths, **seed_kw)
    monkeypatch.setattr(run, "attested_under", lambda main_root, rel, content: [])
    code = run.main(["build", "--data-root", str(paths.data_root), "--main-root", str(paths.main_repo_root),
                     "--run-id", paths.run_id, "--census-run-id", CENSUS_RUN, "--replay-run-id", REPLAY_RUN,
                     "--totals-run-id", TOTALS_RUN])
    body = json.loads((paths.run_root / "results" / "exit_test.json").read_text(encoding="ascii"))
    return paths, code, body


def test_all_compared_cohort_passes_the_inception_gate_but_not_the_spec_exit(tmp_path, monkeypatch, capsys):
    """The genuine all-filers-compared fixture: PASS is still reachable. It is the GATE that passes; the
    spec's criterion (every filer 'holds') is published separately and is false, with its reason."""
    paths, code, body = _cohort_main(tmp_path, monkeypatch, "sp3p-profile-final-pass")
    assert code == 0 and body["verdict"] == "PASS"
    assert body["inception_gate"] is True and body["inception_gate_reasons"] == []
    assert body["spec_exit"] is False
    assert [r["code"] for r in body["spec_exit_reasons"]] == ["consistency_not_holds"]
    assert body["consistency_verdict_counts"] == {"holds": 0, "no_breach": 8, "breach": 0,
                                                  "insufficient_evidence": 0}
    assert "holds on all" not in json.dumps(body)
    for cik, row in body["per_cik"].items():
        counts = row["consistency_rows"]
        assert counts["compared"] >= 1 and counts["breach"] == 0, cik
        assert counts["total"] == counts["compared"] + counts["insufficient_evidence"] + counts["not_applicable"]
        assert row["consistency_verdict"] == "no_breach" and row["published_basis"] == "accepted"
    printed = capsys.readouterr().out
    assert "holds on all" not in printed
    summary = json.loads(printed)
    assert summary["inception_gate"] is True and summary["spec_exit"] is False
    assert summary["spec_exit_reasons"] == body["spec_exit_reasons"]
    assert summary["per_cik"][STELLUS]["consistency_rows"] == body["per_cik"][STELLUS]["consistency_rows"]
    # Owner rulings 1 and 3 (2026-10-04), through the CLI: both counts and the substantive keys per filer,
    # the procedure keys outside the contract with their guards, in exit_test.json and (counts) on stdout.
    consistency = json.loads((paths.run_root / "results" / "consistency.json").read_text(encoding="ascii"))
    for cik, row in body["per_cik"].items():
        assert row["compared_total"] == row["consistency_rows"]["compared"]
        assert 1 <= row["compared_substantive"] == len(row["substantive_keys_compared"]) < row["compared_total"]
        assert "/cik" in row["identity_keys_compared"] and "/cik" not in row["substantive_keys_compared"]
        assert [(r["pointer"], r["guard"]) for r in row["procedure_keys_outside_contract"]] == [
            ("/source_encodings/cash_identifiers", "independent_totals"),
            ("/invariants/rate_sanity", "production_rate_rules")]
        assert row["procedure_keys_outside_contract"][0]["guard_status_at_report_date"] == "within_tolerance"
        assert not [r for r in consistency[cik]["keys"] if r["pointer"] in (
            "/source_encodings/cash_identifiers", "/invariants/rate_sanity")]
        assert row["published_basis_tolerance"]["band_pct"] == 0.5
        assert row["published_basis_tolerance"]["outcome"] == "within_tolerance"
        for field in ("compared_total", "compared_substantive", "substantive_keys_compared",
                      "published_basis_tolerance"):
            assert summary["per_cik"][cik][field] == row[field]


def test_published_basis_needs_a_residual_inside_half_a_percent_through_the_cli(tmp_path, monkeypatch):
    """Owner ruling 2 (2026-10-04) through the CLI: the contract holds for every filer, but +0.51% (the real
    BCRED shape), -0.51% and a mixed-mode filer are candidates; +0.49% is accepted. The gate is untouched."""
    over, under, mixed, inside = "0001803498", "0001950803", "0001920453", "0001287750"
    paths, code, body = _cohort_main(
        tmp_path, monkeypatch, "sp3p-profile-own1-tolerance",
        totals_residuals={over: 0.51, under: -0.51, mixed: {"rolling": 0.49, "anchored": 0.51}, inside: 0.49})
    assert code == 0 and body["inception_gate"] is True
    states = {cik: row["published_basis"] for cik, row in body["per_cik"].items()}
    assert {c for c, s in states.items() if s == "candidate"} == {over, under, mixed}
    assert states[inside] == "accepted"
    for cik in (over, under, mixed):
        row = body["per_cik"][cik]
        assert row["totals_outcome"] == "holds"
        assert row["published_basis_tolerance"]["outcome"] == "outside_tolerance"
        assert row["grid"]["candidate"] >= 1
        doc = pd.load_document(paths.run_root / "profiles" / (cik + ".json"))
        basis = doc["admissions"][doc["partition_predicate"]["published_basis_entry_id"]]
        assert basis["witness"]["candidate_cause"] == "totals_outside_owner_tolerance_at_inception"
        stub = next(s for s in doc["stubs"] if s["key"] == "partition_structure.published_basis")
        assert "B1/B2 review item (fair-value reconciliation flag)" in stub["closing_evidence"]
        # the procedure key's guard reports its own state for this filer
        assert row["procedure_keys_outside_contract"][0]["guard_status_at_report_date"] == "outside_tolerance"
    assert body["per_cik"][inside]["published_basis_tolerance"]["outcome"] == "within_tolerance"
    pinned = json.loads((paths.run_root / "manifest.json").read_text(encoding="ascii"))
    assert pinned["published_basis_tolerance_pct"] == 0.5
    assert pinned["published_basis_tolerance_outcomes"][over] == "outside_tolerance"


def test_cohort_with_a_real_shape_filer_fails_the_inception_gate(tmp_path, monkeypatch, capsys):
    """I4: one filer in the real-data shape (no Q4 census: nothing in its wrapper can be compared, and no
    totals pair evaluates at the inception date). It is insufficient_evidence, the gate FAILS, exit 1."""
    paths, code, body = _cohort_main(tmp_path, monkeypatch, "sp3p-profile-final-realshape",
                                     no_q4_census=(NO_Q4_CENSUS,))
    assert code == run.EXIT_FAIL and body["verdict"] == "FAIL"
    assert body["inception_gate"] is False and body["spec_exit"] is False
    assert [(r["code"], r["ciks"]) for r in body["inception_gate_reasons"]] == [
        ("consistency_insufficient_evidence", [NO_Q4_CENSUS])]
    row = body["per_cik"][NO_Q4_CENSUS]
    assert row["consistency_verdict"] == "insufficient_evidence" and row["consistency"] is False
    assert row["consistency_rows"]["compared"] == 0 and row["consistency_rows"]["insufficient_evidence"] >= 3
    assert row["criterion_1"] is True and row["resolver"] is True   # stubs still answer every key
    assert row["published_basis"] == "candidate"
    assert body["consistency_verdict_counts"] == {"holds": 0, "no_breach": 7, "breach": 0,
                                                  "insufficient_evidence": 1}
    # the documents and the round trip are still written, and still clean
    roundtrip = json.loads((paths.run_root / "results" / "roundtrip.json").read_text(encoding="ascii"))
    assert roundtrip["ok"] is True
    doc = pd.load_document(paths.run_root / "profiles" / (NO_Q4_CENSUS + ".json"))
    basis = doc["admissions"][doc["partition_predicate"]["published_basis_entry_id"]]
    assert basis["state"] == "candidate"
    assert basis["witness"]["candidate_cause"] == "no_totals_outcome_at_inception"
    assert basis["witness"]["independent_totals"]["source"]["run_id"] == TOTALS_RUN
    assert "holds on all" not in capsys.readouterr().out


def test_published_basis_follows_the_pinned_totals_outcome_per_filer(tmp_path, monkeypatch):
    """I3 through the CLI: accepted where fair_value holds in every mode, candidate on a breach in any mode
    or an abstention. None of it touches the gate (a candidate still has its stub)."""
    breach, mixed, abstains = "0001950803", "0001920453", "0001715933"
    paths, code, body = _cohort_main(
        tmp_path, monkeypatch, "sp3p-profile-final-totals",
        totals={breach: "breach", mixed: {"rolling": "breach", "anchored": "holds"},
                abstains: "insufficient_evidence"})
    assert code == 0 and body["inception_gate"] is True
    states = {cik: row["published_basis"] for cik, row in body["per_cik"].items()}
    assert {c for c, s in states.items() if s == "candidate"} == {breach, mixed, abstains}
    assert sum(s == "accepted" for s in states.values()) == 5
    causes = {}
    for cik in (breach, mixed, abstains):
        doc = pd.load_document(paths.run_root / "profiles" / (cik + ".json"))
        causes[cik] = doc["admissions"][doc["partition_predicate"]["published_basis_entry_id"]]["witness"][
            "candidate_cause"]
    assert causes == {breach: "totals_breach_at_inception", mixed: "totals_breach_at_inception",
                      abstains: "totals_insufficient_evidence_at_inception"}
    pinned = json.loads((paths.run_root / "manifest.json").read_text(encoding="ascii"))
    assert pinned["totals_run_id"] == TOTALS_RUN
    assert any(i["label"] == "totals/" + TOTALS_RUN + "/results/backtest_results.json" for i in pinned["inputs"])


def test_missing_totals_results_are_refused_before_any_write(staged):
    _totals_path(staged).unlink()
    with pytest.raises(run.StageInvalidated, match="totals contract results missing"):
        build(staged)
    assert not (staged.run_root / "manifest.json").is_file()
    assert not (staged.run_root / "profiles").exists()


def test_missing_totals_results_exit_2_through_main(staged):
    _totals_path(staged).unlink()
    assert _main_exit(staged, "sp3p-profile-final-nototals") == run.EXIT_INVALIDATED


def test_totals_run_id_is_a_required_cli_argument(staged):
    with pytest.raises(SystemExit) as exc:
        run.main(["build", "--data-root", str(staged.data_root), "--main-root", str(staged.main_repo_root),
                  "--run-id", "sp3p-profile-final-noarg", "--census-run-id", CENSUS_RUN,
                  "--replay-run-id", REPLAY_RUN, "--cik", STELLUS])
    assert exc.value.code == 2


def test_totals_results_under_another_predicate_version_exit_2(staged):
    path = _totals_path(staged)
    results = totals_results(STELLUS, "holds", version="census-published.v1")
    path.write_text(json.dumps(dict(results=results)), encoding="ascii")
    assert _main_exit(staged, "sp3p-profile-final-v1totals") == run.EXIT_INVALIDATED


def test_totals_file_read_failing_exits_2(staged, monkeypatch):
    _file_record_failing_for(monkeypatch, "totals/", unlink_after=True)
    assert _main_exit(staged, "sp3p-profile-final-totals-vanish") == run.EXIT_INVALIDATED


def test_single_filer_summary_publishes_both_fields_and_row_counts(staged):
    summary = build(staged)
    assert summary["verdict"] == "FAIL" and summary["inception_gate"] is False and summary["spec_exit"] is False
    assert "missing_filers" in [r["code"] for r in summary["inception_gate_reasons"]]
    row = summary["per_cik"][STELLUS]
    assert set(row["consistency_rows"]) == {"total", "compared", "holds", "breach", "insufficient_evidence",
                                            "not_applicable"}
    assert set(row["grid"]) == {"accepted", "candidate", "stubs"} and row["published_basis"] == "accepted"
