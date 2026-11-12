"""scripts/run_batch.py with the stage commands stubbed: what is written, and when the pointer moves."""
import csv
import json
from pathlib import Path

import pytest

from pipeline import decision_store
from scripts import run_batch as rb

LEDGER_COLUMNS = ["review_id", "state", "status", "cik", "engine", "rule_name", "report_date"]


class Runner:
    """Stands in for run_command: records each call, writes the ledger when asked to."""

    def __init__(self, ledger_rows=(), fail=None):
        self.calls = []
        self.ledger_rows = list(ledger_rows)
        self.fail = fail

    def __call__(self, argv, *, log_path, output_dir):
        name = Path(log_path).stem
        self.calls.append(name)
        Path(log_path).write_text("stub\n", encoding="utf-8")
        if name == self.fail:
            return 5
        if "scripts/findings_ledger.py" in argv:
            out = Path(argv[argv.index("--out") + 1])
            with open(out, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=LEDGER_COLUMNS)
                writer.writeheader()
                writer.writerows(self.ledger_rows)
            return 1  # findings remain
        return 0


def row(rid, state, status):
    return {"review_id": rid, "state": state, "status": status, "cik": "0000000001", "engine": "oracle",
            "rule_name": "A01", "report_date": "2025-12-31"}


def go(tmp_path, batch_id, runner, **kwargs):
    kwargs.setdefault("quarters", ["2025-12-31"])
    kwargs.setdefault("decisions_dir", tmp_path / "decisions")
    return rb.run_batch(batch_id=batch_id, output_dir=tmp_path / "out", run=runner, memory=lambda: 64.0,
                        busy=lambda: False, cohort=lambda: ["0000000001"], say=lambda *_: None, **kwargs)


def test_a_full_batch_writes_everything_and_moves_the_pointer(tmp_path):
    runner = Runner([row("A", "open", "needs_agent_review")])
    assert go(tmp_path, "b1", runner) == 0
    batch = tmp_path / "out" / "batches" / "b1"
    assert runner.calls[:3] == ["extract", "fieldstatus", "highlights"]
    assert runner.calls.index("unified") < runner.calls.index("validate") < runner.calls.index("ledger")
    for name in ("findings_ledger.csv", "compare.csv", "batch.json", "ledger.log", "gate_2025-12-31.log", "reattest.log"):
        assert (batch / name).exists(), name
    meta = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    assert meta["compare"]["first_batch"] and meta["finished"]
    assert [s["stage"] for s in meta["stages"]][-3:] == ["compare", "gate 2025-12-31", "reattest"]
    assert rb.latest(tmp_path / "out")["batch_id"] == "b1"


def test_a_failing_stage_stops_the_batch_and_leaves_the_pointer(tmp_path):
    assert go(tmp_path, "b1", Runner([row("A", "open", "needs_agent_review")])) == 0
    runner = Runner([row("A", "open", "needs_agent_review")], fail="unified")
    assert go(tmp_path, "b2", runner) == 1
    assert runner.calls[-1] == "unified" and "validate" not in runner.calls
    assert not (tmp_path / "out" / "batches" / "b2" / "findings_ledger.csv").exists()
    assert rb.latest(tmp_path / "out")["batch_id"] == "b1"


def test_a_failing_ledger_stage_leaves_the_pointer(tmp_path):
    assert go(tmp_path, "b1", Runner([row("A", "open", "needs_agent_review")])) == 0
    assert go(tmp_path, "b2", Runner(fail="ledger"), start="ledger") == 1
    assert rb.latest(tmp_path / "out")["batch_id"] == "b1"


def test_low_memory_stops_before_the_stage_runs(tmp_path):
    runner = Runner()
    code = rb.run_batch(batch_id="b1", output_dir=tmp_path / "out", quarters=[], run=runner, memory=lambda: 9.0,
                        busy=lambda: False, cohort=lambda: [], say=lambda *_: None,
                        decisions_dir=tmp_path / "decisions")
    assert code == 1 and "unified" not in runner.calls and runner.calls[-1] == "financials"
    assert rb.latest(tmp_path / "out") == {}


def test_an_existing_batch_or_a_busy_machine_is_refused(tmp_path):
    assert go(tmp_path, "b1", Runner([row("A", "open", "needs_agent_review")])) == 0
    again = Runner()
    assert go(tmp_path, "b1", again) == 2 and again.calls == []
    busy = Runner()
    code = rb.run_batch(batch_id="b3", output_dir=tmp_path / "out", quarters=[], run=busy, memory=lambda: 64.0,
                        busy=lambda: True, cohort=lambda: [], say=lambda *_: None)
    assert code == 3 and busy.calls == [] and not (tmp_path / "out" / "batches" / "b3").exists()


def test_dry_run_writes_nothing(tmp_path):
    lines = []
    code = rb.run_batch(batch_id="b1", output_dir=tmp_path / "out", quarters=[], dry_run=True, say=lines.append,
                        run=Runner(), busy=lambda: True)
    assert code == 0 and not (tmp_path / "out").exists()
    assert any(line.startswith("unified") and "14 GB" in line for line in lines)
    assert any(line.startswith("ledger") for line in lines)


def test_from_ledger_runs_only_the_tail_and_compares_with_the_previous_batch(tmp_path):
    decisions = tmp_path / "decisions"
    assert go(tmp_path, "b1", Runner([row("A", "real_error_unremediated", "needs_data_fix"),
                                      row("B", "open", "needs_agent_review")])) == 0
    decision_store.append({"type": "fix_record", "cik": "0000000001", "finding_ids": ["A"], "quarters": [],
                           "statement": "fixed", "evidence": [], "files": ["w.json"], "tested_in": "sbx",
                           "expects": {"finding_ids": ["A"], "ciks": ["0000000001"]},
                           "decided_by": "agent:a", "decided_on": "2026-11-12"},
                          actor="agent:a", directory=decisions)
    runner = Runner([row("A", "remediated_promoted", "closed"), row("N", "open", "needs_agent_review")])
    assert go(tmp_path, "b2", runner, start="ledger", until="compare") == 0
    assert runner.calls == ["disposition_validity", "ledger"]
    batch = tmp_path / "out" / "batches" / "b2"
    with open(batch / "compare.csv", newline="", encoding="utf-8") as fh:
        outcomes = {r["review_id"]: r["outcome"] for r in csv.DictReader(fh)}
    assert outcomes == {"A": "fixed", "B": "closed_other", "N": "new_finding"}
    meta = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    assert meta["compare"]["previous_batch"] == "b1" and meta["compare"]["fix_records"] == 1
    assert rb.latest(tmp_path / "out")["batch_id"] == "b2"


def test_skip_and_bad_batch_id(tmp_path):
    runner = Runner([row("A", "open", "needs_agent_review")])
    assert go(tmp_path, "b1", runner, skip=("frontend", "reattest")) == 0
    assert "frontend" not in runner.calls and "reattest" not in runner.calls
    with pytest.raises(SystemExit):
        rb.main(["--batch-id", "bad id", "--dry-run"])
