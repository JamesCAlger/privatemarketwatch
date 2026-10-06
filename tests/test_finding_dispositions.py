"""Standing dispositions: validation, reach limits, and how the findings ledger applies them."""
import csv
import json

import pytest

from pipeline import finding_dispositions as fd


def _entry(**changes):
    base = {"disposition_id": "D-900", "class": "as_filed", "ciks": ["0001838126"], "engine": "row_validation",
            "rule_name": "C107", "quarters": ["2026-03-31"], "statement": "Negative cost on undrawn lines, as filed.",
            "evidence": [{"source": "query", "quote": "1,322 of 1,328 rows have no principal or principal over 10x value"}],
            "rerun": "python scratch/2026-10-05_fund_loop/unfunded.py five8", "decided_by": "agent", "decided_on": "2026-10-06"}
    return {**base, **changes}


def _store(tmp_path, *entries):
    directory = tmp_path / "finding_dispositions"
    directory.mkdir()
    (directory / "v05.json").write_text(json.dumps({"dispositions": list(entries)}), encoding="utf-8")
    return directory


def test_a_complete_entry_is_valid():
    assert fd.validate(_entry()) == []


@pytest.mark.parametrize("changes,problem", [
    ({"evidence": []}, "evidence"),
    ({"rerun": ""}, "rerun"),
    ({"class": "false_alarm"}, "class"),
    ({"ciks": ["1838126"]}, "ciks"),
    ({"quarters": ["2026-Q1"]}, "quarters"),
    ({"decided_on": "yesterday"}, "decided_on"),
])
def test_incomplete_entries_are_rejected(changes, problem):
    assert any(problem in p for p in fd.validate(_entry(**changes)))


@pytest.mark.parametrize("kind", ["as_filed", "not_applicable"])
def test_a_judgment_about_filings_must_name_its_funds_and_quarters(kind):
    assert any("name its funds" in p for p in fd.validate(_entry(**{"class": kind, "ciks": ["*"]})))
    assert any("name its quarters" in p for p in fd.validate(_entry(**{"class": kind, "quarters": ["all"]})))


def test_an_informational_rule_may_cover_every_fund_and_quarter():
    assert fd.validate(_entry(**{"class": "informational", "ciks": ["*"], "quarters": ["all"]})) == []


def test_load_raises_on_an_invalid_or_repeated_entry(tmp_path):
    with pytest.raises(ValueError, match="Invalid disposition"):
        fd.load(_store(tmp_path, _entry(evidence=[])))
    other = tmp_path / "second"
    other.mkdir()
    with pytest.raises(ValueError, match="Duplicate disposition id"):
        fd.load(_store(other, _entry(), _entry()))


def test_match_respects_fund_rule_and_quarter(tmp_path):
    entries = fd.load(_store(tmp_path, _entry(),
                             _entry(disposition_id="D-901", **{"class": "informational"}, ciks=["*"], quarters=["all"],
                                    engine="nonaccrual", rule_name="nonaccrual_flag")))
    hit = fd.match(entries, cik="1838126", engine="row_validation", rule_name="C107", report_date="2026-03-31")
    assert hit["disposition_id"] == "D-900"
    # a later quarter, another fund, another rule: not covered
    assert fd.match(entries, cik="1838126", engine="row_validation", rule_name="C107", report_date="2026-06-30") is None
    assert fd.match(entries, cik="1287750", engine="row_validation", rule_name="C107", report_date="2026-03-31") is None
    assert fd.match(entries, cik="1838126", engine="row_validation", rule_name="C103", report_date="2026-03-31") is None
    assert fd.match(entries, cik="1999999", engine="nonaccrual", rule_name="nonaccrual_flag",
                    report_date="2030-12-31")["disposition_id"] == "D-901"


def _queue(tmp_path, rows):
    path = tmp_path / "review_queue.csv"
    fields = ["review_id", "cik", "rule_name", "report_date", "lane", "engine", "fv_at_risk_m", "fund_quarter_fv_m"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{f: "" for f in fields}, **row})
    return path


def test_ledger_gives_a_dispositioned_open_finding_a_terminal_state(tmp_path):
    from scripts.findings_ledger import build_ledger, summarize
    queue = _queue(tmp_path, [
        {"review_id": "RQ-1", "cik": "0001838126", "rule_name": "C107", "report_date": "2026-03-31", "lane": "blocker",
         "engine": "row_validation"},
        {"review_id": "RQ-2", "cik": "0001838126", "rule_name": "C107", "report_date": "2026-06-30", "lane": "blocker",
         "engine": "row_validation"},
    ])
    empty = tmp_path / "none"
    ledger = build_ledger(queue_path=queue, staged_dir=empty, promoted_dir=empty, archive_dir=empty, wrapper_dir=empty,
                          verdict_dirs=(empty,), dispositions_dir=_store(tmp_path, _entry()))
    by_id = {row["review_id"]: row for row in ledger}
    assert by_id["RQ-1"]["state"] == "dispositioned_as_filed" and by_id["RQ-1"]["disposition_id"] == "D-900"
    assert by_id["RQ-2"]["state"] == "open" and by_id["RQ-2"]["disposition_id"] == ""
    assert summarize(ledger)["n_actionable"] == 1


def test_a_disposition_does_not_override_an_adjudicated_real_error(tmp_path):
    from scripts.findings_ledger import build_ledger
    queue = _queue(tmp_path, [{"review_id": "RQ-1", "cik": "0001838126", "rule_name": "C107", "report_date": "2026-03-31",
                               "lane": "blocker", "engine": "row_validation"}])
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    (verdicts / "RQ-1.json").write_text(json.dumps({"review_id": "RQ-1", "verdict": "real_error"}), encoding="utf-8")
    empty = tmp_path / "none"
    ledger = build_ledger(queue_path=queue, staged_dir=empty, promoted_dir=empty, archive_dir=empty, wrapper_dir=empty,
                          verdict_dirs=(verdicts,), dispositions_dir=_store(tmp_path, _entry()))
    assert ledger[0]["state"] == "real_error_unremediated"


def test_acceptance_and_sandbox_treat_dispositioned_states_as_resolved():
    from pipeline.quarter_acceptance import RESOLVED_FINDING_STATES
    assert fd.DISPOSITIONED_STATES <= RESOLVED_FINDING_STATES


def _ledger_state(tmp_path, entry):
    from scripts.findings_ledger import build_ledger
    queue = _queue(tmp_path, [{"review_id": "RQ-1", "cik": "0001838126", "rule_name": entry["rule_name"],
                               "report_date": "2026-03-31", "lane": "review", "engine": entry["engine"]}])
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir(exist_ok=True)
    (verdicts / "RQ-1.json").write_text(json.dumps({"review_id": "RQ-1", "verdict": "real_error"}), encoding="utf-8")
    empty = tmp_path / "none"
    return build_ledger(queue_path=queue, staged_dir=empty, promoted_dir=empty, archive_dir=empty, wrapper_dir=empty,
                        verdict_dirs=(verdicts,), dispositions_dir=_store(tmp_path, entry))[0]["state"]


def test_an_informational_rule_closes_a_finding_a_reviewer_confirmed_as_true(tmp_path):
    # e.g. non-accrual: 'real_error' there means the loan is on non-accrual, which is what the rule reports
    entry = _entry(**{"class": "informational"}, ciks=["*"], quarters=["all"], engine="nonaccrual", rule_name="nonaccrual_flag")
    assert _ledger_state(tmp_path, entry) == "dispositioned_informational"


def test_as_filed_supersedes_a_real_error_verdict_only_with_the_flag_and_filing_evidence(tmp_path):
    filed = [{"source": "filing", "quote": "identifier and maturity tag both read 4/30/2024"}]
    assert any("filing evidence" in p for p in fd.validate(_entry(supersedes_real_error_verdict=True)))
    assert fd.validate(_entry(supersedes_real_error_verdict=True, evidence=filed)) == []
    assert _ledger_state(tmp_path, _entry(supersedes_real_error_verdict=True, evidence=filed)) == "dispositioned_as_filed"


def test_the_recorded_store_loads_and_its_rerun_scripts_exist():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    entries = fd.load(root / "data" / "overrides" / "finding_dispositions")
    assert entries
    for entry in entries:
        for script in re.findall(r"scripts/[\w/]+\.py", entry["rerun"]):
            assert (root / script).exists(), (entry["disposition_id"], script)


def test_a_drafted_fix_that_was_never_promoted_does_not_outrank_filing_evidence():
    # A fix staged or pulled by an earlier run is a draft, not a resolution. An entry that carries filing evidence
    # and says it replaces the earlier verdict closes the finding; one without that stays out (decision D-022).
    filed = [{"source": "filing", "quote": "context c-925 carries no InvestmentOwnedAtCost fact"}]
    strong = _entry(supersedes_real_error_verdict=True, evidence=filed)
    for state in ("remediation_staged", "remediation_pulled"):
        assert fd.closes(strong, state)
        assert not fd.closes(_entry(), state)
        assert not fd.closes(_entry(**{"class": "informational"}, ciks=["*"], quarters=["all"]), state)
    assert not fd.closes(strong, "remediated_promoted")
