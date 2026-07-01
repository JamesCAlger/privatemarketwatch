"""Tests for the B2 remediation driver pure core (discover/snapshots/gate/promote)."""

from __future__ import annotations

import csv
import json

import pandas as pd

from scripts.agent_b2 import run_remediation as rr


# --------------------------------------------------------------- group_real_errors

def test_group_real_errors_packets_by_cik_and_fix_class():
    verdicts = {
        "RVQ_a": {"verdict": "real_error", "mechanism": "subtotal_leak",
                  "findings": [{"fix_class": "subtotal_filter"}]},
        "RVQ_b": {"verdict": "real_error", "mechanism": "genuine_value_defect",
                  "findings": [{"fix_class": "all_pik_normalization"}, {"fix_class": "dedup"}]},
        "RVQ_c": {"verdict": "false_alarm"},  # ignored
        "RVQ_d": {"verdict": "real_error", "mechanism": "unknown", "findings": []},  # no fix_class
    }
    meta = {
        "RVQ_a": {"cik": "0001743415", "report_date": "2024-12-31", "rule_name": "fv_conservation"},
        "RVQ_b": {"cik": "0001715933", "report_date": "2025-03-31", "rule_name": "C113"},
        "RVQ_d": {"cik": "0001715933", "report_date": "2025-03-31", "rule_name": "C113"},
    }
    packets = rr.group_real_errors(verdicts, meta)
    keyed = {(p["cik"], p["fix_class"]): p for p in packets}
    assert ("0001743415", "subtotal_filter") in keyed
    # the multi-defect verdict produced two packets
    assert ("0001715933", "all_pik_normalization") in keyed
    assert ("0001715933", "dedup") in keyed
    # the no-fix_class real_error is grouped under None (needs a human)
    assert ("0001715933", None) in keyed
    # false_alarm excluded
    assert all(p["cik"] != "RVQ_c" for p in packets)
    # stage-ordered: stage-1 packets (subtotal_filter/dedup) before stage-2 (all_pik)
    stages = [p["stage"] for p in packets if p["fix_class"]]
    assert stages == sorted(stages)


def test_group_real_errors_dedupes_same_review_id_for_same_fix_class():
    verdicts = {
        "RVQ_a": {"verdict": "real_error", "mechanism": "comparative_leak",
                  "findings": [{"fix_class": "comparative_period_filter"},
                               {"fix_class": "comparative_period_filter"}]},
    }
    meta = {
        "RVQ_a": {"cik": "0001603480", "report_date": "2025-06-30",
                  "rule_name": "fv_conservation"},
    }
    packets = rr.group_real_errors(verdicts, meta)
    assert len(packets) == 1
    assert packets[0]["review_ids"] == ["RVQ_a"]


# --------------------------------------------------------------- conservation snapshots

def _holdings(rows):
    return pd.DataFrame(rows)


def test_conservation_snapshot_flags_overshoot():
    df = _holdings([
        {"report_date": "2024-12-31", "fair_value": 200.0},
        {"report_date": "2024-12-31", "fair_value": 137.0},  # leaked subtotal
        {"report_date": "2024-09-30", "fair_value": 300.0},
    ])
    snaps = rr.build_conservation_snapshots(df, {"2024-12-31": 200.0, "2024-09-30": 300.0})
    assert snaps["2024-12-31"]["flags"] == ["fv_conservation"]  # 337 vs 200
    assert snaps["2024-12-31"]["fv_at_risk"] == 137.0
    assert snaps["2024-09-30"]["flags"] == []  # 300 vs 300 clean


def test_conservation_snapshot_clears_after_removal():
    df = _holdings([{"report_date": "2024-12-31", "fair_value": 200.0},
                    {"report_date": "2024-09-30", "fair_value": 300.0}])
    snaps = rr.build_conservation_snapshots(df, {"2024-12-31": 200.0, "2024-09-30": 300.0})
    assert snaps["2024-12-31"]["flags"] == []


# --------------------------------------------------------------- end-to-end gate

def test_filter_holdings_cik_normalizes():
    df = _holdings([
        {"cik": "0001377936", "report_date": "2026-02-28", "fair_value": 1.0},
        {"cik": 1377936, "report_date": "2026-02-28", "fair_value": 2.0},   # int form
        {"cik": "0001742313", "report_date": "2026-02-28", "fair_value": 9.0},
    ])
    out = rr.filter_holdings_cik(df, "0001377936")
    assert len(out) == 2 and out["fair_value"].tolist() == [1.0, 2.0]


def test_gate_conservation_packet_pass_on_subtotal_removal():
    anchors = {"2024-12-31": 200.0, "2024-09-30": 300.0, "2024-06-30": 280.0}
    baseline = _holdings([
        {"report_date": "2024-12-31", "fair_value": 200.0},
        {"report_date": "2024-12-31", "fair_value": 137.0},   # leaked subtotal (the defect)
        {"report_date": "2024-09-30", "fair_value": 300.0},
        {"report_date": "2024-06-30", "fair_value": 280.0},
    ])
    trial = _holdings([  # subtotal removed in the target quarter; held-out quarters untouched
        {"report_date": "2024-12-31", "fair_value": 200.0},
        {"report_date": "2024-09-30", "fair_value": 300.0},
        {"report_date": "2024-06-30", "fair_value": 280.0},
    ])
    res = rr.gate_conservation_packet(cik="0001743415", target_quarter="2024-12-31",
                                      baseline_df=baseline, trial_df=trial, anchors=anchors)
    assert res.verdict == "PASS", res.reasons


def test_gate_conservation_packet_rejects_held_out_regression():
    anchors = {"2024-12-31": 200.0, "2024-09-30": 300.0, "2024-06-30": 280.0}
    baseline = _holdings([
        {"report_date": "2024-12-31", "fair_value": 200.0},
        {"report_date": "2024-12-31", "fair_value": 137.0},
        {"report_date": "2024-09-30", "fair_value": 300.0},
        {"report_date": "2024-06-30", "fair_value": 280.0},
    ])
    trial = _holdings([  # over-broad: also deleted a real row from a held-out quarter
        {"report_date": "2024-12-31", "fair_value": 200.0},
        {"report_date": "2024-09-30", "fair_value": 250.0},  # now undershoots 300 -> new flag
        {"report_date": "2024-06-30", "fair_value": 280.0},
    ])
    res = rr.gate_conservation_packet(cik="0001743415", target_quarter="2024-12-31",
                                      baseline_df=baseline, trial_df=trial, anchors=anchors)
    assert res.verdict == "FAIL"
    assert res.checks["no_new_flags"] is False


# --------------------------------------------------------------- discover + promote (IO)

def test_discover_writes_worklist(tmp_path):
    vdir = tmp_path / "verdicts"
    vdir.mkdir()
    (vdir / "RVQ_a.json").write_text(json.dumps(
        {"review_id": "RVQ_a", "verdict": "real_error", "mechanism": "subtotal_leak",
         "findings": [{"fix_class": "subtotal_filter"}]}), encoding="utf-8")
    (vdir / "RVQ_old.json").write_text(json.dumps(
        {"review_id": "RVQ_old", "verdict": "real_error", "mechanism": "subtotal_leak",
         "findings": [{"fix_class": "subtotal_filter"}]}), encoding="utf-8")
    swl = tmp_path / "source_worklist.csv"
    with open(swl, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["review_id", "cik", "report_date", "rule_name"])
        w.writeheader()
        w.writerow({"review_id": "RVQ_a", "cik": "0001743415",
                    "report_date": "2024-12-31", "rule_name": "fv_conservation"})
    res = rr.discover("B2_1", base_dir=tmp_path / "agent_b2", verdicts_dir=vdir, source_worklist=swl)
    assert res["n_packets"] == 1 and res["n_actionable"] == 1
    rows = list(csv.DictReader(open(tmp_path / "agent_b2" / "batch" / "B2_1" / "worklist.csv", encoding="utf-8-sig")))
    assert rows[0]["cik"] == "0001743415" and rows[0]["fix_class"] == "subtotal_filter"
    assert [r["source_review_ids"] for r in rows] == ["RVQ_a"]


def test_route_corrections_by_flavor():
    corrections = [
        {"fix_class": "subtotal_filter"}, {"fix_class": "dedup"},
        {"fix_class": "rule_scope"}, {"fix_class": None}, {"fix_class": "classification_fix"},
    ]
    routed = rr.route_corrections(corrections)
    assert len(routed["wrapper_patch"]) == 2   # subtotal_filter + classification_fix
    assert len(routed["post_staging"]) == 1    # dedup
    assert len(routed["rule_track"]) == 1      # rule_scope
    assert len(routed["needs_human"]) == 1     # no fix_class


def test_prepare_trial_wrappers_runs_subtotal_filter(tmp_path):
    cik = "0001633858"
    src = tmp_path / "src"
    src.mkdir()
    (src / f"{cik}.json").write_text(json.dumps({
        "schema_version": "bdc-xbrl-wrapper.v3", "cik": cik,
        "dispatch": {"rule_prefix": "T", "aggregate_markers": ["total investments"]}}), encoding="utf-8")
    corrections = [
        {"cik": cik, "fix_class": "subtotal_filter", "template": {"patterns": ["Leaked Rollup"]},
         "source_review_ids": ["RVQ_x"], "confidence": 0.9},
        {"cik": cik, "fix_class": "classification_fix", "template": {}},  # not implemented -> recorded
    ]
    out = tmp_path / "trial_wrappers"
    audits = rr.prepare_trial_wrappers(cik, corrections, out_wrapper_dir=out, source_wrapper_dir=src)
    by = {a["fix_class"]: a for a in audits}
    assert by["subtotal_filter"]["status"] == "ok"
    assert "leaked rollup" in by["subtotal_filter"]["patterns_added"]
    assert by["classification_fix"]["status"] == "not_implemented"
    assert (out / f"{cik}.json").exists()


def test_build_trial_command_shape():
    cmd = rr.build_trial_command("0001633858", wrapper_dir="/w", corrections_dir="/c", stage=1,
                                 python="py")
    assert cmd[:3] == ["py", str(rr.TRIAL_REBUILD), "--cik"] or cmd[0] == "py"
    assert "--wrapper-dir" in cmd and "--corrections" in cmd and "--stage" in cmd
    # no wrapper/corrections -> minimal command
    bare = rr.build_trial_command("0001633858", python="py")
    assert "--wrapper-dir" not in bare and "--corrections" not in bare


def test_apply_packet_prepares_without_running(tmp_path):
    cik = "0001633858"
    cdir = tmp_path / "corrections" / cik
    cdir.mkdir(parents=True)
    (cdir / "dedup.json").write_text(json.dumps({
        "cik": cik, "fix_class": "dedup",
        "template": {"match_fields": ["issuer_name", "report_date", "period"]}}), encoding="utf-8")
    res = rr.apply_packet("B2_apply", cik, base_dir=tmp_path / "agent_b2",
                          corrections_dir=tmp_path / "corrections", run=False)
    assert res["ran"] is False
    assert res["n_post_staging"] == 1
    # post-staging present -> the trial command passes the corrections dir
    assert "--corrections" in res["trial_command"]


def test_promote_copies_only_pass(tmp_path):
    corr = tmp_path / "corrections" / "0001743415"
    corr.mkdir(parents=True)
    (corr / "subtotal_leak.json").write_text(json.dumps({"cik": "0001743415"}), encoding="utf-8")
    (corr / "rate_scale.json").write_text(json.dumps({"cik": "0001743415"}), encoding="utf-8")
    overrides = tmp_path / "overrides"
    promoted = rr.promote_passes(
        [{"cik": "0001743415", "mechanism": "subtotal_leak", "verdict": "PASS"},
         {"cik": "0001743415", "mechanism": "rate_scale", "verdict": "FAIL"}],
        corrections_dir=tmp_path / "corrections", overrides_dir=overrides)
    assert len(promoted) == 1
    assert (overrides / "0001743415" / "subtotal_leak.json").exists()
    assert not (overrides / "0001743415" / "rate_scale.json").exists()
