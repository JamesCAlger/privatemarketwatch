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
    # 2026-08-13: classification_fix is now a post-staging frame applier; rule_scope
    # is a detector-policy decision routed to the human basket.
    assert len(routed["wrapper_patch"]) == 1   # subtotal_filter
    assert len(routed["post_staging"]) == 2    # dedup + classification_fix
    assert len(routed["rule_track"]) == 0
    assert len(routed["needs_human"]) == 2     # rule_scope + no fix_class


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
    ]
    out = tmp_path / "trial_wrappers"
    audits = rr.prepare_trial_wrappers(cik, corrections, out_wrapper_dir=out, source_wrapper_dir=src)
    by = {a["fix_class"]: a for a in audits}
    assert by["subtotal_filter"]["status"] == "ok"
    assert "leaked rollup" in by["subtotal_filter"]["patterns_added"]
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
        corrections_dir=tmp_path / "corrections", overrides_dir=overrides,
        wrapper_dir=tmp_path / "wrappers")
    assert len(promoted) == 1
    assert (overrides / "0001743415" / "subtotal_leak.json").exists()
    assert not (overrides / "0001743415" / "rate_scale.json").exists()


def test_promote_wrapper_patch_applies_to_production_wrapper(tmp_path):
    """Gap-1 Layer A: a PASS subtotal_filter promotes the PATCHED WRAPPER (with
    provenance) into the wrapper store, not a leaf into the corrections store."""
    cik = "0001743415"
    wrappers = tmp_path / "wrappers"
    wrappers.mkdir()
    (wrappers / f"{cik}.json").write_text(json.dumps(
        {"dispatch": {"aggregate_markers": ["total investments"]}}), encoding="utf-8")
    corr = tmp_path / "corrections" / cik
    corr.mkdir(parents=True)
    (corr / "subtotal_filter.json").write_text(json.dumps(
        {"cik": cik, "fix_class": "subtotal_filter",
         "template": {"patterns": ["total debt investments"]},
         "source_review_ids": ["RVQ_1"], "confidence": 0.9}), encoding="utf-8")
    overrides = tmp_path / "overrides"

    promoted = rr.promote_passes(
        [{"cik": cik, "mechanism": "subtotal_filter", "verdict": "PASS"}],
        corrections_dir=tmp_path / "corrections", overrides_dir=overrides,
        wrapper_dir=wrappers)

    assert len(promoted) == 1
    assert promoted[0]["layer"] == "wrapper_patch"
    assert promoted[0]["status"] == "ok"
    wrapper = json.loads((wrappers / f"{cik}.json").read_text(encoding="utf-8"))
    assert "total debt investments" in wrapper["dispatch"]["aggregate_markers"]
    assert wrapper["b2_provenance"][0]["patterns_added"] == ["total debt investments"]
    assert wrapper["b2_provenance"][0]["source_review_ids"] == ["RVQ_1"]
    # The leaf must NOT land in the corrections override store (wrong layer).
    assert not (overrides / cik / "subtotal_filter.json").exists()

    # Re-promotion is a recorded no-op: no duplicate provenance, wrapper unchanged.
    promoted2 = rr.promote_passes(
        [{"cik": cik, "mechanism": "subtotal_filter", "verdict": "PASS"}],
        corrections_dir=tmp_path / "corrections", overrides_dir=overrides,
        wrapper_dir=wrappers)
    assert promoted2[0]["status"] == "noop"
    wrapper2 = json.loads((wrappers / f"{cik}.json").read_text(encoding="utf-8"))
    assert len(wrapper2["b2_provenance"]) == 1


# --------------------------------------------------------------------------- value gate (2026-08-13)


def _vg_frame():
    return pd.DataFrame([
        {"issuer_name": "Alpha Corp", "report_date": "2025-12-31", "fair_value": 1000.0,
         "interest_rate": 0.105, "pik_rate": None, "basis_spread": 5.0,
         "asset_class": "PRIVATE_CREDIT"},
        {"issuer_name": "Beta LLC", "report_date": "2025-12-31", "fair_value": 2000.0,
         "interest_rate": 11.5, "pik_rate": 2.0, "basis_spread": 6.0,
         "asset_class": "PRIVATE_CREDIT"},
    ])


def _vg_corr(**kw):
    base = {"cik": "0000000100", "fix_class": "rate_rescale",
            "template": {"field": "interest_rate", "factor": 100,
                         "row_selector": {"issuer_name": "Alpha Corp"}}}
    base.update(kw)
    return base


def test_value_gate_passes_on_exact_replay():
    from pipeline.agent_b2_appliers import apply_rate_rescale
    base = _vg_frame()
    trial, _ = apply_rate_rescale(base, _vg_corr()["template"])
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=trial, correction=_vg_corr())
    assert res["verdict"] == "PASS", res["reasons"]
    assert res["checks"]["replay_equivalence"] is True


def test_value_gate_fails_on_off_target_drift():
    from pipeline.agent_b2_appliers import apply_rate_rescale
    base = _vg_frame()
    trial, _ = apply_rate_rescale(base, _vg_corr()["template"])
    trial = trial.copy()
    trial.loc[trial["issuer_name"] == "Beta LLC", "fair_value"] = 2500.0  # unrelated edit
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=trial, correction=_vg_corr())
    assert res["verdict"] == "FAIL"
    assert res["checks"]["replay_equivalence"] is False


def test_value_gate_fails_on_noop_correction():
    # Stale-fix guard: a correction that changes nothing on the baseline must not promote.
    base = _vg_frame()
    corr = _vg_corr()
    corr["template"] = {"field": "interest_rate", "factor": 100,
                        "row_selector": {"issuer_name": "No Such Issuer"}}
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=base.copy(), correction=corr)
    assert res["verdict"] == "FAIL"
    assert res["checks"]["replay_ok"] is False


def test_value_gate_fails_on_out_of_bounds_rate():
    from pipeline.agent_b2_appliers import apply_rate_rescale
    base = _vg_frame()
    corr = _vg_corr()
    corr["template"] = {"field": "interest_rate", "factor": 1000,
                        "row_selector": {"issuer_name": "Alpha Corp"}}  # 0.105 -> 105
    trial, _ = apply_rate_rescale(base, corr["template"])
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=trial, correction=corr)
    assert res["verdict"] == "FAIL"
    assert res["checks"]["field_sanity"] is False


def test_value_gate_missing_position_add_fails_closed_without_grounding():
    from pipeline.agent_b2_appliers import apply_missing_position_add
    base = _vg_frame()
    corr = {"cik": "0000000100", "fix_class": "missing_position_add",
            "template": {"positions": [{"issuer_name": "Gamma Bill", "fair_value": 500.0,
                                        "report_date": "2025-12-31",
                                        "source_row_id": "SRC-42",
                                        "bdc_dimensions_raw": "investmentidentifieraxis=Gamma"}]}}
    trial, _ = apply_missing_position_add(base, corr["template"])
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=trial, correction=corr)
    assert res["verdict"] == "FAIL"
    assert res["checks"]["grounding_verified"] is False


def test_value_gate_missing_position_add_passes_with_grounding():
    from pipeline.agent_b2_appliers import apply_missing_position_add
    base = _vg_frame()
    corr = {"cik": "0000000100", "fix_class": "missing_position_add",
            "template": {"positions": [{"issuer_name": "Gamma Bill", "fair_value": 500.0,
                                        "report_date": "2025-12-31",
                                        "source_row_id": "SRC-42",
                                        "bdc_dimensions_raw": "investmentidentifieraxis=Gamma"}]}}
    trial, _ = apply_missing_position_add(base, corr["template"])
    grounding = pd.DataFrame([{"source_row_id": "SRC-42", "fair_value": 500.0}])
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=trial, correction=corr,
                               grounding_df=grounding)
    assert res["verdict"] == "PASS", res["reasons"]


def test_value_gate_grounding_fv_mismatch_fails():
    from pipeline.agent_b2_appliers import apply_missing_position_add
    base = _vg_frame()
    corr = {"cik": "0000000100", "fix_class": "missing_position_add",
            "template": {"positions": [{"issuer_name": "Gamma Bill", "fair_value": 500000.0,
                                        "report_date": "2025-12-31",
                                        "source_row_id": "SRC-42",
                                        "bdc_dimensions_raw": "investmentidentifieraxis=Gamma"}]}}
    trial, _ = apply_missing_position_add(base, corr["template"])
    grounding = pd.DataFrame([{"source_row_id": "SRC-42", "fair_value": 500.0}])
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=trial, correction=corr,
                               grounding_df=grounding)
    assert res["verdict"] == "FAIL"
    assert res["checks"]["grounding_verified"] is False


# ------------------------------------------------- magnitude plausibility (round 4)
# Modeled on the q4b2exp_v3 magnitude pulls: quarter-scoped but UNSELECTED
# rescales/remaps that pushed a whole quarter 10x-1000x off the fund's own norm while
# staying inside the absolute _FIELD_BOUNDS.

_MQ = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]


def _mag_frame(target_rate=None, target_principal=None, target_pct=0.2):
    """4 quarters x 4 rows; rates ~10, principal ~ fair_value ~1000 (ratio ~1)."""
    rows = []
    for q in _MQ:
        for i in range(4):
            rate = (target_rate if (target_rate is not None and q == "2025-12-31")
                    else 9.0 + i)
            principal = (target_principal if (target_principal is not None and q == "2025-12-31")
                         else 950.0 + 30 * i)
            rows.append({"issuer_name": f"Issuer {i}", "report_date": q,
                         "fair_value": 1000.0 + 10 * i, "cost": 990.0 + 10 * i,
                         "principal_amount": principal, "interest_rate": rate,
                         "pik_rate": None, "basis_spread": 5.0,
                         "pct_of_net_assets": target_pct + 0.05 * i,
                         "asset_class": "PRIVATE_CREDIT"})
    return pd.DataFrame(rows)


def _scoped(corr):
    corr["scope"] = {"quarters": ["2025-12-31"]}
    return corr


def _gate_scoped(base, corr):
    from pipeline.agent_b2_appliers import apply_scoped
    trial, audit = apply_scoped(base, corr)
    assert audit.get("status") == "ok", audit
    return rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                                baseline_df=base, trial_df=trial, correction=corr)


def test_magnitude_gate_refuses_unselected_principal_x1000():
    # 1572694 shape: evidence cites 2 FX rows, fix multiplies EVERY row's principal.
    base = _mag_frame()
    corr = _scoped({"cik": "0000000100", "fix_class": "unit_rescale",
                    "template": {"field": "principal_amount", "factor": 1000}})
    res = _gate_scoped(base, corr)
    assert res["checks"]["magnitude_plausible"] is False
    assert res["verdict"] == "FAIL"
    assert any("principal" in r for r in res["reasons"])


def test_magnitude_gate_refuses_unselected_rate_div100():
    # 1646614 shape: interest_rate x0.01 across the quarter; post-fix values (~0.1)
    # are INSIDE the absolute bounds, so only the fund-norm comparison catches it.
    base = _mag_frame()
    corr = _scoped({"cik": "0000000100", "fix_class": "unit_rescale",
                    "template": {"field": "interest_rate", "factor": 0.01}})
    res = _gate_scoped(base, corr)
    assert res["checks"]["field_sanity"] is True
    assert res["checks"]["magnitude_plausible"] is False
    assert res["verdict"] == "FAIL"


def test_magnitude_gate_refuses_remap_pct_into_rate():
    # 1508655 shape: pct_of_net_assets (~0.2) remapped into interest_rate (norm ~10).
    base = _mag_frame()
    corr = _scoped({"cik": "0000000100", "fix_class": "column_remap",
                    "template": {"from_field": "pct_of_net_assets",
                                 "to_field": "interest_rate"}})
    res = _gate_scoped(base, corr)
    assert res["checks"]["magnitude_plausible"] is False
    assert res["verdict"] == "FAIL"


def test_magnitude_gate_passes_scale_repair():
    # The legitimate direction: the target quarter's rates were stored /100 (0.09-0.12
    # vs fund norm ~10); rate_rescale x100 REPAIRS the magnitude defect.
    base = _mag_frame(target_rate=0.105)
    corr = _scoped({"cik": "0000000100", "fix_class": "rate_rescale",
                    "template": {"field": "interest_rate", "factor": 100}})
    res = _gate_scoped(base, corr)
    assert res["checks"]["magnitude_plausible"] is True, res["reasons"]
    assert res["verdict"] == "PASS", res["reasons"]


def test_magnitude_gate_passes_selected_single_row_fix():
    # An issuer-selected fix moves one row of four: the quarter average stays within
    # one order of magnitude of the norm; bounded fixes are not refused.
    base = _mag_frame()
    corr = _scoped({"cik": "0000000100", "fix_class": "rate_rescale",
                    "template": {"field": "interest_rate", "factor": 0.01,
                                 "row_selector": {"issuer_name": "Issuer 0"}}})
    res = _gate_scoped(base, corr)
    assert res["checks"]["magnitude_plausible"] is True, res["reasons"]


def test_magnitude_gate_vacated_from_field_not_a_break():
    # A remap that vacates from_field in the target quarter is a remap consequence,
    # not a magnitude break; the newly populated to_field lands on the norm.
    rows = []
    for q in _MQ:
        for i in range(4):
            principal = None if q == "2025-12-31" else 950.0 + 30 * i
            shares = (950.0 + 30 * i) if q == "2025-12-31" else None
            rows.append({"issuer_name": f"Issuer {i}", "report_date": q,
                         "fair_value": 1000.0, "principal_amount": principal,
                         "shares_held": shares, "interest_rate": 10.0})
    base = pd.DataFrame(rows)
    corr = _scoped({"cik": "0000000100", "fix_class": "column_remap",
                    "template": {"from_field": "shares_held",
                                 "to_field": "principal_amount"}})
    res = _gate_scoped(base, corr)
    assert res["checks"]["magnitude_plausible"] is True, res["reasons"]


def test_magnitude_gate_changed_row_leg_catches_blended_remap():
    # 1508655 shape on real data: most rows get small remapped values, a minority keep
    # in-band rates, so the QUARTER average stays inside 10x -- but the rows the fix
    # actually wrote land an order of magnitude off the norm.
    rows = []
    for q in _MQ:
        for i in range(10):
            has_pct = i < 7
            rows.append({"issuer_name": f"Issuer {i}", "report_date": q,
                         "fair_value": 1000.0, "interest_rate": 10.5 + 0.1 * i,
                         "pct_of_net_assets": (0.7 + 0.02 * i) if has_pct else None})
    base = pd.DataFrame(rows)
    corr = _scoped({"cik": "0000000100", "fix_class": "column_remap",
                    "template": {"from_field": "pct_of_net_assets",
                                 "to_field": "interest_rate"}})
    from pipeline.agent_b2_appliers import apply_scoped
    trial, _ = apply_scoped(base, corr)
    # quarter average post-fix: (7 * ~0.77 + 3 * ~11) / 10 ~= 3.8 -> inside 10x of ~11
    ok, reasons = rr.check_magnitude_plausibility(
        baseline_df=base, trial_df=trial, correction=corr, target_quarter="2025-12-31")
    assert ok is False
    assert any("changed-row" in r for r in reasons)


def test_magnitude_check_skips_without_fund_norm():
    # Only one off-target quarter -> no norm -> the predicate abstains (other gate
    # checks still apply); it must not fabricate a refusal from thin history.
    base = _mag_frame()
    base = base[base["report_date"].isin(["2025-09-30", "2025-12-31"])].reset_index(drop=True)
    corr = _scoped({"cik": "0000000100", "fix_class": "unit_rescale",
                    "template": {"field": "principal_amount", "factor": 1000}})
    from pipeline.agent_b2_appliers import apply_scoped
    trial, _ = apply_scoped(base, corr)
    ok, reasons = rr.check_magnitude_plausibility(
        baseline_df=base, trial_df=trial, correction=corr, target_quarter="2025-12-31")
    assert ok is True and reasons == []


def test_magnitude_check_ratio_leg_catches_principal_break_when_fund_grows():
    # Dollar averages legitimately drift with portfolio growth, but the per-row
    # principal/FV ratio does not: a x1000 principal rescale must still be refused
    # when the fund tripled in size across quarters.
    rows = []
    for k, q in enumerate(_MQ):
        scale = (1 + k)  # fund grows 4x over the year
        for i in range(4):
            rows.append({"issuer_name": f"Issuer {i}", "report_date": q,
                         "fair_value": scale * (1000.0 + 10 * i),
                         "principal_amount": scale * (950.0 + 30 * i),
                         "interest_rate": 10.0})
    base = pd.DataFrame(rows)
    corr = _scoped({"cik": "0000000100", "fix_class": "unit_rescale",
                    "template": {"field": "principal_amount", "factor": 1000}})
    from pipeline.agent_b2_appliers import apply_scoped
    trial, _ = apply_scoped(base, corr)
    ok, reasons = rr.check_magnitude_plausibility(
        baseline_df=base, trial_df=trial, correction=corr, target_quarter="2025-12-31")
    assert ok is False
    assert any("principal/FV" in r for r in reasons)


# ---------------------------------------------------------------------------
# Re-adjudication worklist (wrong-diagnosis loop, 2026-08-21)
# ---------------------------------------------------------------------------

class TestReadjudicationWorklist:
    def test_is_diagnosis_refusal_on_magnitude_check_false(self):
        assert rr.is_diagnosis_refusal(
            {"verdict": "FAIL", "checks": {"magnitude_plausible": False}, "reasons": []})

    def test_is_diagnosis_refusal_on_rate_signature_reason(self):
        assert rr.is_diagnosis_refusal(
            {"verdict": "FAIL", "checks": {"replay_ok": True},
             "reasons": ["rate signature already plausible before fix"]})

    def test_is_diagnosis_refusal_false_on_authoring_fail(self):
        # replay-equivalence failure = B2 authoring defect, NOT a B1 diagnosis defect
        assert not rr.is_diagnosis_refusal(
            {"verdict": "FAIL", "checks": {"replay_equivalence": False,
                                           "magnitude_plausible": True},
             "reasons": ["trial does not match applier(baseline)"]})
        assert not rr.is_diagnosis_refusal(
            {"verdict": "PASS", "checks": {"magnitude_plausible": False}, "reasons": []})

    def _entry(self, rid="RVQ_BLK_x", fc="unit_rescale", cik="0001234567"):
        return {"cik": cik, "fix_class": fc, "source_review_ids": rid,
                "batch_id": "b1", "gated_utc": "2026-08-21T00:00:00+00:00",
                "reason": "magnitude_plausible false"}

    def test_append_readjudication_dedupes_by_review_id_and_fix_class(self, tmp_path):
        p = tmp_path / "readju.csv"
        assert rr.append_readjudication([self._entry()], path=p) == 1
        # same (review_id, fix_class) pair again -> no-op
        assert rr.append_readjudication([self._entry()], path=p) == 0
        # same review_id but different fix_class -> new row
        assert rr.append_readjudication([self._entry(fc="column_remap")], path=p) == 1
        rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
        assert len(rows) == 2
        assert {r["fix_class"] for r in rows} == {"unit_rescale", "column_remap"}

    def test_append_readjudication_is_append_only(self, tmp_path):
        p = tmp_path / "readju.csv"
        rr.append_readjudication([self._entry()], path=p)
        before = p.read_text(encoding="utf-8")
        rr.append_readjudication([self._entry(rid="RVQ_BLK_y")], path=p)
        after = p.read_text(encoding="utf-8")
        assert after.startswith(before)          # existing rows never rewritten
        assert after.count("\n") == before.count("\n") + 1
