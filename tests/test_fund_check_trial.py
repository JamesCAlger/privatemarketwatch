import pandas as pd

from scripts.fund_check_trial import compare, conservation_status, row_validation_status


def _finding(engine, rule, quarter="2026-03-31"):
    return dict(review_id=engine + rule + quarter, state="open", engine=engine, rule_name=rule, report_date=quarter)


def _result(engine, rule, status, quarter="2026-03-31"):
    return dict(engine=engine, rule_name=rule, report_date=quarter, status=status, n=1)


def test_compare_labels_each_finding_by_what_the_trial_can_show():
    findings = pd.DataFrame([
        _finding("row_validation", "FX01"),      # fires again
        _finding("row_validation", "X02"),       # validator rule, no issue row -> cleared
        _finding("row_validation", "PP03"),      # adapter rule the validator cannot emit
        _finding("oracle", "E04"),               # evaluated, passes
        _finding("oracle", "E07"),               # stale input
        _finding("oracle", "Z99"),               # never evaluated
        _finding("nonaccrual", "nonaccrual_flag"),
    ])
    results = pd.DataFrame([
        _result("row_validation", "FX01", "warn"),
        _result("oracle", "E04", "pass"),
        _result("oracle", "E07", "fail"),
    ])
    out = compare(findings, results, row_rules=frozenset({"FX01", "X02"})).set_index("rule_name")["trial"].to_dict()
    assert out == {"FX01": "still_fires", "X02": "no_longer_fires", "PP03": "not_rerun", "E04": "no_longer_fires",
                   "E07": "not_rerun", "Z99": "not_rerun", "nonaccrual_flag": "not_rerun"}


def test_a_pass_in_another_quarter_does_not_clear_a_firing_quarter():
    findings = pd.DataFrame([_finding("oracle", "A07", "2025-12-31")])
    results = pd.DataFrame([_result("oracle", "A07", "pass"), _result("oracle", "A07", "fail", "2025-12-31")])
    assert compare(findings, results)["trial"].tolist() == ["still_fires"]


def test_row_validation_status_is_fail_when_any_issue_row_is_a_fail():
    issues = pd.DataFrame([
        dict(rule_id="X06", report_date="2026-03-31 00:00:00", severity="WARN"),
        dict(rule_id="X06", report_date="2026-03-31", severity="FAIL"),
        dict(rule_id="FX01", report_date="2026-03-31", severity="WARN"),
    ])
    out = row_validation_status(issues).set_index("rule_name")
    assert out.loc["X06", "status"] == "fail" and out.loc["X06", "n"] == 2
    assert out.loc["FX01", "status"] == "warn"


def test_conservation_uses_the_published_basis_and_the_band():
    holdings = pd.DataFrame([
        dict(report_date="2026-03-31", fair_value="100", accounting_record_class="parent_schedule"),
        dict(report_date="2026-03-31", fair_value="900", accounting_record_class="underlying_schedule"),
        dict(report_date="2025-12-31", fair_value="110", accounting_record_class="parent_schedule"),
    ])
    filed = pd.DataFrame([dict(report_date="2026-03-31", investments_at_fair_value="100"),
                          dict(report_date="2025-12-31", investments_at_fair_value="100")])
    out = conservation_status(holdings, filed, band_pct=0.5).set_index("report_date")["status"].to_dict()
    assert out == {"2026-03-31": "pass", "2025-12-31": "fail"}


def test_boolean_blocking_flag_is_written_as_an_indicator():
    from pipeline.source_reconciliation import _indicator_detail
    frame = pd.DataFrame({"blocking_issue": [True, False], "status": ["a", "b"]})
    out = _indicator_detail(frame)
    assert out["blocking_issue"].tolist() == [1, 0]
    assert frame["blocking_issue"].tolist() == [True, False]          # caller's frame untouched
    numeric = pd.DataFrame({"blocking_issue": [1.0, 0.0]})
    assert _indicator_detail(numeric) is numeric                       # already numeric: unchanged
