"""Row corrections may set nonaccrual_footnote from the printed schedule's non-accrual marker (2026-10-17, Crescent).

The financial step derives nonaccrual_status from nonaccrual_footnote, so the correction has to land as a real
boolean; anything other than 'true' or 'false' is skipped.
"""
import csv

import duckdb
import pandas as pd

from pipeline.unified_holdings import UNIFIED_COLUMNS, _apply_row_corrections

KEY = {"cik": "0001633336", "report_date": "2024-06-30", "accession_number": "0000950170-24-095458",
       "bdc_investment_identifier": "Investments United States Debt Investments Seko Global Logistics Network, LLC Term Loan"}
OTHER = dict(KEY, bdc_investment_identifier="Investments United States Debt Investments Service Logic Acquisition, Inc. Term Loan")


def _frame(*rows):
    data = []
    for row in rows:
        full = {c: "" for c in UNIFIED_COLUMNS}
        full.update(row)
        data.append(full)
    frame = pd.DataFrame(data)
    frame["nonaccrual_footnote"] = False
    return frame


def _corrections(tmp_path, value):
    path = tmp_path / "row_corrections.csv"
    cols = ["cik", "report_date", "accession_number", "bdc_investment_identifier", "field", "value", "reason",
            "source_evidence", "author", "date_added"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerow(dict(KEY, field="nonaccrual_footnote", value=value,
                             reason="Printed 'Seko Global Logistics Network, LLC (9)(11) ...'; (9) = non-accrual",
                             source_evidence="cached filing", author="test", date_added="2026-10-17"))
    return path


def test_printed_marker_sets_nonaccrual_footnote_as_boolean(tmp_path):
    result = _apply_row_corrections(_frame(dict(KEY, source="bdc"), dict(OTHER, source="bdc")),
                                    corrections_path=_corrections(tmp_path, "true"))
    seko = result[result["bdc_investment_identifier"] == KEY["bdc_investment_identifier"]].iloc[0]
    assert seko["nonaccrual_footnote"] is True or seko["nonaccrual_footnote"] == True  # noqa: E712
    assert "nonaccrual_footnote" in seko["corrected_fields"]
    # the CSV round trip the financial step reads: TRY_CAST(... AS BOOLEAN) must see true
    stored = str(seko["nonaccrual_footnote"])
    assert duckdb.sql(f"SELECT TRY_CAST('{stored}' AS BOOLEAN)").fetchone()[0] is True


def test_other_rows_keep_their_footnote_flag(tmp_path):
    result = _apply_row_corrections(_frame(dict(KEY, source="bdc"), dict(OTHER, source="bdc")),
                                    corrections_path=_corrections(tmp_path, "true"))
    other = result[result["bdc_investment_identifier"] == OTHER["bdc_investment_identifier"]].iloc[0]
    assert bool(other["nonaccrual_footnote"]) is False
    assert "nonaccrual_footnote" not in str(other["corrected_fields"] or "")


def test_integer_flag_column_stays_scannable_by_duckdb(tmp_path):
    # the combined frame can carry the flag as 0/1 in an object column; a Python bool in it broke
    # the next DuckDB scan in sandbox ccza (Type BOOLEAN does not match with INTEGER)
    frame = _frame(dict(KEY, source="bdc"), dict(OTHER, source="bdc"))
    frame["nonaccrual_footnote"] = pd.Series([0, 0], dtype=object)
    result = _apply_row_corrections(frame, corrections_path=_corrections(tmp_path, "true"))
    con = duckdb.connect()
    con.register("h", result[["bdc_investment_identifier", "nonaccrual_footnote"]])
    got = dict(con.execute("SELECT bdc_investment_identifier, TRY_CAST(nonaccrual_footnote AS BOOLEAN) FROM h").fetchall())
    assert got == {KEY["bdc_investment_identifier"]: True, OTHER["bdc_investment_identifier"]: False}


def test_value_other_than_true_or_false_is_skipped(tmp_path):
    for bad in ("yes", "nonaccrual", "1x"):
        result = _apply_row_corrections(_frame(dict(KEY, source="bdc")), corrections_path=_corrections(tmp_path, bad))
        assert bool(result.iloc[0]["nonaccrual_footnote"]) is False
        assert "nonaccrual_footnote" not in str(result.iloc[0]["corrected_fields"] or "")
