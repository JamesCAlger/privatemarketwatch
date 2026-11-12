"""scripts/migrate_decision_store.py on fixture files."""
import json

import pytest

from pipeline import decision_store as ds
from scripts import migrate_decision_store as mig

CIK = "0001234567"


@pytest.fixture
def sources(tmp_path):
    reports = tmp_path / "reports"
    reviews = tmp_path / "reviews"
    verdicts = tmp_path / "verdicts"
    for d in (reports, reviews, verdicts):
        d.mkdir()
    (reports / (CIK + ".json")).write_text(json.dumps({
        "cik": CIK, "label": "sbx1", "investigator_id": "fund agent 1",
        "investigations": [
            {"finding_id": "RVQ_BLK_aaaaaaaaaaaa", "conclusion": "false_alarm", "rule_name": "A01",
             "report_date": "2025-12-31", "next_action": "check repair",
             "evidence": [{"accession": "0000000000-26-000001", "text": "Total Software 1,234 1,250"},
                          {"accession": "sandbox sbx1", "text": "published 1,250"}, {"text": ""}]},
            {"finding_id": "RVQ_BLK_bbbbbbbbbbbb", "conclusion": "confirmed_error", "next_action": "fix"},
            {"finding_id": "RVQ_BLK_cccccccccccc", "conclusion": "not a conclusion"},
        ],
        "orchestrator_requests": [{"file": "pipeline/x.py", "what": "repair the check", "why": "misfire"}],
        "request_resolution_history": [
            {"request_id": "REQ-1", "classification": "verification_bug", "resolution": "deferred",
             "original_request": {"file": "pipeline/y.py", "what": "read the dash cell"}},
            {"request_id": "REQ-2", "classification": "acceptance_change", "resolution": "implemented",
             "what": "count the filer industry"},
            {"request_id": "REQ-3", "classification": "verification_bug",
             "resolution": "implemented then reverted: ineffective", "what": "x", "file": "pipeline/z.py"},
        ]}), encoding="utf-8")
    (reviews / (CIK + "_sbx1.json")).write_text(json.dumps({
        "reviewer_id": "reviewer 1", "finding_reviews": [
            {"finding_id": "RVQ_BLK_aaaaaaaaaaaa", "outcome": "supported"},
            {"finding_id": "RVQ_BLK_bbbbbbbbbbbb", "outcome": "rejected"}]}), encoding="utf-8")
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "reason_key,state,engine,rule_name,owner_words,ruled_on,proposal_ids\n"
        "k-accepted,accepted,oracle,A01,Accept it,2026-10-25,PD-1\n"
        "k-rejected,rejected,oracle,B01,Delegated reviewer for the owner: not a disposition,2026-11-12,PD-2\n"
        "k-more,more_evidence,oracle,A01,,,PD-3\n"
        "k-open,proposed,oracle,A01,,,PD-4\n", encoding="utf-8")
    (verdicts / "RVQ_REV_dddddddddddd.json").write_bytes(b'{"verdict": "real_error"}\n')
    return {"report_paths": [reports / (CIK + ".json")], "review_dirs": [reviews], "queue_path": queue,
            "verdict_stores": {"review_queue": verdicts}}


def test_migration_counts_and_content(tmp_path, sources):
    target = tmp_path / "decisions"
    result = mig.migrate(directory=target, **sources)
    assert result["written"] == {"verdict": 2, "check_repair_request": 2, "owner_request": 2, "owner_ruling": 3}  # an unclassified request goes to the owner
    assert result["verdict_files_copied"] == {"review_queue": 1}
    entries = {e.get("request_id") or e.get("reason_key") or e["finding_ids"][0]: e for e in ds.load_native(target)}
    a = entries["RVQ_BLK_aaaaaaaaaaaa"]
    assert (a["conclusion"], a["review_outcome"], a["reviewed_by"]) == ("false_alarm", "supported", "reviewer 1")
    assert a["decided_by"] == "agent:fund_agent_1" and a["quarters"] == ["2025-12-31"]
    assert [e["source"] for e in a["evidence"]] == ["filing", "query"]
    assert entries["RVQ_BLK_bbbbbbbbbbbb"]["review_outcome"] == "rejected"
    assert entries["REQ-1"]["type"] == "check_repair_request" and entries["REQ-1"]["resolution"] == "open"
    assert entries["REQ-1"]["check"] == "pipeline/y.py"
    assert entries["REQ-2"]["type"] == "owner_request" and entries["REQ-2"]["resolution"] == "implemented"
    assert entries["REQ-3"]["resolution"] == "declined"
    assert entries["k-accepted"]["decided_by"] == "owner" and entries["k-accepted"]["ruling"] == "accept"
    assert entries["k-rejected"]["decided_by"] == "delegate:2026-11-12"
    assert entries["k-more"]["ruling"] == "more" and entries["k-more"]["words"].startswith("(no words")
    assert "k-open" not in entries
    copied = target / "verdict_files" / "review_queue" / "RVQ_REV_dddddddddddd.json"
    assert copied.read_bytes() == b'{"verdict": "real_error"}\n'


def test_second_run_is_refused(tmp_path, sources):
    target = tmp_path / "decisions"
    mig.migrate(directory=target, **sources)
    with pytest.raises(SystemExit, match="append-only"):
        mig.migrate(directory=target, **sources)


def test_dry_run_writes_nothing(tmp_path, sources):
    target = tmp_path / "decisions"
    result = mig.migrate(directory=target, dry_run=True, **sources)
    assert result["written"]["verdict"] == 2 and not target.exists()


def test_migrated_verdicts_feed_facts(tmp_path, sources):
    target = tmp_path / "decisions"
    mig.migrate(directory=target, **sources)
    row = {"review_id": "RVQ_BLK_aaaaaaaaaaaa", "cik": CIK, "engine": "oracle", "rule_name": "A01",
           "report_date": "2025-12-31"}
    facts = ds.facts_by_finding(ds.load_native(target), [row])["RVQ_BLK_aaaaaaaaaaaa"]
    assert (facts.conclusion, facts.conclusion_supported) == ("false_alarm", True)
