"""source_encodings.printed_rows_without_context: schedule rows printed with no XBRL context.

Owner ruling 2026-10-18 (OVR-T8Y-R2 (a)). TCW Direct Lending VIII, 10-Q 2023-09-30
(0000950170-23-060972), prints 'Harvey Gulf Holdings, LLC 08/10/22 Term Loan A - 12.63% (SOFR +
7.00%, 1.00% Floor) 6.6 % 28,265,379 08/10/27 27,883,696 28,434,971' and files no fact or context
for it at 2023-09-30.
"""
import json

import duckdb
import pytest

from pipeline.printed_rows import (CONTEXT_PREFIX, condition_sql, declared_sql, entry_errors,
                                   printed_row_records)
from pipeline.source_encodings import load_encodings

CIK = "0001825265"
ACC = "0000950170-23-060972"
LINE = ("Harvey Gulf Holdings, LLC 08/10/22 Term Loan A - 12.63% (SOFR + 7.00%, 1.00% Floor) 6.6 % "
        "28,265,379 08/10/27 27,883,696 28,434,971")


def _entry(**changes):
    entry = {"accession": ACC, "quarter": "2023-09-30", "issuer": "Harvey Gulf Holdings, LLC",
             "instrument": "Term Loan A", "fair_value": 28434971, "cost": 27883696,
             "principal_amount": 28265379, "industry": "Energy Equipment & Services", "printed_line": LINE}
    entry.update(changes)
    return entry


def _encodings(tmp_path, entries):
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK,
               "source_encodings": {"printed_rows_without_context": entries}}
    (tmp_path / (CIK + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")
    return load_encodings(tmp_path)


META = {"cik": "1825265", "accession_number": ACC, "report_date": "2023-09-30"}


def test_listed_row_becomes_one_record_with_only_the_declared_values(tmp_path):
    encodings = _encodings(tmp_path, [_entry()])
    tagged = [{"_context_id": "C_1", "period": "2023-09-30", "investment_identifier": "Debt Investments, Alorica Inc., Term Loan",
               "fair_value": 33723435.0, "cost": 33429980.0}]
    added = printed_row_records(tagged, META, encodings)
    assert len(added) == 1
    rec = added[0]
    assert rec["_context_id"].startswith(CONTEXT_PREFIX)
    assert (rec["fair_value"], rec["cost"], rec["principal_amount"]) == (28434971.0, 27883696.0, 28265379.0)
    assert rec["period"] == "2023-09-30"
    # nothing else is read from the line: no rate, spread, maturity or percent
    for name in ("interest_rate", "basis_spread", "maturity_date", "pct_of_net_assets", "pik_rate"):
        assert name not in rec
    facts = json.loads(rec["src_facts"])["_printed_page"]
    assert facts["line"] == LINE and facts["issuer"] == "Harvey Gulf Holdings, LLC" and facts["instrument"] == "Term Loan A"


def test_row_the_filing_tags_is_refused_not_duplicated(tmp_path):
    # false positive guard: the same row on a current-period context is not added a second time
    encodings = _encodings(tmp_path, [_entry()])
    tagged = [{"_context_id": "C_9", "period": "2023-09-30",
               "investment_identifier": "Debt Investments, Energy Equipment & Services Harvey Gulf Holdings, LLC, "
                                        "Acquisition Date 08/10/22 Term Loan A - 12.63% Net Assets 6.6% Maturity 08/10/27",
               "fair_value": 28434971.0, "cost": 27883696.0}]
    assert printed_row_records(tagged, META, encodings) == []


def test_row_tagged_under_another_name_with_the_same_values_is_refused(tmp_path):
    encodings = _encodings(tmp_path, [_entry()])
    tagged = [{"_context_id": "C_9", "period": "2023-09-30", "investment_identifier": "HGH Term Loan A",
               "fair_value": 28434971.0, "cost": 27883696.0}]
    assert printed_row_records(tagged, META, encodings) == []


def test_comparative_context_of_the_same_row_does_not_block_it(tmp_path):
    # the filing holds the row's 2022-12-31 comparative context; that is not the quarter's row
    encodings = _encodings(tmp_path, [_entry()])
    comparative = [{"_context_id": "C_df52", "period": "2022-12-31",
                    "investment_identifier": "Debt Investments, Harvey Gulf Holdings, LLC, Acquisition Date 08/10/22 Term Loan A",
                    "fair_value": 32976372.0, "cost": 32838862.0}]
    assert len(printed_row_records(comparative, META, encodings)) == 1


def test_term_loan_does_not_match_term_loan_a_of_the_same_issuer(tmp_path):
    lenox = "Lenox Holdings, Inc. 07/08/22 Term Loan - 14.31% (SOFR + 8.75%, 1.00% Floor) 8.5 % $ 37,883,211 07/08/27 $ 37,312,266 $ 36,708,831"
    entry = _entry(issuer="Lenox Holdings, Inc.", instrument="Term Loan", fair_value=36708831, cost=37312266,
                   principal_amount=37883211, printed_line=lenox)
    encodings = _encodings(tmp_path, [entry])
    other = [{"_context_id": "C_2", "period": "2023-09-30",
              "investment_identifier": "Debt Investments, Lenox Holdings, Inc., Acquisition Date 01/01/23 Term Loan A",
              "fair_value": 1.0, "cost": 1.0}]
    assert len(printed_row_records(other, META, encodings)) == 1


def test_other_filings_and_funds_get_nothing(tmp_path):
    encodings = _encodings(tmp_path, [_entry()])
    assert printed_row_records([], {**META, "accession_number": "0000950170-23-040379"}, encodings) == []
    assert printed_row_records([], {**META, "cik": "0001715933"}, encodings) == []


@pytest.mark.parametrize("change", [
    {"fair_value": 28434972},            # a number the line does not print
    {"issuer": "Harvey Gulf Holdings"},  # fine: a prefix of the printed name is in the line
    {"instrument": "Term Loan C"},
    {"accession": "2023-09-30"},
    {"rate": "12.63"},                   # nothing beyond the declared fields
])
def test_loader_checks_each_entry_against_its_printed_line(tmp_path, change):
    entry = _entry(**change)
    if change == {"issuer": "Harvey Gulf Holdings"}:
        assert entry_errors(entry) == []
        return
    assert entry_errors(entry)
    with pytest.raises(ValueError):
        _encodings(tmp_path, [entry])


def test_loader_rejects_a_duplicate_row(tmp_path):
    with pytest.raises(ValueError):
        _encodings(tmp_path, [_entry(), _entry()])


def test_staging_sql_reads_the_declared_fields():
    con = duckdb.connect()
    facts = json.dumps({"_printed_page": {"issuer": "Lenox Holdings, Inc.", "instrument": "Term Loan", "industry": "Household Durables"}})
    row = con.execute("SELECT " + condition_sql("c") + ", " + declared_sql("issuer", "f") + ", " + declared_sql("industry", "f")
                      + " FROM (SELECT ? AS c, ? AS f)", [CONTEXT_PREFIX + "abc", facts]).fetchone()
    assert row == (True, "Lenox Holdings, Inc.", "Household Durables")
    assert con.execute("SELECT " + condition_sql("c") + " FROM (SELECT 'C_fa46a8e5' AS c)").fetchone()[0] is False


# --- acceptance checks (OVR-T8Z-R1): a declared printed row is 'printed_page_declared', non-blocking ---

PRINTED_CTX = CONTEXT_PREFIX + "0123456789abcdef"


def _output(**changes):
    from tests.test_validate_holdings import _make_bdc_output
    row = {"bdc_investment_identifier": "Harvey Gulf Holdings, LLC | Term Loan A",
           "bdc_dimensions_raw": "printedpage=Harvey Gulf Holdings, LLC | Term Loan A",
           "issuer_name": "Harvey Gulf Holdings, LLC", "fair_value": "28434971", "cost": "27883696",
           "principal_amount": "28265379", "src_context_id": PRINTED_CTX, "fair_value_source": "printed_page"}
    row.update(changes)
    return _make_bdc_output([row])


def _reconcile(output):
    from pipeline.source_reconciliation import reconcile_bdc_source_to_holdings
    from tests.test_validate_holdings import _make_bdc_source, _no_rescales
    return reconcile_bdc_source_to_holdings(_make_bdc_source([{}]).iloc[0:0], output,
                                            audited_value_rescales=_no_rescales())


UNDECLARED = [
    {"src_context_id": "", "fair_value_source": "xbrl_field"},          # a row with no context at all
    {"src_context_id": PRINTED_CTX, "fair_value_source": "xbrl_field"},  # the prefix alone is no declaration
    {"src_context_id": "C_fa46a8e5", "fair_value_source": "printed_page"},
]


def test_reconciliation_gives_a_declared_row_its_own_non_blocking_status():
    from pipeline.source_reconciliation import build_source_reconciliation_residual_classification
    detail, metrics = _reconcile(_output())
    assert len(detail) == 1
    row = detail.iloc[0]
    assert row["status"] == "printed_page_declared" and row["calibrated_status"] == "printed_page_declared"
    assert row["blocking_issue"] == False  # noqa: E712
    assert row["residual_class"] == "documented_exclusion"
    m = metrics.iloc[0]
    assert int(m["blocking_issue_count"]) == 0 and int(m["matched_rows"]) == 0 and int(m["output_rows"]) == 1
    classified = build_source_reconciliation_residual_classification(detail)
    assert list(classified["mechanism"]) == ["documented_printed_page_declared"]
    assert classified.iloc[0]["blocking_issue"] == False  # noqa: E712
    assert int(classified.iloc[0]["issue_count"]) == 1


@pytest.mark.parametrize("changes", UNDECLARED)
def test_reconciliation_keeps_an_undeclared_row_without_a_fact_blocking(changes):
    from pipeline.source_reconciliation import build_source_reconciliation_residual_classification
    detail, metrics = _reconcile(_output(**changes))
    row = detail.iloc[0]
    assert row["status"] == "extra_in_pipeline" and row["blocking_issue"] == True  # noqa: E712
    assert int(metrics.iloc[0]["blocking_issue_count"]) == 1
    classified = build_source_reconciliation_residual_classification(detail)
    assert list(classified["mechanism"]) == ["blocking_pipeline_only_position"]


def test_src_bdc02_tracks_a_declared_row_without_blocking():
    from pipeline.column_validation import adapt_validation_reports
    detail, _ = _reconcile(_output())
    issues = adapt_validation_reports({"source_reconciliation_detail": detail})
    assert issues[issues["rule_id"] == "SRC_BDC02"].empty
    tracked = issues[issues["rule_id"] == "SRC_BDC02P"]
    assert len(tracked) == 1
    assert (tracked.iloc[0]["severity"], tracked.iloc[0]["action"]) == ("INFO", "TRACK_ONLY")
    assert tracked.iloc[0]["message"].startswith("printed_page_declared")


@pytest.mark.parametrize("changes", UNDECLARED)
def test_src_bdc02_still_blocks_an_undeclared_row_without_a_fact(changes):
    from pipeline.column_validation import adapt_validation_reports
    detail, _ = _reconcile(_output(**changes))
    issues = adapt_validation_reports({"source_reconciliation_detail": detail})
    fired = issues[issues["rule_id"] == "SRC_BDC02"]
    assert len(fired) == 1 and fired.iloc[0]["severity"] == "FAIL"
    assert issues[issues["rule_id"] == "SRC_BDC02P"].empty


def _e07(extra_rows):
    import pandas as pd
    from pipeline.oracle_checks import check_E07_position_count_vs_filing
    detail = pd.DataFrame([{"cik": CIK, "report_date": "2023-09-30", "status": "matched"} for _ in range(10)])
    holdings = pd.DataFrame([{"cik": CIK, "report_date": "2023-09-30", "src_context_id": "C_%d" % i,
                              "fair_value_source": "xbrl_field"} for i in range(10)]
                            + [{"cik": CIK, "report_date": "2023-09-30", **r} for r in extra_rows])
    return check_E07_position_count_vs_filing(detail, holdings)


def test_e07_leaves_declared_rows_out_of_the_output_count_and_reports_them():
    printed = {"src_context_id": PRINTED_CTX, "fair_value_source": "printed_page"}
    results = _e07([printed, printed, dict(printed, src_context_id=CONTEXT_PREFIX + "fedcba9876543210")])
    assert [r.status for r in results] == ["pass"]
    assert "source=10 vs output=10" in results[0].message
    assert "printed_page_declared=3" in results[0].message


@pytest.mark.parametrize("changes", UNDECLARED)
def test_e07_still_counts_undeclared_rows_without_a_fact(changes):
    results = _e07([changes, changes])
    assert [r.status for r in results] == ["fail"]
    assert "source=10 vs output=12" in results[0].message
    assert "printed_page_declared" not in results[0].message


# --- OVR-T8Z-R2: printed terms on a declared row --------------------------------------------------

TERMS = {"interest_rate": 12.63, "basis_spread": 7.0, "interest_rate_floor": 1.0, "reference_rate_type": "SOFR",
         "maturity_date": "2027-08-10", "pct_of_net_assets": 6.6}


def test_printed_terms_are_carried_as_tagged_facts_would_be(tmp_path):
    encodings = _encodings(tmp_path, [_entry(**TERMS)])
    rec = printed_row_records([], META, encodings)[0]
    assert rec["interest_rate"] == pytest.approx(0.1263) and rec["basis_spread"] == pytest.approx(0.07)
    assert rec["interest_rate_floor"] == pytest.approx(0.01) and rec["pct_of_net_assets"] == pytest.approx(0.066)
    assert rec["reference_rate_type"] == "SOFR" and rec["maturity_date"] == "2027-08-10"
    assert json.loads(rec["src_facts"])["_printed_page"]["terms"] == TERMS


@pytest.mark.parametrize("change", [
    {"interest_rate": 12.6},              # 12.6% is not printed (12.63% is)
    {"interest_rate": 12.64},
    {"basis_spread": 6.0},
    {"interest_rate_floor": 7.0},         # 7.00% is printed, but as the spread, not before 'Floor'
    {"pct_of_net_assets": 6.3},           # another row's percent
    {"maturity_date": "2027-10-08"},      # day and month swapped
    {"reference_rate_type": "LIBOR"},
    {"interest_rate": "12.63"},           # text, not a number
    {"maturity_date": "08/10/27"},
])
def test_loader_refuses_a_term_not_printed_in_the_line(tmp_path, change):
    entry = _entry(**{**TERMS, **change})
    assert entry_errors(entry)
    with pytest.raises(ValueError):
        _encodings(tmp_path, [entry])


def test_printed_terms_in_another_spelling_are_admitted():
    # false-positive guard: the page spaces '%' and writes four-digit years on some lines
    line = ("Lenox Holdings, Inc. 07/08/22 Term Loan - 14.31 % (SOFR + 8.75 %, 1.00 % Floor) 8.5 % $ 37,883,211 "
            "07/08/2027 $ 37,312,266 $ 36,708,831")
    entry = _entry(issuer="Lenox Holdings, Inc.", instrument="Term Loan", fair_value=36708831, cost=37312266,
                   principal_amount=37883211, printed_line=line, interest_rate=14.31, basis_spread=8.75,
                   interest_rate_floor=1, reference_rate_type="SOFR", maturity_date="2027-07-08", pct_of_net_assets=8.5)
    assert entry_errors(entry) == []
