"""pipeline.batch_compare: what a batch build did to the findings."""
from pipeline import batch_compare as bc

CIK, OTHER = "0000000001", "0000000002"


def row(rid, state, status="", cik=CIK):
    return {"review_id": rid, "state": state, "status": status, "cik": cik, "engine": "oracle",
            "rule_name": "A01", "report_date": "2025-12-31"}


def fix(*rids, ciks=(CIK,), did="DC-1"):
    return {"decision_id": did, "expects": {"finding_ids": list(rids), "ciks": list(ciks)}}


def outcome(prior, current, fixes=()):
    return {r["review_id"]: r for r in bc.compare(prior, current, fixes)}


def test_a_fix_that_worked():
    got = outcome([row("A", "open", "needs_data_fix")], [], [fix("A")])
    assert got["A"]["outcome"] == "fixed" and got["A"]["fix_ids"] == "DC-1"
    got = outcome([row("A", "real_error_unremediated")], [row("A", "remediated_promoted")], [fix("A")])
    assert got["A"]["outcome"] == "fixed" and got["A"]["status"] == "closed"


def test_a_fix_that_failed():
    got = outcome([row("A", "real_error_unremediated")], [row("A", "real_error_unremediated")], [fix("A")])
    assert got["A"]["outcome"] == "failed_fix" and not got["A"]["outside_expected_funds"]


def test_a_fix_whose_verdict_still_stands():
    got = outcome([row("A", "real_error_unremediated")], [row("A", "real_error_check_silent")], [fix("A")])
    assert got["A"]["outcome"] == "fixed_pending_retirement"


def test_unexplained_silence_on_a_reviewed_finding():
    # verdict stands, check went quiet, nobody recorded a fix
    got = outcome([row("A", "real_error_unremediated")], [row("A", "real_error_check_silent")])
    assert got["A"]["outcome"] == "unexplained_silence"
    # reviewed by a fund agent (no verdict file): it leaves the ledger
    got = outcome([row("B", "open", "needs_check_repair")], [])
    assert got["B"]["outcome"] == "unexplained_silence"
    got = outcome([row("B", "open", "needs_owner_ruling")], [row("B", "gone_unadjudicated")])
    assert got["B"]["outcome"] == "unexplained_silence"
    # already silent before: nothing moved
    assert outcome([row("C", "real_error_check_silent")], [row("C", "real_error_check_silent")]) == {}


def test_a_never_reviewed_finding_that_vanishes_is_closed_not_flagged():
    got = outcome([row("A", "open", "needs_agent_review")], [])
    assert got["A"]["outcome"] == "closed_other"
    got = outcome([row("A", "open")], [row("A", "gone_unadjudicated")])
    assert got["A"]["outcome"] == "closed_other"


def test_closed_by_a_disposition_or_retirement():
    got = outcome([row("A", "open", "needs_owner_ruling")], [row("A", "dispositioned_as_filed")])
    assert got["A"]["outcome"] == "closed_other"
    got = outcome([row("B", "real_error_check_silent")], [row("B", "verdict_retired")])
    assert got["B"]["outcome"] == "closed_other"


def test_new_and_reopened():
    got = outcome([row("R", "adjudicated_false_alarm")], [row("R", "open"), row("N", "open"),
                                                         row("Q", "adjudicated_false_alarm")])
    assert got["R"]["outcome"] == "reopened" and got["N"]["outcome"] == "new_finding"
    assert "Q" not in got  # new and already closed: nothing to do


def test_movement_outside_the_funds_the_fixes_named():
    prior = [row("A", "real_error_unremediated"), row("X", "adjudicated_false_alarm", cik=OTHER)]
    current = [row("X", "open", cik=OTHER), row("Y", "open", cik=OTHER), row("Z", "open")]
    got = outcome(prior, current, [fix("A")])
    assert got["A"]["outcome"] == "fixed" and not got["A"]["outside_expected_funds"]
    assert got["X"]["outside_expected_funds"] and got["Y"]["outside_expected_funds"]
    assert not got["Z"]["outside_expected_funds"]  # same fund as the fix
    # with no fixes in the batch nothing is "outside": there is no expectation to compare with
    assert not any(r["outside_expected_funds"] for r in bc.compare(prior, current, []))


def test_unchanged_findings_are_not_listed_and_summary_counts():
    prior = [row("A", "open"), row("B", "adjudicated_false_alarm"), row("C", "real_error_unremediated")]
    current = [row("A", "open"), row("B", "adjudicated_false_alarm"), row("C", "real_error_unremediated"),
               row("N", "open")]
    rows = bc.compare(prior, current, [fix("C")])
    assert [r["review_id"] for r in rows] == ["C", "N"]
    summary = bc.summarize(rows)
    assert summary["outcomes"]["failed_fix"] == 1 and summary["outcomes"]["new_finding"] == 1
    assert summary["n_moved"] == 2 and set(summary["outcomes"]) == set(bc.OUTCOMES)
    assert set(rows[0]) == set(bc.COLUMNS)


def test_a_fix_naming_an_unknown_finding_is_ignored():
    assert bc.compare([], [], [fix("GHOST")]) == []
