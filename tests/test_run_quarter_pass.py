"""Tests for the checkpointed quarter-pass runbook (scripts/run_quarter_pass.py)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pipeline import config
from scripts.run_quarter_pass import Runner, _stages

Q = "2025-12-31"


def _runner(tmp_path: Path, executed: list[list[str]], *, fail_on: str | None = None):
    def fake_run(argv: list[str], log_path: Path) -> int:
        executed.append(argv)
        log_path.write_text("", encoding="utf-8")
        return 1 if (fail_on and fail_on in " ".join(argv)) else 0

    return Runner("t1", Q, run_cmd=fake_run, pass_base=tmp_path / "passes")


def test_stage_order_pre_dispatch_ends_at_select():
    names = [s.name for s in _stages(Q)]
    assert names[:8] == ["rebuild", "oracle", "nonaccrual", "validate", "shadow",
                         "queue", "acceptance", "select"]
    assert names[8:] == ["rebuild_post", "oracle_post", "nonaccrual_post",
                         "validate_post", "shadow_post", "queue_post",
                         "acceptance_post", "summary"]


def test_acceptance_verdict_exit_codes_are_outcomes():
    stages = {s.name: s for s in _stages(Q)}
    assert stages["acceptance"].allowed_exit == (0, 1, 2)
    assert stages["acceptance_post"].allowed_exit == (0, 1, 2)
    assert stages["rebuild"].allowed_exit == (0,)


def test_until_select_runs_pre_half_and_checkpoints(tmp_path, monkeypatch):
    funds = tmp_path / "funds.csv"
    with funds.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["cik", "entity_name", "fund_fv_m", "tier"])
        w.writeheader()
        w.writerow({"cik": "0000000001", "entity_name": "Small", "fund_fv_m": "10.0",
                    "tier": "under_review"})
        w.writerow({"cik": "0000000002", "entity_name": "Big", "fund_fv_m": "999.0",
                    "tier": "under_review"})
        w.writerow({"cik": "0000000003", "entity_name": "Clean", "fund_fv_m": "5.0",
                    "tier": "verified"})
    monkeypatch.setattr(config, "QUARTER_ACCEPTANCE_FUNDS_FILE", funds)
    monkeypatch.setattr(config, "QUARTER_ACCEPTANCE_FILE", tmp_path / "qa.json")

    executed: list[list[str]] = []
    r = _runner(tmp_path, executed)
    assert r.run(until_stage="select") == 0
    # 7 subprocess stages ran (select is a function stage)
    assert len(executed) == 7
    assert "rebuild_outputs.py" in " ".join(executed[0])

    state = json.loads(r.state_path.read_text(encoding="utf-8"))
    assert state["stages"]["select"]["status"] == "completed"
    assert "rebuild_post" not in state["stages"]

    # candidates ranked by FV desc, verified funds excluded
    with (r.pass_dir / "candidates.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [row["cik"] for row in rows] == ["0000000002", "0000000001"]


def test_completed_stages_skip_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "QUARTER_ACCEPTANCE_FILE", tmp_path / "qa.json")
    executed: list[list[str]] = []
    r = _runner(tmp_path, executed)
    assert r.run(until_stage="queue") == 0
    n_first = len(executed)
    r2 = _runner(tmp_path, executed)
    assert r2.run(until_stage="queue") == 0
    assert len(executed) == n_first  # nothing re-ran


def test_failed_stage_halts_and_records(tmp_path):
    executed: list[list[str]] = []
    r = _runner(tmp_path, executed, fail_on="oracle_runner")
    assert r.run(until_stage="queue") == 1
    state = json.loads(r.state_path.read_text(encoding="utf-8"))
    assert state["stages"]["oracle"]["status"] == "failed"
    assert "validate" not in state["stages"]  # halted at the failure


def test_from_resumes_post_dispatch_half(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "QUARTER_ACCEPTANCE_FILE", tmp_path / "qa.json")
    executed: list[list[str]] = []
    r = _runner(tmp_path, executed)
    assert r.run(from_stage="rebuild_post", until_stage="queue_post") == 0
    state = json.loads(r.state_path.read_text(encoding="utf-8"))
    assert "rebuild" not in state["stages"]  # pre half untouched
    assert state["stages"]["rebuild_post"]["status"] == "completed"


def test_summary_diffs_pre_and_post(tmp_path):
    executed: list[list[str]] = []
    r = _runner(tmp_path, executed)
    r.pass_dir.mkdir(parents=True)

    def _acc(verdict, flagged_share, checks_fail):
        return {
            "verdict": verdict,
            "metrics": {"conservation": {"flagged_fv_share_pct": flagged_share,
                                         "n_flagged": 14 if flagged_share > 30 else 8}},
            "checks": [{"id": "flagged_fv_share", "pass": not checks_fail}],
        }

    (r.pass_dir / "acceptance_pre.json").write_text(
        json.dumps(_acc("FAIL", 43.99, True)), encoding="utf-8")
    (r.pass_dir / "acceptance_post.json").write_text(
        json.dumps(_acc("PASS", 18.2, False)), encoding="utf-8")
    r.summarize_pass()
    summary = json.loads((r.pass_dir / "pass_summary.json").read_text(encoding="utf-8"))
    assert summary["verdict_pre"] == "FAIL" and summary["verdict_post"] == "PASS"
    assert summary["metric_deltas"]["conservation.flagged_fv_share_pct"] == -25.79
    assert summary["checks_pre_fail"] == ["flagged_fv_share"]
    assert summary["checks_post_fail"] == []


def test_dry_run_executes_nothing(tmp_path):
    executed: list[list[str]] = []

    def fake_run(argv, log_path):  # pragma: no cover - must not be called
        executed.append(argv)
        return 0

    r = Runner("t2", Q, dry_run=True, run_cmd=fake_run, pass_base=tmp_path / "passes")
    assert r.run() == 0
    assert executed == []
    assert not r.state_path.exists()
