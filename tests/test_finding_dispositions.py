"""Standing dispositions: validation, reach limits, and how the findings ledger applies them."""
import csv
import json

import pytest

from pipeline import finding_dispositions as fd


HPS = "0001838126"
ACC = "0001838126-26-000001"
LINE = "Acme Corp First Lien Revolver S+ 600 1,990 ( 48 ) ( 50 )"
FILED = {"source": "filing", "quote": "the revolver line", "accession": ACC, "verbatim": LINE, "quarter": "2026-03-31"}


def _entry(**changes):
    base = {"disposition_id": "D-900", "class": "as_filed", "ciks": [HPS], "engine": "row_validation",
            "rule_name": "C107", "quarters": ["2026-03-31"], "statement": "Negative cost on undrawn lines, as filed.",
            "evidence": [{"source": "query", "quote": "1,322 of 1,328 rows have no principal or principal over 10x value"},
                         FILED],
            "rows": [{"cik": HPS, "quarter": "2026-03-31", "row_id": "ROW-a", "issuer": "Acme Corp", "instrument": "Revolver"}],
            "rerun": "python scratch/2026-10-05_fund_loop/unfunded.py five8", "decided_by": "agent", "decided_on": "2026-10-06"}
    return {**base, **changes}


def _flagged(*keys):
    """A flagged-rows provider returning the same keys for every finding."""
    return lambda *_args: frozenset(keys)


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
                          verdict_dirs=(empty,), dispositions_dir=_store(tmp_path, _entry()), flagged_rows=_flagged("row_id:ROW-a"))
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
                          verdict_dirs=(verdicts,), dispositions_dir=_store(tmp_path, _entry()), flagged_rows=_flagged("row_id:ROW-a"))
    assert ledger[0]["state"] == "real_error_unremediated"


def test_acceptance_and_sandbox_treat_dispositioned_states_as_resolved():
    from pipeline.quarter_acceptance import RESOLVED_FINDING_STATES
    assert fd.DISPOSITIONED_STATES <= RESOLVED_FINDING_STATES


def _ledger_state(tmp_path, entry, **kwargs):
    return _ledger_row(tmp_path, entry, **kwargs)["state"]


def _ledger_row(tmp_path, entry, *, verdict="real_error", in_queue=True, flagged=("row_id:ROW-a",), legacy=None):
    from scripts.findings_ledger import build_ledger
    tmp_path.mkdir(parents=True, exist_ok=True)
    queue = _queue(tmp_path, [{"review_id": "RQ-1", "cik": "0001838126", "rule_name": entry["rule_name"],
                               "report_date": "2026-03-31", "lane": "review", "engine": entry["engine"]}] if in_queue else [])
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir(exist_ok=True)
    empty = tmp_path / "none"
    bundles = tmp_path / "review_bundles"
    if verdict:
        (verdicts / "RQ-1.json").write_text(json.dumps({"review_id": "RQ-1", "verdict": verdict}), encoding="utf-8")
        # where a verdict whose check went silent takes its fund, rule and quarter from
        bundles.mkdir(exist_ok=True)
        (bundles / "RQ-1.json").write_text(json.dumps({"review_id": "RQ-1", "cik": HPS, "engine": entry["engine"],
                                                       "rule_name": entry["rule_name"], "report_date": "2026-03-31"}),
                                           encoding="utf-8")
    store = _store(tmp_path, entry)
    import unittest.mock as mock
    with mock.patch.object(fd, "load_legacy", lambda path=None: legacy or {}):
        rows = build_ledger(queue_path=queue, staged_dir=empty, promoted_dir=empty, archive_dir=empty, wrapper_dir=empty,
                            verdict_dirs=(verdicts,), dispositions_dir=store,
                            flagged_rows=(lambda *_a: None) if flagged is None else _flagged(*flagged))
    return rows[0]


def test_an_informational_rule_closes_a_finding_a_reviewer_confirmed_as_true(tmp_path):
    # e.g. non-accrual: 'real_error' there means the loan is on non-accrual, which is what the rule reports
    entry = _entry(**{"class": "informational"}, ciks=["*"], quarters=["all"], engine="nonaccrual", rule_name="nonaccrual_flag")
    assert _ledger_state(tmp_path, entry) == "dispositioned_informational"


def test_as_filed_supersedes_a_real_error_verdict_only_with_the_flag_and_filing_evidence(tmp_path):
    filed = [{**FILED, "quote": "identifier and maturity tag both read 4/30/2024"}]
    no_filing = [{"source": "query", "quote": "a sandbox count"}]
    assert any("filing evidence" in p for p in fd.validate(_entry(supersedes_real_error_verdict=True, evidence=no_filing)))
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


# --- D-253 (2026-11-10): verdict answers, revocation, and the acceptance bar ------------------------------

ANSWER = ("The earlier reviewer read the schedule row and concluded it was absent from the output; it is published "
          "at the printed value, and the unpublished source row is the roll-forward note's twin.")


@pytest.mark.parametrize("verdict_state", ["real_error_unremediated", "real_error_check_silent"])
def test_an_accepted_answer_to_the_verdict_closes_the_finding(tmp_path, verdict_state):
    # audit #26 (0002006758 2026-03-31): an accepted entry answering the verdict for its quarter was not applied
    entry = _entry(**{"class": "not_applicable"}, addresses_verdict={"2026-03-31": ANSWER})
    row = _ledger_row(tmp_path, entry, in_queue=verdict_state == "real_error_unremediated")
    assert (row["state"], row["disposition_id"]) == ("dispositioned_not_applicable", "D-900")
    assert fd.closes(entry, verdict_state, "2026-03-31")


def test_an_entry_without_an_answer_leaves_the_verdict_outstanding(tmp_path):
    assert _ledger_state(tmp_path / "q", _entry()) == "real_error_unremediated"
    assert _ledger_state(tmp_path / "s", _entry(), in_queue=False) == "real_error_check_silent"
    # an answer for another quarter, or a token one, does not answer this quarter's verdict
    assert not fd.closes(_entry(addresses_verdict={"2025-12-31": ANSWER}), "real_error_unremediated", "2026-03-31")
    assert not fd.closes(_entry(addresses_verdict={"2026-03-31": "not an error"}), "real_error_unremediated", "2026-03-31")
    # an answer resting on no filing evidence is refused by the validator and closes nothing
    bare = _entry(addresses_verdict={"2026-03-31": ANSWER}, evidence=[{"source": "query", "quote": "count"}])
    assert any("filing evidence" in p for p in fd.validate(bare))
    assert not fd.closes(bare, "real_error_unremediated", "2026-03-31")


def test_a_supersedes_flag_still_closes_every_listed_quarter():
    assert fd.closes(_entry(supersedes_real_error_verdict=True), "real_error_check_silent", "2026-03-31")


def _legacy(entry):
    return {entry["disposition_id"]: {"ciks": set(entry["ciks"]), "quarters": set(entry["quarters"])}}


REVOCATION = {"revoked_on": "2026-11-10", "revoked_by": "owner, 2026-11-10: \"do as recommended\"",
              "reason": "the page prints the coupon"}


def test_a_revoked_entry_or_member_matches_nothing_and_keeps_its_history():
    whole = _entry(revoked=REVOCATION)
    assert fd.validate(whole) == []
    assert fd.match([whole], cik=HPS, engine="row_validation", rule_name="C107", report_date="2026-03-31") is None
    # narrowed: the quarter moves from quarters to revoked_members, the rest still matches
    narrowed = _entry(revoked_members=[{"ciks": [HPS], "quarters": ["2025-12-31"], **REVOCATION}])
    assert fd.validate(narrowed) == []
    assert fd.match([narrowed], cik=HPS, engine="row_validation", rule_name="C107", report_date="2025-12-31") is None
    assert fd.match([narrowed], cik=HPS, engine="row_validation", rule_name="C107", report_date="2026-03-31") is narrowed
    # a revoked member left in quarters is ambiguous: refused
    both = _entry(revoked_members=[{"ciks": [HPS], "quarters": ["2026-03-31"], **REVOCATION}])
    assert any("still listed" in p for p in fd.validate(both))
    assert any("revoked needs reason" in p for p in fd.validate(_entry(revoked={"revoked_on": "2026-11-10", "revoked_by": "x"})))


def test_a_revoked_member_is_not_reached_by_carry_forward():
    entry = _entry(carry_forward={"from": "2026-06-30", "check": "values_as_filed", "params": {"fields": ["cost"]}},
                   revoked_members=[{"ciks": [HPS], "quarters": ["2026-06-30"], **REVOCATION}])
    assert fd.validate(entry) == []
    assert fd.match([entry], cik=HPS, engine="row_validation", rule_name="C107", report_date="2026-06-30",
                    passes={("D-900", HPS, "2026-06-30")}) is None


@pytest.mark.parametrize("changes,problem", [
    ({"evidence": [{"source": "query", "quote": "a sandbox count"}]}, "filing quote"),
    ({"evidence": [{**FILED, "quarter": "2025-12-31"}]}, "filing quote"),             # quoted for another quarter
    ({"evidence": [{**FILED, "verbatim": "too short"}]}, "filing quote"),
    ({"evidence": [{**FILED, "accession": ""}]}, "filing quote"),
    ({"rows": []}, "rows must name"),
    ({"rows": [{"cik": HPS, "quarter": "2026-03-31", "issuer": "Acme Corp"}]}, "one of row_id"),
    ({"rows": [{"cik": HPS, "quarter": "2025-12-31", "row_id": "ROW-a"}]}, "does not list"),
    ({"rows": [{"cik": HPS, "quarter": "2026-03-31", "row_id": "ROW-a", "fund_level": True}]}, "exactly one"),
])
def test_a_new_entry_must_quote_every_member_and_name_its_rows(changes, problem):
    assert any(problem in p for p in fd.validate(_entry(**changes))), fd.validate(_entry(**changes))


def test_every_member_needs_its_own_quote_and_rows():
    problems = fd.validate(_entry(quarters=["2025-12-31", "2026-03-31"]))
    assert any("filing quote" in p and "2025-12-31" in p for p in problems)
    assert any("names nothing" in p and "2025-12-31" in p for p in problems)
    complete = _entry(quarters=["2025-12-31", "2026-03-31"], evidence=[FILED, {**FILED, "quarter": "2025-12-31"}],
                      rows=[{"cik": HPS, "quarter": q, "row_id": "ROW-a"} for q in ("2025-12-31", "2026-03-31")])
    assert fd.validate(complete) == []


def test_informational_entries_are_exempt_from_the_member_bar():
    assert fd.validate(_entry(**{"class": "informational"}, ciks=["*"], quarters=["all"],
                              evidence=[{"source": "code", "quote": "x"}], rows=None)) == []


def test_the_legacy_flag_is_honoured_only_for_frozen_ids_and_members():
    old = _entry(evidence=[{"source": "query", "quote": "count"}], rows=None, legacy_unscoped=True)
    assert fd.validate(old, legacy=_legacy(old)) == []
    assert any("frozen in the legacy registry" in p for p in fd.validate(old, legacy={}))
    widened = dict(old, quarters=["2026-03-31", "2026-06-30"])
    assert any("beyond its frozen members" in p for p in fd.validate(widened, legacy=_legacy(old)))
    # narrowing stays legal
    frozen = {"D-900": {"ciks": {HPS}, "quarters": {"2025-12-31", "2026-03-31"}}}
    assert fd.validate(old, legacy=frozen) == []


def test_named_rows_close_the_finding_and_a_recurrence_on_other_rows_stays_open(tmp_path):
    entry = _entry(**{"class": "not_applicable"})
    assert _ledger_row(tmp_path / "a", entry, verdict=None, flagged=("row_id:ROW-a",))["state"] == "dispositioned_not_applicable"
    # the same rule fires again on the named row AND another row: open, and the column says why
    row = _ledger_row(tmp_path / "b", entry, verdict=None, flagged=("row_id:ROW-a", "row_id:ROW-b"))
    assert (row["state"], row["disposition_id"], row["disposition_row_check"]) == ("open", "", "D-900:rows_outside:1")
    # a recurrence only on other rows: open
    assert _ledger_state(tmp_path / "c", entry, verdict=None, flagged=("row_id:ROW-b",)) == "open"
    # rows that cannot be resolved fail closed
    row = _ledger_row(tmp_path / "d", entry, verdict=None, flagged=None)
    assert (row["state"], row["disposition_row_check"]) == ("open", "D-900:rows_unresolved")


def test_a_legacy_entry_still_closes_unscoped(tmp_path):
    old = _entry(evidence=[{"source": "query", "quote": "count"}], rows=None, legacy_unscoped=True)
    row = _ledger_row(tmp_path, old, verdict=None, flagged=("row_id:ROW-z",), legacy=_legacy(old))
    assert (row["state"], row["disposition_row_check"]) == ("dispositioned_as_filed", "legacy_unscoped")


def test_source_identifier_and_fund_level_rows_match_their_keys():
    from pipeline.finding_rows import FUND_LEVEL, descriptor_key
    entry = _entry(rows=[{"cik": HPS, "quarter": "2026-03-31", "source_identifier": "Affiliated  Investments AWRG Borrower LLC, Term Loan"},
                         {"cik": HPS, "quarter": "2026-03-31", "fund_level": True}])
    assert fd.validate(entry) == []
    keys = fd.row_keys(entry, HPS, "2026-03-31")
    assert keys == {"source_identifier:affiliated investments awrg borrower llc, term loan", FUND_LEVEL}
    assert descriptor_key({"cik": HPS}) is None
    ok, why = fd.covers_rows(entry, cik=HPS, quarter="2026-03-31",
                             flagged=frozenset({"source_identifier:affiliated investments awrg borrower llc, term loan"}))
    assert ok and why == "rows_within"


def test_flagged_rows_reads_row_validation_issues(tmp_path):
    import duckdb
    from pipeline.finding_rows import FlaggedRows
    con = duckdb.connect()
    con.execute("CREATE TABLE i (cik VARCHAR, report_date DATE, rule_id VARCHAR, row_id VARCHAR, value VARCHAR)")
    con.execute("INSERT INTO i VALUES ('0001838126', DATE '2026-03-31', 'C107', 'ROW-a', '-48'), "
                "('0001838126', DATE '2026-03-31', 'C107', 'ROW-b', '-50'), "
                "('0001838126', DATE '2026-03-31', 'SRC_BDC01', NULL, 'Some  Issuer, Term Loan'), "
                "('0001838126', DATE '2026-03-31', 'AGG01', NULL, NULL)")
    con.execute("COPY i TO '%s' (FORMAT PARQUET)" % (tmp_path / "row_validation_issues.parquet").as_posix())
    con.close()
    rows = FlaggedRows(tmp_path)
    assert rows(HPS, "row_validation", "C107", "2026-03-31") == {"row_id:ROW-a", "row_id:ROW-b"}
    assert rows(HPS, "row_validation", "SRC_BDC01", "2026-03-31") == {"source_identifier:some issuer, term loan"}
    assert rows(HPS, "row_validation", "AGG01", "2026-03-31") == {"fund_level"}
    assert rows(HPS, "row_validation", "C107", "2025-12-31") is None          # nothing flagged there: unresolved
    assert rows(HPS, "oracle", "C04", "2026-03-31") is None                   # engine not resolved yet: fail closed
    assert rows(HPS, "fund_financials", "F16", "2026-03-31") == {"fund_level"}


def test_owner_queue_refuses_an_entry_without_a_verified_page_quote_for_each_member(monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "v05_evidence"))
    import fund_gate
    import owner_queue
    pages = {(HPS, ACC): fund_gate.normalise("Schedule of Investments " + LINE + " Total")}
    monkeypatch.setattr(fund_gate, "page_text", lambda cik, accession: pages.get((cik, accession)))
    assert owner_queue.bar_problems(_entry()) == []
    # the quote is not on the page
    assert owner_queue.bar_problems(_entry(evidence=[{**FILED, "verbatim": "Acme Corp First Lien Revolver 9,999 ( 1 )"}]))
    # one of two members has no verified quote (its filing is not on the page cache): refused
    two = _entry(quarters=["2025-12-31", "2026-03-31"],
                 evidence=[FILED, {**FILED, "quarter": "2025-12-31", "accession": "0001838126-25-000009"}],
                 rows=[{"cik": HPS, "quarter": q, "row_id": "ROW-a"} for q in ("2025-12-31", "2026-03-31")])
    problems = owner_queue.bar_problems(two)
    assert len(problems) == 1 and "2025-12-31" in problems[0]
    # no rows named: refused by the validator before any page is read
    assert any("rows" in p for p in owner_queue.bar_problems(_entry(rows=None)))
    # a grandfathered flag cannot ride in on a new acceptance
    assert owner_queue.bar_problems(_entry(legacy_unscoped=True))


def test_the_recorded_store_is_grandfathered_and_the_d253_revocations_hold():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    entries = {e["disposition_id"]: e for e in fd.load(root / "data" / "overrides" / "finding_dispositions")}
    for key in ("DS-015-1287750", "DS-011-1812554"):
        assert fd.is_revoked(entries[key])
    assert fd.match(list(entries.values()), cik="0001287750", engine="provenance_reverify",
                    rule_name="financial_convention_unresolved", report_date="2023-06-30") is None
    assert fd.match(list(entries.values()), cik="0001812554", engine="oracle", rule_name="C04", report_date="2023-09-30") is None
    for key in ("DS-005-1287750", "DS-C115-1742313-2", "DS-016-1812554"):
        assert entries[key]["statement_history"] and entries[key]["decided_by"]
