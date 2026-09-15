"""E3-v2: a no-cached-filing exclusion is certified only by positive EDGAR evidence.

Run: python -m pytest tests/test_exclusion_context_audit.py -q
"""
import csv
import json
from pathlib import Path

import pytest

from scripts.run_exclusion_context_audit import assess_filing_gap, load_filing_gaps, run

CIK = "0001234567"
Q = "2023-03-31"
REGISTER_COLUMNS = ("cik,entity_name,report_date,eligibility_status,evidence_ids,holdings_rows,indexed_filings,"
                    "positive_investment_concept,positive_investment_amount,source_currency,"
                    "positive_source_accession,full_source_roster_reviewed,follow_up")
GAP_COLUMNS = "cik,entity,quarter,status,matching_accessions,earliest_periodic_report_date,periodic_filings_total"


def filing(report_date, accession="0001234567-23-000010", form="10-Q"):
    return dict(form=form, accession=accession, filing_date="2023-08-10", report_date=report_date, primary="x.htm")


def write_gaps(directory, status="no_filing_for_quarter", matching="", earliest="2023-06-30", total=2,
               filings=None, submissions=True):
    path = directory / "filing_gaps.csv"
    path.write_text(GAP_COLUMNS + "\n" + ",".join(
        (CIK, "Test Fund", Q, status, matching, earliest, str(total))) + "\n", encoding="utf-8")
    if submissions:
        if filings is None:
            filings = [filing("2023-06-30"), filing("2023-09-30", "0001234567-23-000020")]
        (directory / (CIK + ".json")).write_text(json.dumps(dict(name="Test Fund", filings=filings)), encoding="utf-8")
    return path


def companyfacts(directory, events):
    (directory / (CIK + ".json")).write_text(json.dumps(dict(cik=int(CIK), facts={"us-gaap": {
        "InvestmentOwnedAtFairValue": {"units": {"USD": events}}}})), encoding="utf-8")


def fact(end, val, filed="2023-08-10", accn="0001234567-23-000010"):
    return dict(end=end, val=val, accn=accn, filed=filed, form="10-Q")


def make_fixture(tmp_path):
    register = tmp_path / "obligations.csv"
    register.write_text(REGISTER_COLUMNS + "\n" + ",".join(
        (CIK, "Test Fund", Q, "not_yet_investment_operating", "LIFE-" + CIK, "0", "0", "", "", "", "", "False", "")) + "\n",
        encoding="utf-8")
    index = tmp_path / "bdc_filings_index.csv"
    index.write_text("cik,report_date,filing_date,accession_number,form_type\n"
                     "9999999,2023-03-31,2023-05-01,0000000000-23-000001,10-Q\n", encoding="utf-8")
    cf_dir = tmp_path / "companyfacts"
    cf_dir.mkdir()
    companyfacts(cf_dir, [fact("2023-06-30", 5_000_000)])
    gaps_dir = tmp_path / "gaps"
    gaps_dir.mkdir()
    return dict(register=register, index=index, companyfacts_dir=cf_dir, instances_dir=tmp_path / "instances",
                expected=1, gaps_dir=gaps_dir, dest=tmp_path / "e3")


@pytest.fixture
def fixture(tmp_path):
    return make_fixture(tmp_path)


def audit(fixture, **kwargs):
    options = {k: v for k, v in fixture.items() if k not in ("gaps_dir", "dest")}
    options.update(kwargs)
    run(fixture["dest"], **options)
    summary = json.loads((fixture["dest"] / "summary.json").read_text())
    with (fixture["dest"] / "exclusions.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    return summary, rows[0], json.loads((fixture["dest"] / (CIK + "_" + Q + ".json")).read_text())


def test_without_filing_gaps_no_accession_stays_unassessable(fixture):
    summary, row, _ = audit(fixture)
    assert row["verdict"] == "exclusion_unassessable" and row["accession"] == ""
    assert summary["denominator_certifiable"] is False and summary["filing_gaps"] is None


def test_edgar_absence_with_later_first_report_certifies(fixture):
    gaps = write_gaps(fixture["gaps_dir"])
    summary, row, record = audit(fixture, filing_gaps=gaps)
    assert row["verdict"] == "no_periodic_filing_confirmed"
    assert row["secondary_check"] == "clear" and row["earliest_periodic_report_date"] == "2023-06-30"
    assert summary["denominator_certifiable"] is True
    assert summary["verdicts"]["no_periodic_filing_confirmed"] == 1
    assert summary["filing_gaps"]["sha256"] in summary["input_sha256"].values()
    assert summary["filing_gaps"]["path"] == str(gaps.resolve())
    assert record["filing_gap"]["submissions_json_sha256"] == summary["filing_gaps"]["submissions_json_sha256"][CIK]
    assert record["filing_gap"]["json_periodic_filings_total"] == 2


def test_filing_exists_not_indexed_contradicts(fixture):
    gaps = write_gaps(fixture["gaps_dir"], status="filing_exists_not_indexed", matching="0001234567-23-000005:10-Q",
                      earliest=Q, filings=[filing(Q, "0001234567-23-000005"), filing("2023-06-30")])
    summary, row, _ = audit(fixture, filing_gaps=gaps)
    assert row["verdict"] == "exclusion_contradicted_filing_exists"
    assert summary["denominator_certifiable"] is False
    assert summary["verdicts"]["exclusion_contradicted_filing_exists"] == 1


def test_prior_positive_companyfacts_fact_contradicts_despite_edgar_absence(fixture):
    # A first 10-Q for 2023-06-30 can carry a positive comparative instant at
    # or before the quarter: companyfacts is the secondary contradiction source.
    companyfacts(fixture["companyfacts_dir"], [fact("2022-12-31", 250_000), fact("2023-06-30", 5_000_000)])
    gaps = write_gaps(fixture["gaps_dir"])
    summary, row, record = audit(fixture, filing_gaps=gaps)
    assert row["verdict"] == "exclusion_contradicted" and row["secondary_check"] == "contradicted"
    assert row["prior_positive_facts"] == "1" and row["prior_positive_earliest"] == "2022-12-31"
    assert record["prior_positive_facts"]["max_amount"] == 250_000
    assert summary["denominator_certifiable"] is False


def test_missing_filing_gap_row_stays_unassessable(fixture):
    gaps = write_gaps(fixture["gaps_dir"])
    gaps.write_text(GAP_COLUMNS + "\n" + ",".join(
        ("0007654321", "Other Fund", Q, "no_filing_for_quarter", "", "2023-06-30", "2")) + "\n", encoding="utf-8")
    summary, row, _ = audit(fixture, filing_gaps=gaps)
    assert row["verdict"] == "exclusion_unassessable" and row["filing_gap_reason"] == "no_filing_gap_row"
    assert summary["denominator_certifiable"] is False


def test_submissions_error_stays_unassessable(fixture):
    gaps = write_gaps(fixture["gaps_dir"], status="submissions_error", earliest="", total=0, submissions=False)
    _, row, _ = audit(fixture, filing_gaps=gaps)
    assert row["verdict"] == "exclusion_unassessable" and row["filing_gap_reason"] == "submissions_error"


def test_filing_gaps_hash_mismatch_is_refused(fixture):
    gaps = write_gaps(fixture["gaps_dir"])
    with pytest.raises(ValueError, match="sha256 mismatch"):
        audit(fixture, filing_gaps=gaps, filing_gaps_sha256="0" * 64)
    assert not (fixture["dest"] / "summary.json").exists()


def test_filing_gaps_hash_match_accepted(fixture):
    gaps = write_gaps(fixture["gaps_dir"])
    expected = load_filing_gaps(gaps)["sha256"]
    summary, row, _ = audit(fixture, filing_gaps=gaps, filing_gaps_sha256=expected.upper())
    assert row["verdict"] == "no_periodic_filing_confirmed" and summary["filing_gaps"]["sha256"] == expected


def test_incomplete_companyfacts_blocks_certification(fixture):
    (fixture["companyfacts_dir"] / (CIK + ".json")).unlink()
    gaps = write_gaps(fixture["gaps_dir"])
    _, row, _ = audit(fixture, filing_gaps=gaps)
    assert row["verdict"] == "exclusion_unassessable" and row["secondary_check"] == "unavailable"
    assert row["filing_gap_reason"] == "companyfacts_secondary_check_unavailable"


def test_csv_row_must_agree_with_its_submissions_json(tmp_path):
    gaps = load_filing_gaps(write_gaps(tmp_path, earliest="2023-09-30"))
    verdict, evidence = assess_filing_gap(CIK, Q, gaps)
    assert verdict is None and evidence["reason"] == "csv_json_disagreement"


def test_first_report_at_or_before_quarter_cannot_certify(tmp_path):
    gaps = load_filing_gaps(write_gaps(tmp_path, earliest=Q, filings=[filing(Q), filing("2023-06-30")],
                                       matching="", status="no_filing_for_quarter"))
    verdict, evidence = assess_filing_gap(CIK, Q, gaps)
    assert verdict is None and evidence["reason"] == "csv_json_disagreement"
    gaps = load_filing_gaps(write_gaps(tmp_path, earliest="2022-12-31", total=1, filings=[filing("2022-12-31")]))
    verdict, evidence = assess_filing_gap(CIK, Q, gaps)
    assert verdict is None and evidence["reason"] == "earliest_periodic_report_not_after_quarter"


def test_empty_edgar_history_is_absence_not_evidence(tmp_path):
    gaps = load_filing_gaps(write_gaps(tmp_path, earliest="", total=0, filings=[]))
    verdict, evidence = assess_filing_gap(CIK, Q, gaps)
    assert verdict is None and evidence["reason"] == "no_periodic_filings_on_edgar"


def test_duplicate_fund_quarter_rows_rejected(tmp_path):
    path = write_gaps(tmp_path)
    path.write_text(path.read_text() + path.read_text().splitlines()[1] + "\n")
    with pytest.raises(ValueError, match="repeats"):
        load_filing_gaps(path)
