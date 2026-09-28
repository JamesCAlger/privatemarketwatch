"""Filer-profile pilot Task 5: cached-source validation, bounded performance, cache identity.

Synthetic instances are written to tmp_path. The three `needs_cache` fixture tests read
cached instances through PROFILE_PILOT_DATA_ROOT (set by the pilot launcher), are pinned
by the source sha256 and write nothing. Their expected values were read from the raw XML
with a separate stdlib reader, not from the census or the validator.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path

import pytest

from scripts.profile_pilot import census, census_collect, census_run, manifest
from tests.test_profile_pilot_census import (CIK, FOOTNOTE_LINK, PRIOR, Q, assemble, ctx, document,
                                             fact, position, write)
from tests.test_profile_pilot_paths import fake_paths, put_instance


def _v():
    from scripts.profile_pilot import census_validate
    return census_validate


def rich_instance() -> str:
    """Rates, a comparative position, a text block, a footnote on a rate fact."""
    extra = [fact("us-gaap:InvestmentInterestRate", "p1", "0.1050", unit="pure", decimals="4", fid="r1"),
             fact("us-gaap:InvestmentBasisSpreadVariableRate", "p1", "0.0600", unit="pure",
                  decimals="4", fid="s1"),
             fact("us-gaap:InvestmentInterestRatePaidInKind", "p1", "0.02", unit="pure", decimals="4")]
    blob = "Policy text " * 150
    contexts, facts = assemble(
        position("p1", "Acme Corp Term Loan", "100", extra=extra),
        position("old", "Acme Corp Term Loan", "90", period=PRIOR,
                 extra=[fact("us-gaap:InvestmentInterestRate", "old", "0.0950", unit="pure",
                             decimals="4", fid="r_old")]),
        ([ctx("fund_dur", ("2023-01-01", Q)), ctx("prior_dur", ("2022-01-01", "2022-03-31"))],
         [fact("us-gaap:SignificantAccountingPoliciesTextBlock", "fund_dur", blob, fid="tb1"),
          fact("us-gaap:InvestmentIncomeInterest", "prior_dur", "7", unit="usd", decimals="0",
               fid="inc_prior")]))
    link = FOOTNOTE_LINK.replace("#f_fv", "#r1")
    return document(contexts, facts, extra=link)


def build(tmp_path, text=None, **kwargs):
    path = write(tmp_path, text or rich_instance())
    meta = dict(cik=CIK, report_date=Q, accession_number="0000000000-23-000001", form_type="10-Q",
                role="q1")
    return census.build_census(path, meta, **kwargs), path


def check(report, name):
    return report["checks"][name]


# ---------------------------------------------------------------- validator on synthetic sources

def test_validator_passes_a_faithful_census_on_identified_facts(tmp_path):
    doc, path = build(tmp_path)
    report = _v().validate_against_source(doc, path)
    assert report["verdict"] == "pass", json.dumps(report["checks"], indent=1)[:3000]
    rates = check(report, "rates")
    assert rates["status"] == "pass" and rates["checked"] >= 4
    ids = {e["fact_id"] for e in rates["examples"]}
    assert {"r1", "s1"} <= ids
    comparative = check(report, "comparative_contexts")
    assert comparative["status"] == "pass"
    assert {"old", "prior_dur"} <= set(comparative["context_ids"])
    text = check(report, "text_facts")
    assert text["status"] == "pass" and "tb1" in {e["fact_id"] for e in text["examples"]}
    notes = check(report, "footnotes")
    assert notes["status"] == "pass" and notes["checked"] == 1
    assert notes["resources"][0]["fact_ids"] == ["r1"]


def test_validator_detects_a_changed_rate_value(tmp_path):
    doc, path = build(tmp_path)
    target = next(f for f in doc["facts"] if f["id"] == "r1")
    target["value"] = "0.1051"
    report = _v().validate_against_source(doc, path)
    rates = check(report, "rates")
    assert report["verdict"] == "fail" and rates["status"] == "fail"
    assert any(m["fact_id"] == "r1" for m in rates["mismatches"])


def test_validator_detects_a_position_rate_not_backed_by_its_source_fact(tmp_path):
    doc, path = build(tmp_path)
    pos = next(p for p in doc["positions"] if p["context_id"] == "p1")
    pos["fields"]["interest_rate"]["value"] = "0.2"
    report = _v().validate_against_source(doc, path)
    assert check(report, "rates")["status"] == "fail"
    assert any(m.get("context_id") == "p1" for m in check(report, "rates")["mismatches"])


def test_validator_detects_a_dropped_rate_fact(tmp_path):
    doc, path = build(tmp_path)
    doc["facts"] = [f for f in doc["facts"] if f["id"] != "s1"]
    report = _v().validate_against_source(doc, path)
    assert check(report, "fact_inventory")["status"] == "fail"
    assert report["verdict"] == "fail"


def test_validator_detects_a_wrong_comparative_period(tmp_path):
    doc, path = build(tmp_path)
    context = next(c for c in doc["contexts"] if c["id"] == "old")
    context["period"] = dict(kind="instant", instant="2022-09-30")
    report = _v().validate_against_source(doc, path)
    assert check(report, "comparative_contexts")["status"] == "fail"
    assert any(m["context_id"] == "old" for m in check(report, "comparative_contexts")["mismatches"])


def test_validator_detects_a_comparative_period_labelled_current(tmp_path):
    doc, path = build(tmp_path)
    for period in doc["periods"]:
        if period.get("instant") == PRIOR:
            period["relation"] = "document_period_end"
    report = _v().validate_against_source(doc, path)
    assert check(report, "comparative_contexts")["status"] == "fail"


def test_validator_detects_changed_text_and_footnote_links(tmp_path):
    doc, path = build(tmp_path)
    block = next(f for f in doc["facts"] if f["id"] == "tb1")
    block["text_sha256"] = "0" * 64
    doc["footnotes"]["resources"][0]["fact_indices"] = []
    report = _v().validate_against_source(doc, path)
    assert check(report, "text_facts")["status"] == "fail"
    assert check(report, "footnotes")["status"] == "fail"


def test_validator_confirms_unsupported_footnotes_from_the_source(tmp_path):
    contexts, facts = position("p1", "Acme Corp", "100")
    doc, path = build(tmp_path, document(contexts, facts))
    report = _v().validate_against_source(doc, path)
    notes = check(report, "footnotes")
    assert notes["status"] == "pass" and notes["census_state"] == "unsupported"
    assert notes["raw_footnote_links"] == 0


def test_validator_refuses_a_source_with_a_doctype(tmp_path):
    doc, _ = build(tmp_path)
    bad = write(tmp_path, '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>', "bad.xml")
    with pytest.raises(_v().SourceRefused):
        _v().validate_against_source(doc, bad)


def test_validator_detects_a_source_hash_mismatch(tmp_path):
    doc, path = build(tmp_path)
    doc["document"]["sha256_before"] = "f" * 64
    report = _v().validate_against_source(doc, path)
    assert check(report, "source")["status"] == "fail" and report["verdict"] == "fail"


def test_identity_evidence_comes_from_the_xml_not_the_cohort_table(tmp_path):
    doc, path = build(tmp_path)
    report = _v().validate_against_source(doc, path)
    identity = report["identity"]
    assert identity["raw_fv_contexts_at_document_period_end"]["typed_axes"] == {
        "us-gaap:InvestmentIdentifierAxis": 1}
    assert identity["census_position_role_reasons"] == {"typed_investment_identifier": 1}
    assert report["economic_periods"]["document_period_end_dates"] == [Q]
    assert PRIOR in report["economic_periods"]["comparative_instants"]
    assert report["cohort"]["forced"] is False


def test_explicit_identity_rule_outside_its_evidenced_period_fails(tmp_path):
    v = _v()
    onex = "0001860424"
    rule = v.explicit_rule_periods(onex)
    assert rule["rule"] == "onex_explicit_investee_and_debt_type" and rule["periods"] == ["2023-03-31"]
    doc = dict(positions=[dict(context_id="c1", period=dict(kind="instant", instant="2023-06-30"))],
               contexts=[dict(id="c1", role="confirmed_position",
                              role_reason="onex_explicit_investee_and_debt_type",
                              period=dict(kind="instant", instant="2023-06-30"))])
    got = v.check_explicit_rule_periods(doc, onex)
    assert got["status"] == "fail" and got["mismatches"][0]["instant"] == "2023-06-30"
    doc["contexts"][0]["period"] = dict(kind="instant", instant="2023-03-31")
    assert v.check_explicit_rule_periods(doc, onex)["status"] == "pass"
    nexpoint = v.explicit_rule_periods("0001588272")
    assert nexpoint["periods"] == ["2023-03-31"]
    assert v.explicit_rule_periods(CIK)["rule"] is None


# ---------------------------------------------------------------- bounded collection

class StageClock:
    """Expires the moment the collector checks the named stage."""

    def __init__(self, stage):
        self.stage, self.seconds, self.seen = stage, 1.0, []

    def check(self, stage):
        self.seen.append(stage)
        if stage == self.stage:
            raise census_collect.TimeBound(stage, self.seconds)


@pytest.mark.parametrize("stage", ["parse", "contexts", "units", "facts", "text_facts", "footnotes"])
def test_time_bound_covers_every_collection_stage(tmp_path, stage):
    path = write(tmp_path, rich_instance())
    out = census_collect.collect_instance(path, clock=StageClock(stage))
    channels = out["channels"]
    assert census_collect.collection_state(channels, out["errors"]) == "incomplete"
    truncated = [n for n, ch in channels.items() if ch["state"] == "truncated"]
    assert truncated and all("time bound" in channels[n]["reason"] and stage in channels[n]["reason"]
                             for n in truncated)
    if stage == "parse":
        assert out["contexts"] == [] and out["facts"] == []


def test_collector_checks_the_clock_in_every_stage(tmp_path):
    path = write(tmp_path, rich_instance())
    clock = StageClock("never")
    out = census_collect.collect_instance(path, clock=clock)
    assert census_collect.collection_state(out["channels"], out["errors"]) == "complete"
    assert {"parse", "contexts", "units", "facts", "text_facts", "footnotes", "nested_scan"} <= set(clock.seen)


def test_zero_timeout_is_an_incomplete_collection_not_a_smaller_census(tmp_path):
    doc, _ = build(tmp_path, bounds=census.Bounds(timeout_seconds=0))
    assert doc["collection"]["state"] == "incomplete"
    assert doc["facts"] == [] and doc["positions"] == []


def test_nested_item_facts_downgrade_the_fact_channels(tmp_path):
    contexts, facts = position("p1", "Acme Corp", "100")
    nested = ('<fake:HoldingTuple>'
              + fact("us-gaap:InvestmentOwnedAtCost", "p1", "95", unit="usd", decimals="0")
              + '</fake:HoldingTuple>')
    doc, _ = build(tmp_path, document(contexts, facts, extra=nested))
    assert doc["collection"]["state"] == "incomplete"
    for name in ("numeric_facts", "text_facts"):
        assert doc["channels"][name]["state"] == "truncated"
        assert "nested" in doc["channels"][name]["reason"]


def test_fed_parse_is_hashed_and_equals_the_before_hash(tmp_path):
    path = write(tmp_path, rich_instance())
    out = census_collect.collect_instance(path)
    assert out["source"]["sha256_parsed"] == out["source"]["sha256_before"] == out["source"]["sha256_after"]


# ---------------------------------------------------------------- limits and calibrated estimate

def _entry(paths, cik=CIK, accession="0000000000-23-000001", text=None):
    path = put_instance(paths.main_repo_root, cik, accession, text or rich_instance().replace(CIK, cik))
    return dict(cik=cik, quarter=Q, role="q1", status="selected", accession_number=accession,
                form_type="10-Q", source_path=str(path))


def _census_files(paths, cik=CIK):
    root = paths.run_root / "census" / cik
    return sorted(p for p in root.rglob("*.json")) if root.exists() else []


def test_limit_exceeded_is_a_failure_to_assess_with_a_receipt_and_no_cache(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    entry = _entry(paths)
    monkeypatch.setattr(census_run, "LIMITS", census_run.PerformanceLimits(
        max_wall_seconds=0.0, max_peak_bytes=2 * 2 ** 30, target_positions=1000))
    got = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    assert got["status"] == "limit_exceeded" and "wall" in got["reason"]
    assert _census_files(paths) == []
    receipt = json.loads((paths.run_root / got["receipt"]).read_text(encoding="ascii"))
    assert receipt["status"] == "limit_exceeded" and receipt["fingerprint"] == got["fingerprint"]
    assert receipt["measured"]["wall_seconds"] >= 0


def test_peak_memory_limit_is_enforced(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    monkeypatch.setattr(census_run, "LIMITS", census_run.PerformanceLimits(
        max_wall_seconds=60.0, max_peak_bytes=1, target_positions=1000))
    got = census_run.census_fund_quarter(paths, _entry(paths), lease_factory=None)
    assert got["status"] == "limit_exceeded" and "peak" in got["reason"]


def test_measurement_records_wall_peak_and_serialised_size(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    got = census_run.census_fund_quarter(paths, _entry(paths), lease_factory=None)
    assert got["status"] == "collected"
    m = got["measurement"]
    for key in ("wall_seconds", "stage_seconds", "peak_bytes_upper", "peak_exact", "sampled_peak_rss_bytes",
                "serialised_bytes", "compact_bytes", "estimate_seconds", "estimate_bytes"):
        assert key in m, key
    assert got["performance"]["status"] == "pass"
    assert got["performance"]["limits"] == dict(max_wall_seconds=60.0, max_peak_bytes=2 * 2 ** 30,
                                                target_positions=1000)


def test_calibrated_estimate_envelopes_every_calibration_point():
    cal = census_run.CALIBRATION
    assert cal["source_run"] == "stageb-20260928t231648z" and len(cal["points"]) >= 20
    for point in cal["points"]:
        seconds, peak = census_run.estimate(point["source_bytes"])
        assert seconds >= point["wall_seconds"] and peak >= point["peak_rss_bytes"], point
    old_seconds = 5.0 + 66_454_503 / 1_500_000
    assert census_run.estimate(66_454_503)[0] < old_seconds / 2  # no longer 5-40x conservative


def test_heavy_cik_never_bypasses_the_lease_whatever_the_estimate():
    for cik in ("0001287750", "0001803498"):
        workload = dict(ciks=[cik], instance_count=1, full_cache_scan=False, pipeline_cik_count=0,
                        est_seconds=0.0, est_bytes=0)
        assert manifest.classify_workload(workload) is True


def test_performance_summary_assesses_the_thousand_position_target():
    results = [dict(cik="0001287750", report_date="2022-09-30", status="collected",
                    summary=dict(position_observations_current=1031),
                    measurement=dict(stage_seconds=3.0, wall_seconds=2.0, peak_bytes_upper=400_000_000,
                                     peak_exact=True),
                    performance=dict(status="pass")),
               dict(cik="0001901037", report_date="2022-09-30", status="limit_exceeded",
                    summary=None, measurement=dict(stage_seconds=70.0), performance=None)]
    summary = census_run.performance_summary(results)
    assert summary["target"]["instances"][0]["cik"] == "0001287750"
    assert summary["target"]["status"] == "pass"
    assert summary["not_assessed"] == [dict(cik="0001901037", report_date="2022-09-30",
                                            status="limit_exceeded")]
    assert summary["status"] == "fail"  # a failure to assess anywhere is not a pass
    assert census_run.performance_summary(results[1:])["target"]["status"] == "not_assessed"


# ---------------------------------------------------------------- cache identity and regeneration

def test_cache_hit_on_identical_dependencies(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    entry = _entry(paths)
    first = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    again = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    assert (first["cache"], again["cache"]) == ("miss", "hit")
    assert first["path"] == again["path"] and first["fingerprint"][:16] in first["path"].replace("\\", "/")


def _regenerates(paths, entry, change):
    first = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    before = Path(first["path"]).read_bytes()
    change()
    second = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    assert second["status"] == "collected" and second["cache"] == "miss"
    assert second["fingerprint"] != first["fingerprint"] and second["path"] != first["path"]
    assert Path(first["path"]).read_bytes() == before  # the old complete result is preserved
    return first, second


def test_code_dependency_change_forces_regeneration(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    dep = tmp_path / "extra_dependency.py"
    dep.write_text("A = 1\n", encoding="ascii")
    monkeypatch.setattr(census_run, "CODE_DEPENDENCIES", census_run.CODE_DEPENDENCIES + (str(dep),))
    _regenerates(paths, _entry(paths), lambda: dep.write_text("A = 2\n", encoding="ascii"))


def test_bounds_change_forces_regeneration(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    entry = _entry(paths)
    first = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    second = census_run.census_fund_quarter(paths, entry, lease_factory=None,
                                            bounds=census.Bounds(max_contexts=39_999))
    assert second["cache"] == "miss" and second["fingerprint"] != first["fingerprint"]


def test_collector_version_change_forces_regeneration(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    _regenerates(paths, _entry(paths),
                 lambda: monkeypatch.setattr(census_run, "COLLECTOR_VERSION", "census.test+changed"))


def test_source_change_forces_regeneration(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    entry = _entry(paths)
    _regenerates(paths, entry, lambda: Path(entry["source_path"]).write_text(
        rich_instance().replace("0.1050", "0.1075"), encoding="utf-8"))


def test_identity_records_code_digest_runtime_and_configuration(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    got = census_run.census_fund_quarter(paths, _entry(paths), lease_factory=None)
    body = json.loads(Path(got["path"]).read_text(encoding="ascii"))
    deps = body["identity"]["dependencies"]
    labels = {r["label"] for r in deps["code"]}
    assert {"code/scripts/profile_pilot/census_collect.py", "code/pipeline/identifier_rate.py",
            "code/scripts/profile_pilot/envelope.py", "code/pipeline/bdc_filings.py"} <= labels
    assert all(r["status"] == "present" and len(r["sha256"]) == 64 for r in deps["code"])
    assert set(deps["runtime"]) >= {"python", "lxml", "libxml2", "jsonschema"}
    assert deps["bounds"] == asdict(census.Bounds())
    assert body["identity"]["collector_version"] == census_run.COLLECTOR_VERSION
    assert len(deps["code_digest"]) == 64


def test_prior_incomplete_result_at_the_identity_path_is_never_reused(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    entry = _entry(paths)
    plan = census_run.plan(paths, entry)
    target = paths.run_root / plan["relative"]
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(dict(identity=plan["identity"], complete=False, result={})),
                      encoding="ascii")
    got = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    assert got["status"] == "stage_invalidated" and "incomplete" in got["reason"]


def test_failed_runs_leave_separate_receipts_and_no_cached_result(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    entry = _entry(paths)
    tight = census.Bounds(max_facts=3)
    first = census_run.census_fund_quarter(paths, entry, lease_factory=None, bounds=tight)
    second = census_run.census_fund_quarter(paths, entry, lease_factory=None, bounds=tight)
    assert first["status"] == second["status"] == "incomplete"
    assert first["receipt"] != second["receipt"]
    receipts = sorted((paths.run_root / "census_failures").rglob("*.json"))
    assert len(receipts) == 2 and _census_files(paths) == []
    kept = [r.read_bytes() for r in receipts]
    ok = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    assert ok["status"] == "collected" and ok["cache"] == "miss"
    assert [r.read_bytes() for r in receipts] == kept
    body = json.loads(receipts[0].read_text(encoding="ascii"))
    assert body["collection"]["state"] == "incomplete" and body["fingerprint"] == first["fingerprint"]


def test_validation_stage_is_cached_on_the_census_file_and_regenerates_with_it(tmp_path, monkeypatch):
    v = _v()
    paths = fake_paths(tmp_path, run_id="stageb-test")
    entry = _entry(paths)
    census_run.census_fund_quarter(paths, entry, lease_factory=None)
    first = v.validate_fund_quarter(paths, entry, lease_factory=None)
    again = v.validate_fund_quarter(paths, entry, lease_factory=None)
    assert first["status"] == "validated" and first["verdict"] == "pass"
    assert (first["cache"], again["cache"]) == ("miss", "hit")
    monkeypatch.setattr(census_run, "COLLECTOR_VERSION", "census.test+changed")
    missing = v.validate_fund_quarter(paths, entry, lease_factory=None)
    assert missing["status"] == "census_missing"
    census_run.census_fund_quarter(paths, entry, lease_factory=None)
    third = v.validate_fund_quarter(paths, entry, lease_factory=None)
    assert third["cache"] == "miss" and third["path"] != first["path"]


def test_heavy_validation_runs_only_under_the_lease(tmp_path, monkeypatch):
    import psutil
    from scripts.profile_pilot import protection
    v = _v()
    paths = fake_paths(tmp_path, run_id="stageb-test")
    entry = _entry(paths, cik="0001287750", accession="0001287750-23-000001")

    class Self:
        pid = os.getpid()
        info = dict(pid=os.getpid(), name="python.exe", cmdline=["python", "-m", "pytest"])

    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([Self()]))
    factory = lambda: protection.shared_heavy_lease(paths, head="test")  # noqa: E731
    assert census_run.census_fund_quarter(paths, entry, lease_factory=factory)["status"] == "collected"
    refused = v.validate_fund_quarter(paths, entry, lease_factory=None)
    assert refused["status"] == "lease_refused"
    assert not (paths.run_root / "validation" / "0001287750").exists()
    got = v.validate_fund_quarter(paths, entry, lease_factory=factory)
    assert got["status"] == "validated" and got["heavy"] is True
    assert got["lease"]["acquired_utc"] and got["lease"]["released_utc"]


# ---------------------------------------------------------------- cached fixtures (launcher only)

FIXTURES = {
    "stellus": dict(cik="0001901037", report_date="2022-09-30", accession="0001558370-22-016375",
                    file="1901037/000155837022016375.xml",
                    sha256="ec651855d92e5a819a1b540a9923a42184c561265d0a1b930727128423747b96"),
    "nexpoint": dict(cik="0001588272", report_date="2023-09-30", accession="0001193125-23-276929",
                     file="1588272/000119312523276929.xml",
                     sha256="69223fcfd633fd122886a9f19436ec8df6040db5361017ef094af1136905cff9"),
    "fidelity": dict(cik="0001920453", report_date="2023-03-31", accession="0000950170-23-021729",
                     file="1920453/000095017023021729.xml",
                     sha256="d2eaa9ff98cb748e0105b9ff344bb9e99e9ef0394ded226f65ad05b81999bb8f"),
}


def _fixture(name):
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    if not data_root:
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    spec = FIXTURES[name]
    path = Path(data_root) / "raw" / "filings" / "bdc_xbrl" / spec["file"]
    if not path.is_file():
        pytest.skip("cached fixture instance missing: " + spec["file"])
    assert manifest.sha256_file(path) == spec["sha256"], "fixture source changed: " + spec["file"]
    meta = dict(cik=spec["cik"], report_date=spec["report_date"], accession_number=spec["accession"],
                form_type="10-Q", role="q1")
    doc = census.build_census(path, meta)
    assert doc["collection"]["state"] == "complete" and census.validate_census(doc)["ok"]
    report = _v().validate_against_source(doc, path, cik=spec["cik"], report_date=spec["report_date"])
    assert report["verdict"] == "pass", json.dumps(
        {k: v for k, v in report["checks"].items() if v["status"] == "fail"}, indent=1)[:3000]
    return doc, report


def _fact(doc, fact_id):
    return next(f for f in doc["facts"] if f["id"] == fact_id)


@pytest.mark.needs_cache
def test_stellus_q1_fixture_cross_checks_against_raw_source():
    doc, report = _fixture("stellus")
    rate = _fact(doc, "Tc_RnaSSYDlN06hqpCJUipmCQ_6_11")
    assert rate["qname"] == "us-gaap-supplement:InvestmentInterestRatePaidInCash"
    assert rate["field"] == "interest_rate" and Decimal(rate["value"]) == Decimal("0.1020")
    assert rate["context_id"].startswith("As_Of_9_30_2022_us-gaap_InvestmentIdentifierAxis_spcbdc_cnst_string_"
                                         "ArcherSystemsLlcTermLoan")
    spread = _fact(doc, "Tc_lrNbJDOFFEe0wnhF4FghQw_6_7")
    assert spread["field"] == "basis_spread" and Decimal(spread["value"]) == Decimal("0.0650")
    comparative = report["checks"]["comparative_contexts"]
    assert any(c.startswith("As_Of_12_31_2021_us-gaap_StatementEquityComponentsAxis_us-gaap_RetainedEarningsMember")
               for c in comparative["context_ids"])
    assert {"2021-12-31", "2022-03-31"} <= set(report["economic_periods"]["comparative_instants"])
    assert report["economic_periods"]["document_period_end_dates"] == ["2022-09-30"]
    assert report["checks"]["footnotes"]["census_state"] == "unsupported"
    assert report["checks"]["footnotes"]["raw_footnote_links"] == 0
    assert report["checks"]["text_facts"]["checked"] >= 80  # 82 TextBlock facts in the source
    identity = report["identity"]
    assert identity["raw_fv_contexts_at_document_period_end"]["typed_axes"] == {
        "us-gaap-supplement:InvestmentIdentifierAxis": 62}
    assert identity["explicit_rule"]["rule"] is None
    assert report["checks"]["document"]["document_type"] == ["10-Q"]


@pytest.mark.needs_cache
def test_nexpoint_q1_fixture_identity_is_typed_and_the_explicit_rule_stays_earlier():
    doc, report = _fixture("nexpoint")
    fixed = _fact(doc, "Fact_92785955")
    assert fixed["field"] == "interest_rate" and fixed["raw"] == "0.10"
    spread_as_rate = _fact(doc, "Fact_92785954")  # SOFR + 375 tagged InvestmentInterestRate = 3.75
    assert spread_as_rate["raw"] == "3.75" and spread_as_rate["field"] == "interest_rate"
    prior_fv = _fact(doc, "Fact_92785079")
    assert prior_fv["value"] == "1318346" and prior_fv["context_id"].startswith("PAsOn12_31_2022_")
    assert "2022-12-31" in report["economic_periods"]["comparative_instants"]
    notes = report["checks"]["footnotes"]
    assert notes["census_state"] == "complete" and notes["status"] == "pass"
    assert any(e["label"] == "FN_320824" and e["text_prefix"].startswith("Non-income producing security")
               for e in notes["resources"])
    identity = report["identity"]
    assert identity["raw_fv_contexts_at_document_period_end"]["typed_axes"] == {
        "us-gaap:InvestmentIdentifierAxis": 57}
    assert identity["explicit_rule"]["periods"] == ["2023-03-31"]
    assert identity["census_position_role_reasons"].get("nexpoint_explicit_investee_and_instrument", 0) == 0
    assert report["checks"]["explicit_rule_periods"]["status"] == "pass"


@pytest.mark.needs_cache
def test_fidelity_q1_fixture_is_the_low_history_case():
    doc, report = _fixture("fidelity")
    rate = _fact(doc, "F_5c4d000b-4a5f-486c-aff9-6c93d8794da8")
    assert rate["field"] == "interest_rate" and rate["raw"] == "0.1111"
    assert rate["context_id"] == "C_2d785026-1420-48fa-888a-cad1bd55852b"
    comparative = report["checks"]["comparative_contexts"]
    assert "C_d5744b8a-cefb-4676-8f01-99179df12b72" in comparative["context_ids"]
    notes = report["checks"]["footnotes"]
    assert any(e["label"] == "FNT_d71395fd-f8ee-4159-b0e3-b6a6008154e0"
               and e["text_prefix"] == "All debt investments are shown at amortized cost."
               for e in notes["resources"])
    assert report["history"]["class"] == "low_history"
    assert report["history"]["positions_current"] < 50
    assert report["identity"]["raw_fv_contexts_at_document_period_end"]["typed_axes"] == {
        "us-gaap-supplement:InvestmentIdentifierAxis": 26}
