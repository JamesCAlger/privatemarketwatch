"""The fund-clearing gate: quote matching, file rules, and the checks that read a sandbox."""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "v05_evidence"))
import fund_gate  # noqa: E402

CIK = "0001234567"
ACC = "0001234567-25-000001"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(fund_gate, "SANDBOXES", tmp_path)
    monkeypatch.setattr(fund_gate, "REPO", tmp_path)
    fund_gate.page_text.cache_clear()
    page = tmp_path / "data/raw/filings/bdc_html/1234567"
    page.mkdir(parents=True)
    (page / "000123456725000001.html").write_text(
        "<tr><td>Acme&#160;Holdings,&nbsp;Inc.</td><td>First lien</td><td>&#8364; 40,000</td><td>42,858</td><td>&#8212;</td></tr>",
        encoding="utf-8")
    return tmp_path


def _holdings(root, label, rows):
    out = root / label / "output"
    out.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(out / "private_markets_holdings.parquet")
    return out


def _row(row_id, fair_value, quarter="2025-12-31", **more):
    base = {"row_id": row_id, "cik": CIK, "report_date": pd.Timestamp(quarter), "fair_value": fair_value,
            "index_classification": "DIRECT_LENDING", "accounting_record_class": "", "principal_amount": 1.0,
            "entity_id": "e1", "cost": 1.0}
    return {**base, **more}


def test_a_quote_is_matched_as_page_line_prints_it(sandbox):
    assert fund_gate.page_text(CIK, ACC) == "Acme Holdings, Inc. First lien EUR 40,000 42,858 -"
    good = {"fixes": [{"what": "par", "quotes": [{"accession": ACC, "text": "Acme Holdings, Inc. First lien EUR 40,000 42,858"}]}]}
    assert fund_gate.check_quotes(CIK, good)["ok"]
    # an invented figure, a fix with no quote, a quote too short to mean anything, a filing not on disk
    for bad in ({"fixes": [{"what": "par", "quotes": [{"accession": ACC, "text": "Acme Holdings, Inc. First lien EUR 41,000 42,858"}]}]},
                {"fixes": [{"what": "par", "quotes": []}]},
                {"fixes": [{"what": "par", "quotes": [{"accession": ACC, "text": "40,000"}]}]},
                {"fixes": [{"what": "par", "quotes": [{"accession": "0001234567-25-000009", "text": "Acme Holdings, Inc. First lien"}]}]}):
        assert not fund_gate.check_quotes(CIK, bad)["ok"]


def test_a_proposal_needs_a_verbatim_filing_quote(sandbox):
    store = sandbox / "data/overrides/finding_dispositions_proposed"
    store.mkdir(parents=True)
    entry = {"disposition_id": "PD-1", "ciks": [CIK], "engine": "row_validation", "rule_name": "X11", "quarters": ["2025-12-31"],
             "evidence": [{"source": "filing", "quote": "my reading of the line"}]}
    (store / ("fund_%s.json" % CIK)).write_text(json.dumps({"dispositions": [entry]}), encoding="utf-8")
    assert not fund_gate.check_quotes(CIK, {})["ok"]
    entry["evidence"][0].update(accession=ACC, verbatim="Acme Holdings, Inc. First lien EUR 40,000")
    (store / ("fund_%s.json" % CIK)).write_text(json.dumps({"dispositions": [entry]}), encoding="utf-8")
    assert fund_gate.check_quotes(CIK, {})["ok"]


def test_totals_need_one_basis_and_every_other_quarter_declared(sandbox):
    out = _holdings(sandbox, "s1", [_row("a", 100e6, "2025-09-30"), _row("b", 100e6), _row("c", 9e6, index_classification="CASH"),
                                    _row("d", 50e6, "2026-03-31")])
    pd.DataFrame({"cik": [CIK, CIK], "report_date": ["2025-09-30", "2025-12-31"],
                  "investments_at_fair_value": [100e6, 103e6]}).to_csv(out / "fund_financials.csv", index=False)
    result = fund_gate.check_totals("s1", CIK, [])
    assert not result["ok"] and result["basis"] == "ex_cash"
    assert [u["quarter"] for u in result["undeclared"]] == ["2025-12-31", "2026-03-31"]   # 3M under; no filed total
    assert fund_gate.check_totals("s1", CIK, [{"quarter": "2025-12-31"}, {"quarter": "2026-03-31"}])["ok"]


def test_every_changed_field_and_row_must_be_declared(sandbox):
    _holdings(sandbox, "old", [_row("a", 1.0), _row("b", 2.0), _row("gone", 3.0)])
    _holdings(sandbox, "new", [_row("a", 1.0, principal_amount=None, entity_id="e2"), _row("b", 2.5), _row("added", 4.0)])
    silent = fund_gate.check_fields("new", "old", CIK, {})
    assert not silent["ok"] and silent["values_lost"] == {"principal_amount": 1}
    assert silent["columns_changed"] == {"fair_value": 1, "principal_amount": 1, "entity_id": 1}
    assert len(silent["problems"]) == 4          # two columns, one row added, one removed; entity_id is informational
    declared = {"declared_changes": [{"column": "fair_value", "rows": 1}, {"column": "principal_amount", "rows": 1}],
                "rows_added": 1, "rows_removed": 1}
    assert fund_gate.check_fields("new", "old", CIK, declared)["ok"]
    declared["declared_changes"][0]["rows"] = 0
    assert not fund_gate.check_fields("new", "old", CIK, declared)["ok"]


def test_outstanding_findings_need_a_proposal(sandbox):
    (sandbox / "s1").mkdir()
    pd.DataFrame([{"cik": CIK, "report_date": "2025-12-31", "state": "open", "engine": "row_validation", "rule_name": "X11"},
                  {"cik": CIK, "report_date": "2025-09-30", "state": "dispositioned_as_filed", "engine": "row_validation", "rule_name": "X02"},
                  {"cik": CIK, "report_date": "2025-09-30", "state": "resolved_upstream", "engine": "oracle", "rule_name": "B01"},
                  {"cik": "0009999999", "report_date": "2025-12-31", "state": "open", "engine": "oracle", "rule_name": "B01"}]
                 ).to_csv(sandbox / "s1" / "findings_ledger.csv", index=False)
    result = fund_gate.check_ledger("s1", CIK)
    assert (result["ok"], result["findings"], result["outstanding"], result["uncovered"]) == (False, 2, 1, ["row_validation X11 2025-12-31"])
    store = sandbox / "data/overrides/finding_dispositions_proposed"
    store.mkdir(parents=True)
    (store / ("fund_%s.json" % CIK)).write_text(json.dumps({"dispositions": [
        {"ciks": [CIK], "engine": "row_validation", "rule_name": "X11", "quarters": ["2025-12-31"]}]}), encoding="utf-8")
    assert fund_gate.check_ledger("s1", CIK)["ok"]


def test_a_proposal_over_an_earlier_real_error_verdict_must_answer_it(sandbox):
    (sandbox / "s1").mkdir()
    pd.DataFrame([{"cik": CIK, "report_date": "2025-12-31", "state": "real_error_unremediated", "engine": "oracle", "rule_name": "C04"},
                  {"cik": CIK, "report_date": "2025-09-30", "state": "open", "engine": "oracle", "rule_name": "C04"}]
                 ).to_csv(sandbox / "s1" / "findings_ledger.csv", index=False)
    store = sandbox / "data/overrides/finding_dispositions_proposed"
    store.mkdir(parents=True)
    entry = {"ciks": [CIK], "engine": "oracle", "rule_name": "C04", "quarters": ["2025-09-30", "2025-12-31"]}
    (store / ("fund_%s.json" % CIK)).write_text(json.dumps({"dispositions": [entry]}), encoding="utf-8")
    assert fund_gate.check_ledger("s1", CIK)["unanswered_verdicts"] == ["oracle C04 2025-12-31"]
    entry["addresses_verdict"] = {"2025-12-31": "too short"}
    (store / ("fund_%s.json" % CIK)).write_text(json.dumps({"dispositions": [entry]}), encoding="utf-8")
    assert fund_gate.check_ledger("s1", CIK)["unanswered_verdicts"] == ["oracle C04 2025-12-31"]
    entry["addresses_verdict"] = {"2025-12-31": "The reviewer cited four rows with a Par Amount / Shares figure; two are dollar amounts and two are counts now published."}
    (store / ("fund_%s.json" % CIK)).write_text(json.dumps({"dispositions": [entry]}), encoding="utf-8")
    assert fund_gate.check_ledger("s1", CIK)["unanswered_verdicts"] == []


def test_file_rules():
    forbidden = lambda path: any(re.search(rule, path) for rule in fund_gate.FORBIDDEN)
    for path in ("AGENTS.md", "pipeline/column_validation.py", "scripts/shadow_identity_engine.py", "scripts/v05_evidence/fund_gate.py",
                 "data/reference/accepted_disposition_reasons.json", "data/overrides/finding_dispositions/owner_2026-10-13.json",
                 ".claude/skills/v05-fund-clearing/SKILL.md", "pipeline/quarter_acceptance.py"):
        assert forbidden(path), path
    # the fund's own work, and the one accepted-store file written by the by-check tool
    for path in ("data/overrides/bdc_xbrl_wrappers/0001849894.json", "data/overrides/row_corrections.csv", "pipeline/staging_bdc.py",
                 "data/overrides/finding_dispositions_proposed/fund_0001849894.json",
                 "data/overrides/finding_dispositions/fundloop_accepted_by_check.json", "tests/test_new_setting.py"):
        assert not forbidden(path), path
    assert fund_gate.check_files(None, {})["ok"] is False      # no snapshot: not checked, so not passed


def test_stages_need_a_complete_build_log_that_shows_published_data_untouched(sandbox):
    box = sandbox / "s1"
    box.mkdir()
    stages = [{"stage": name, "exit": 1 if name == "ledger" else 0} for name in
              ("rebuild", "validate", "oracle", "provenance", "shadow", "queue", "ledger")]
    (box / "run.json").write_text(json.dumps({"ciks": [CIK], "stages": stages}), encoding="utf-8")
    assert not fund_gate.check_stages("s1", CIK)["ok"]                      # no build log
    runs = sandbox / "scratch" / "fund_runs"
    runs.mkdir(parents=True)
    (runs / "s1.log").write_text("published files touched: none\n", encoding="utf-8")
    assert not fund_gate.check_stages("s1", CIK)["ok"]                      # did not finish
    (runs / "s1.log").write_text("published files touched: none\nCHAIN_DONE\n", encoding="utf-8")
    assert fund_gate.check_stages("s1", CIK)["ok"]
    (runs / "s1.log").write_text("RuntimeError: fund sandbox changed published files: x.csv\nCHAIN_DONE\n", encoding="utf-8")
    assert not fund_gate.check_stages("s1", CIK)["ok"]
    stages[0]["exit"] = 1
    (box / "run.json").write_text(json.dumps({"ciks": [CIK], "stages": stages}), encoding="utf-8")
    (runs / "s1.log").write_text("published files touched: none\nCHAIN_DONE\n", encoding="utf-8")
    assert not fund_gate.check_stages("s1", CIK)["ok"]                      # a stage failed
