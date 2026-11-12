"""scripts/status.py: finding status from one batch folder and the decision store."""
import csv
import json

import pytest

from scripts import status as st

CIK, OTHER = "0000000001", "0000000002"
COLUMNS = ["review_id", "state", "status", "cik", "engine", "rule_name", "report_date"]


def row(rid, state, cik=CIK, quarter="2025-12-31", rule="A01"):
    return {"review_id": rid, "state": state, "status": "", "cik": cik, "engine": "oracle",
            "rule_name": rule, "report_date": quarter}


@pytest.fixture
def batch(tmp_path):
    folder = tmp_path / "out" / "batches" / "b1"
    folder.mkdir(parents=True)
    rows = [row("OPEN", "open"), row("REAL", "real_error_unremediated"), row("HUMAN", "needs_human"),
            row("PROP", "open", rule="B01"), row("MISFIRE", "open", rule="D06"), row("FIXED", "remediation_pulled"),
            row("DONE", "adjudicated_false_alarm"), row("OLD", "open", quarter="2021-12-31"),
            row("ELSE", "open", cik=OTHER)]
    with open(folder / "findings_ledger.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (folder / "batch.json").write_text(json.dumps({"batch_id": "b1", "build_time": "2026-11-12T08:00:00",
                                                  "git": "abc1234", "decisions_hash": "feed",
                                                  "quarters": ["2025-12-31", "2026-03-31"]}), encoding="utf-8")
    (folder / "acceptance_2025-12-31.json").write_text(json.dumps({"verdict": "FAIL", "checks": [
        {"id": "reconcile_rate", "actual": 100.0}, {"id": "verified_fv_share", "actual": 99.2},
        {"id": "outstanding_findings", "actual": 3}]}), encoding="utf-8")
    with open(folder / "acceptance_2025-12-31_funds.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["cik", "conservation_status", "conservation_residual_pct", "n_blockers"])
        writer.writeheader()
        writer.writerow({"cik": CIK, "conservation_status": "pass", "conservation_residual_pct": "0.000", "n_blockers": "0"})
    (tmp_path / "out" / "batches" / "latest.json").write_text(json.dumps({"batch_id": "b1"}), encoding="utf-8")
    return tmp_path / "out"


ENTRIES = [
    {"type": "disposition_proposal", "decision_id": "PD-1", "ciks": [CIK], "engine": "oracle", "rule_name": "B01",
     "quarters": ["2025-12-31"], "class": "as_filed", "reason_key": "b01-comparative", "ready": True, "finding_ids": []},
    {"type": "disposition_proposal", "decision_id": "PD-2", "ciks": [CIK], "engine": "oracle", "rule_name": "D06",
     "quarters": ["2025-12-31"], "class": "rule_problem", "reason_key": "d06-punct", "ready": False, "finding_ids": []},
    {"type": "fix_record", "decision_id": "DC-1", "finding_ids": ["FIXED"], "recorded_at": "2026-11-12T10:00:00",
     "expects": {"finding_ids": ["FIXED"], "ciks": [CIK]}},
]


def test_statuses_reasons_and_scope(batch):
    meta, rows, lines = st.build(output_dir=batch, entries=ENTRIES, ciks={CIK})
    got = {r["review_id"]: (r["status"], r["reason"]) for r in rows}
    assert got == {
        "OPEN": ("needs_agent_review", ""),
        "REAL": ("needs_data_fix", ""),
        "HUMAN": ("needs_owner_ruling", "state needs_human"),
        "PROP": ("needs_owner_ruling", "b01-comparative"),
        "MISFIRE": ("needs_check_repair", ""),
        "FIXED": ("fix_awaiting_build", ""),
    }  # DONE is closed, OLD is before 2022, ELSE is outside the cohort
    text = "\n".join(lines)
    assert "Batch `b1`, built 2026-11-12T08:00:00, git abc1234" in text
    assert "**Outstanding: 6**" in text and "Zero outstanding is not data correct." in text
    assert "1 fix record(s) are newer than this batch" in text
    assert "| 2025-12-31 | FAIL | 100.0 | 99.2 | 3 |" in text
    assert "| 2026-03-31 | n/a | n/a | n/a | n/a |" in text  # the gate did not read that quarter
    assert "pass 0.000% / 0 blockers | n/a |" in text
    assert "| `b01-comparative` | 1 |" in text and "| `state needs_human` | 1 |" in text
    assert "Waiting for the owner (2 findings, 2 reasons)" in text


def test_all_funds_and_no_decisions(batch):
    _meta, rows, lines = st.build(output_dir=batch, entries=[], ciks=None)
    got = {r["review_id"]: r["status"] for r in rows}
    assert got["ELSE"] == "needs_agent_review" and got["FIXED"] == "needs_data_fix" and got["PROP"] == "needs_agent_review"
    assert "0 fix record(s) are newer" in "\n".join(lines)


def test_missing_batch_is_an_error_not_a_guess(tmp_path, batch):
    with pytest.raises(SystemExit, match="no batch yet"):
        st.build(output_dir=tmp_path / "empty", entries=[])
    with pytest.raises(SystemExit, match="has no ledger"):
        st.build(output_dir=batch, batch_id="nope", entries=[])


def test_cli_writes_md_and_csv(batch, tmp_path, monkeypatch):
    monkeypatch.setattr(st.decision_store, "load_all", lambda directory=None, **_: ENTRIES)
    out = tmp_path / "docs"
    assert st.main(["--output-dir", str(batch), "--out-dir", str(out), "--all-funds", "--owner-queue"]) == 0
    with open(out / "findings_status.csv", newline="", encoding="utf-8") as fh:
        written = list(csv.DictReader(fh))
    assert len(written) == 7 and set(written[0]) == set(st.OUT_COLUMNS)
    assert (out / "findings_status.md").read_text(encoding="utf-8").startswith("# Finding status")
