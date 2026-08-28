"""Tests for the findings lifecycle ledger (scripts/findings_ledger.py)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import findings_ledger as fl


# ------------------------------------------------------------- classify_finding

def _cls(rid="RVQ_x", *, in_queue=True, verdict_status="MISSING",
         staged=(), promoted=(), pulled=()):
    return fl.classify_finding(rid, in_queue=in_queue, verdict_status=verdict_status,
                               staged_ids=set(staged), promoted_ids=set(promoted),
                               pulled_ids=set(pulled))


def test_classify_state_matrix():
    assert _cls(verdict_status="MISSING") == "open"
    assert _cls(verdict_status="MISSING", in_queue=False) == "gone_unadjudicated"
    assert _cls(verdict_status="invalid_verdict") == "open"
    assert _cls(verdict_status="placeholder_autodrafted") == "open"
    assert _cls(verdict_status="no_source_not_covered") == "evidence_backlog"
    assert _cls(verdict_status="verdict_false_alarm") == "adjudicated_false_alarm"
    assert _cls(verdict_status="verdict_NO_PATCH_NEEDED") == "adjudicated_false_alarm"
    assert _cls(verdict_status="verdict_INSUFFICIENT_EVIDENCE") == "evidence_backlog"
    assert _cls(verdict_status="verdict_ambiguous") == "needs_human"
    assert _cls(verdict_status="verdict_anchor_bad") == "needs_human"
    assert _cls(verdict_status="verdict_ESCALATE") == "needs_human"
    assert _cls(verdict_status="verdict_PATCH_PROPOSED") == "needs_human"


def test_classify_real_error_remediation_precedence():
    rid = "RVQ_r"
    v = "verdict_real_error"
    assert _cls(rid, verdict_status=v) == "real_error_unremediated"
    assert _cls(rid, verdict_status=v, staged=[rid]) == "remediation_staged"
    assert _cls(rid, verdict_status=v, promoted=[rid]) == "remediated_promoted"
    # promoted wins over staged (a re-author may be staged while v1 is live)
    assert _cls(rid, verdict_status=v, staged=[rid], promoted=[rid]) == "remediated_promoted"
    assert _cls(rid, verdict_status=v, pulled=[rid]) == "remediation_pulled"
    assert _cls(rid, verdict_status=v, in_queue=False) == "resolved_upstream"
    # a promoted fix on a finding still in the queue stays terminal (the next
    # validate refresh decides whether it actually cleared)
    assert _cls(rid, verdict_status=v, in_queue=True, promoted=[rid]) == "remediated_promoted"


# ------------------------------------------------------------------ build_ledger

def _seed_stores(tmp_path: Path):
    d = {
        "queue": tmp_path / "review_queue.csv",
        "verdicts": tmp_path / "verdicts",
        "staged": tmp_path / "staged",
        "promoted": tmp_path / "promoted",
        "archive": tmp_path / "archive",
        "wrappers": tmp_path / "wrappers",
    }
    for k in ("verdicts", "staged", "promoted", "archive", "wrappers"):
        d[k].mkdir()
    return d


def _write_queue(path: Path, rids, *, lane="blocker"):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["review_id", "cik", "rule_name",
                                          "report_date", "lane", "engine",
                                          "fv_at_risk_m", "fund_quarter_fv_m"])
        w.writeheader()
        for rid in rids:
            w.writerow({"review_id": rid, "cik": "0000000001",
                        "rule_name": "fv_conservation", "report_date": "2025-12-31",
                        "lane": lane, "engine": "conservation", "fv_at_risk_m": "1.0",
                        "fund_quarter_fv_m": "1234.5"})


def _verdict_file(vdir: Path, rid: str, verdict: str):
    (vdir / f"{rid}.json").write_text(
        json.dumps({"review_id": rid, "verdict": verdict}), encoding="utf-8")


def _leaf(root: Path, cik: str, fix_class: str, rids):
    p = root / cik
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{fix_class}.json").write_text(json.dumps(
        {"cik": cik, "fix_class": fix_class, "source_review_ids": list(rids)}),
        encoding="utf-8")


def test_build_ledger_end_to_end(tmp_path):
    d = _seed_stores(tmp_path)
    _write_queue(d["queue"], ["RVQ_open", "RVQ_fa", "RVQ_promoted", "RVQ_unrem",
                              "RVQ_pulled"])
    _verdict_file(d["verdicts"], "RVQ_fa", "false_alarm")
    _verdict_file(d["verdicts"], "RVQ_promoted", "real_error")
    _verdict_file(d["verdicts"], "RVQ_unrem", "real_error")
    _verdict_file(d["verdicts"], "RVQ_pulled", "real_error")
    _verdict_file(d["verdicts"], "RVQ_upstream", "real_error")  # not in queue
    _leaf(d["promoted"], "0000000001", "dedup", ["RVQ_promoted"])
    _leaf(d["archive"], "0000000001", "unit_rescale", ["RVQ_pulled"])
    ledger = fl.build_ledger(queue_path=d["queue"], staged_dir=d["staged"],
                             promoted_dir=d["promoted"], archive_dir=d["archive"],
                             wrapper_dir=d["wrappers"], verdict_dirs=(d["verdicts"],))
    states = {r["review_id"]: r["state"] for r in ledger}
    assert states == {
        "RVQ_open": "open",
        "RVQ_fa": "adjudicated_false_alarm",
        "RVQ_promoted": "remediated_promoted",
        "RVQ_unrem": "real_error_unremediated",
        "RVQ_pulled": "remediation_pulled",
        "RVQ_upstream": "resolved_upstream",
    }
    summary = fl.summarize(ledger)
    assert summary["n_actionable"] == 3  # open + unremediated + pulled
    assert summary["dry"] is False
    # fund_quarter_fv_m (all-engine exposure weight) is carried for every state
    # with a queue row, so FV-by-lifecycle-state is readable from the ledger.
    by_rid = {r["review_id"]: r for r in ledger}
    assert by_rid["RVQ_open"]["fund_quarter_fv_m"] == "1234.5"
    assert by_rid["RVQ_unrem"]["fund_quarter_fv_m"] == "1234.5"
    assert by_rid["RVQ_upstream"]["fund_quarter_fv_m"] == ""  # no queue row


def test_wrapper_provenance_counts_as_promoted(tmp_path):
    d = _seed_stores(tmp_path)
    _write_queue(d["queue"], ["RVQ_wrap"])
    _verdict_file(d["verdicts"], "RVQ_wrap", "real_error")
    (d["wrappers"] / "0000000001.json").write_text(json.dumps({
        "dispatch": {"aggregate_markers": []},
        "b2_provenance": [{"source_review_ids": ["RVQ_wrap"],
                           "promoted_gate": {"verdict": "PASS"}}]}), encoding="utf-8")
    ledger = fl.build_ledger(queue_path=d["queue"], staged_dir=d["staged"],
                             promoted_dir=d["promoted"], archive_dir=d["archive"],
                             wrapper_dir=d["wrappers"], verdict_dirs=(d["verdicts"],))
    assert ledger[0]["state"] == "remediated_promoted"


def test_archived_copy_of_promoted_leaf_is_not_pulled(tmp_path):
    # promote_passes copies the leaf; the archive often retains a copy of a leaf
    # that is ALSO still live. Live promotion must win: pulled = archive - promoted.
    d = _seed_stores(tmp_path)
    _write_queue(d["queue"], ["RVQ_both"])
    _verdict_file(d["verdicts"], "RVQ_both", "real_error")
    _leaf(d["promoted"], "0000000001", "dedup", ["RVQ_both"])
    _leaf(d["archive"], "0000000001", "dedup", ["RVQ_both"])
    ledger = fl.build_ledger(queue_path=d["queue"], staged_dir=d["staged"],
                             promoted_dir=d["promoted"], archive_dir=d["archive"],
                             wrapper_dir=d["wrappers"], verdict_dirs=(d["verdicts"],))
    assert ledger[0]["state"] == "remediated_promoted"


def test_review_lane_opens_do_not_block_dryness(tmp_path):
    # The review lane is a triage pool, not the fleet-dispatch pool; 27.5K open
    # review-lane items must not make the loop unconvergeable by construction.
    d = _seed_stores(tmp_path)
    _write_queue(d["queue"], ["RVQ_rev1", "RVQ_rev2"], lane="review")
    ledger = fl.build_ledger(queue_path=d["queue"], staged_dir=d["staged"],
                             promoted_dir=d["promoted"], archive_dir=d["archive"],
                             wrapper_dir=d["wrappers"], verdict_dirs=(d["verdicts"],))
    summary = fl.summarize(ledger)
    assert summary["states"]["open"] == 2
    assert summary["open_by_lane"] == {"review": 2}
    assert summary["n_actionable"] == 0 and summary["dry"] is True


def test_dry_when_only_terminal_states(tmp_path):
    d = _seed_stores(tmp_path)
    _write_queue(d["queue"], ["RVQ_fa"])
    _verdict_file(d["verdicts"], "RVQ_fa", "false_alarm")
    _verdict_file(d["verdicts"], "RVQ_up", "real_error")
    ledger = fl.build_ledger(queue_path=d["queue"], staged_dir=d["staged"],
                             promoted_dir=d["promoted"], archive_dir=d["archive"],
                             wrapper_dir=d["wrappers"], verdict_dirs=(d["verdicts"],))
    summary = fl.summarize(ledger)
    assert summary["dry"] is True and summary["n_actionable"] == 0


def test_closure_seed_retains_absent_finding_and_fails_closed(tmp_path):
    d = _seed_stores(tmp_path)
    _write_queue(d["queue"], ["RVQ_live"])
    seed = tmp_path / "frozen.csv"
    _write_queue(seed, ["RVQ_frozen"])
    ledger = fl.build_ledger(queue_path=d["queue"], staged_dir=d["staged"],
                             promoted_dir=d["promoted"], archive_dir=d["archive"],
                             wrapper_dir=d["wrappers"], verdict_dirs=(d["verdicts"],),
                             seed_paths=(seed,), quarter="2025-12-31", closure_mode=True)
    states = {r["review_id"]: r["state"] for r in ledger}
    assert states == {"RVQ_frozen": "unverified_absence", "RVQ_live": "open"}
    summary = fl.summarize(ledger, closure_mode=True)
    assert summary["n_actionable"] == 2 and summary["dry"] is False


def test_closure_real_error_without_route_requires_b1(tmp_path):
    d = _seed_stores(tmp_path)
    _write_queue(d["queue"], ["RVQ_route"])
    _verdict_file(d["verdicts"], "RVQ_route", "real_error")
    ledger = fl.build_ledger(queue_path=d["queue"], staged_dir=d["staged"],
                             promoted_dir=d["promoted"], archive_dir=d["archive"],
                             wrapper_dir=d["wrappers"], verdict_dirs=(d["verdicts"],),
                             closure_mode=True)
    assert ledger[0]["state"] == "b1_route_missing"


# --------------------------------------------------------------- compare / write

def test_compare_reports_transitions():
    prior = [{"review_id": "a", "state": "open"},
             {"review_id": "b", "state": "real_error_unremediated"},
             {"review_id": "c", "state": "open"}]
    current = [{"review_id": "a", "state": "adjudicated_false_alarm"},
               {"review_id": "b", "state": "remediated_promoted"},
               {"review_id": "d", "state": "open"}]
    delta = fl.compare(prior, current)
    assert delta["changed"] is True
    assert delta["transitions"]["open -> adjudicated_false_alarm"] == 1
    assert delta["transitions"]["real_error_unremediated -> remediated_promoted"] == 1
    assert delta["transitions"]["(new) -> open"] == 1
    assert delta["n_dropped_findings"] == 1  # c left the ledger


def test_write_ledger_emits_summary_sidecar_and_round_delta(tmp_path):
    prior_p = tmp_path / "prior.csv"
    with open(prior_p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["review_id", "state"])
        w.writeheader()
        w.writerow({"review_id": "a", "state": "open"})
    ledger = [{"review_id": "a", "state": "adjudicated_false_alarm"}]
    out = tmp_path / "ledger.csv"
    summary = fl.write_ledger(ledger, out, compare_path=prior_p)
    assert out.exists()
    sidecar = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
    assert sidecar["dry"] is True
    assert summary["round_delta"]["n_transitions"] == 1
