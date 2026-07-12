"""Tests for the agentic driver's orchestration: discover (B1 -> investigation targets) and
promote (gate-PASS rules -> overrides). Steps 3-4 of the B2 consolidation."""
import json

from scripts.agent_investigate.run_investigation import _discover_targets, promote


def _b1_fixture(tmp_path):
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    (verdicts / "R1.json").write_text(json.dumps({"verdict": "real_error", "mechanism": "subtotal_leak"}))
    (verdicts / "R2.json").write_text(json.dumps({"verdict": "false_alarm"}))
    (verdicts / "R3.json").write_text(json.dumps({"verdict": "real_error"}))
    wl = tmp_path / "worklist.csv"
    wl.write_text(
        "review_id,cik,report_date,rule_name\n"
        "R1,0001920453,2024-03-31,fv_conservation\n"        # real_error -> target
        "R2,0001920453,2024-06-30,fv_conservation\n"        # false_alarm -> skipped
        "R3,0001715933,2025-12-31,fv_conservation\n"        # real_error -> target
        ",0001603480,2025-06-30,fv_conservation\n"          # no review_id -> skipped
    )
    return wl, verdicts


def test_discover_selects_only_real_errors(tmp_path):
    wl, verdicts = _b1_fixture(tmp_path)
    targets = _discover_targets(wl, verdicts)
    assert set(targets) == {("1920453", "2024-03-31"), ("1715933", "2025-12-31")}
    assert targets[("1920453", "2024-03-31")] == {"R1"}            # false_alarm R2 excluded


def test_discover_dedupes_multiple_verdicts_per_target(tmp_path):
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    for r in ("R1", "R2"):
        (verdicts / f"{r}.json").write_text(json.dumps({"verdict": "real_error"}))
    wl = tmp_path / "worklist.csv"
    wl.write_text("review_id,cik,report_date\nR1,0001920453,2024-03-31\nR2,0001920453,2024-03-31\n")
    targets = _discover_targets(wl, verdicts)
    assert set(targets) == {("1920453", "2024-03-31")}
    assert targets[("1920453", "2024-03-31")] == {"R1", "R2"}      # one target, both review_ids


def test_promote_refuses_without_gate_pass(tmp_path):
    # No corrected holdings for a fake cik -> gate is not PASS -> promote must refuse (no copy).
    res = promote("9999999999", "2025-12-31", overrides_dir=tmp_path)
    assert res["status"] == "refused" and res.get("gate") != "PASS"
    assert not any(tmp_path.iterdir())                             # nothing written to overrides
