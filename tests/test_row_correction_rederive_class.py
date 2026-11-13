"""REQ-rftc-1 / SVC-R2 (approved D-263): instrument_type and lien_position are re-derived after a row
correction replaces the instrument text, and both are explicitly correctable.

Both classes are first derived from the row text and the filer's member string. A correction of the
instrument text from the printed page replaces that member text as evidence (Apollo 2026-03-31 Olympus
Water: member 'Delayed Draw', page 'Corporate Bond'; Ares Zeppelin: member 'revolving loan', page a term
loan; Silver Capital Recipe: printed under 'Unsecured Debt', published 'Second Lien').
"""
import csv

import pandas as pd

from pipeline.unified_holdings import UNIFIED_COLUMNS, _apply_row_corrections

KEY = {"cik": "0001837532", "report_date": "2026-03-31", "accession_number": "0001193125-26-000001",
       "bdc_investment_identifier": "Olympus Water US Holding Corporation First Lien Delayed Draw Term Loan"}
OTHER = dict(KEY, bdc_investment_identifier="Acme Corp First Lien Revolving Loan")


def _frame(*rows):
    data = []
    for row in rows:
        full = {c: "" for c in UNIFIED_COLUMNS}
        full.update(row)
        data.append(full)
    return pd.DataFrame(data)


def _corrections(tmp_path, *patches):
    path = tmp_path / "row_corrections.csv"
    cols = ["cik", "report_date", "accession_number", "bdc_investment_identifier", "field", "value", "reason",
            "source_evidence", "author", "date_added"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for key, field, value in patches:
            writer.writerow(dict(key, field=field, value=value, reason="printed line", source_evidence="cached filing",
                                 author="test", date_added="2026-11-13"))
    return path


def _row(result, key):
    return result[result["bdc_investment_identifier"] == key["bdc_investment_identifier"]].iloc[0]


def _base(**over):
    row = dict(KEY, source="bdc", issuer_name="Olympus Water US Holding Corporation",
               instrument_description="First Lien Delayed Draw Term Loan",
               instrument_type="Delayed Draw Term Loan", lien_position="First Lien")
    row.update(over)
    return row


def test_corrected_bond_text_clears_the_member_loan_class(tmp_path):
    frame = _frame(_base(), dict(OTHER, source="bdc", issuer_name="Acme Corp", instrument_description="Revolver",
                                 instrument_type="Revolver", lien_position="First Lien"))
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (KEY, "instrument_description", "First Lien Secured Debt - Corporate Bond")))
    row = _row(result, KEY)
    assert row["instrument_type"] is None or pd.isna(row["instrument_type"])
    assert row["lien_position"] == "First Lien"
    assert "instrument_type" in row["corrected_fields"]
    other = _row(result, OTHER)
    assert other["instrument_type"] == "Revolver"
    assert "instrument_type" not in str(other["corrected_fields"] or "")


def test_corrected_term_loan_text_overrides_revolving_member(tmp_path):
    key = dict(KEY, bdc_investment_identifier="Zeppelin US Buyer Inc. First lien senior secured revolving loan")
    frame = _frame(dict(key, source="bdc", issuer_name="Zeppelin US Buyer Inc.",
                        instrument_description="First lien senior secured revolving loan",
                        instrument_type="Revolver", lien_position="First Lien"))
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (key, "instrument_description", "First lien senior secured term loan")))
    assert _row(result, key)["instrument_type"] == "Term Loan"


def test_loan_text_without_subtype_keeps_member_class(tmp_path):
    # False-positive guard: 'First lien senior secured loan' names no sub-type; a real revolver keeps its class.
    frame = _frame(_base(instrument_type="Revolver"))
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (KEY, "instrument_description", "First lien senior secured loan")))
    row = _row(result, KEY)
    assert row["instrument_type"] == "Revolver"
    assert "instrument_type" not in row["corrected_fields"]


def test_name_only_correction_keeps_class(tmp_path):
    # False-positive guard: a name cleanup is not instrument evidence.
    frame = _frame(_base(instrument_description=""))
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (KEY, "issuer_name", "Olympus Water US Holding Corp.")))
    row = _row(result, KEY)
    assert row["instrument_type"] == "Delayed Draw Term Loan"
    assert row["lien_position"] == "First Lien"


def test_explicit_instrument_type_wins_over_rederivation(tmp_path):
    frame = _frame(_base())
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (KEY, "instrument_description", "First lien senior secured loan"),
        (KEY, "instrument_type", "Term Loan")))
    assert _row(result, KEY)["instrument_type"] == "Term Loan"


def test_corrected_unsecured_text_rederives_lien(tmp_path):
    frame = _frame(_base(instrument_description="Second Lien Term Loan", instrument_type="Term Loan",
                         lien_position="Second Lien"))
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (KEY, "instrument_description", "Unsecured Debt")))
    row = _row(result, KEY)
    assert row["lien_position"] == "Unsecured"
    assert "lien_position" in row["corrected_fields"]


def test_text_without_lien_keeps_lien(tmp_path):
    frame = _frame(_base())
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (KEY, "instrument_description", "Term Loan")))
    row = _row(result, KEY)
    assert row["lien_position"] == "First Lien"
    assert row["instrument_type"] == "Term Loan"


def test_explicit_lien_correction_applies(tmp_path):
    frame = _frame(_base())
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (KEY, "lien_position", "Unsecured")))
    assert _row(result, KEY)["lien_position"] == "Unsecured"


def test_explicit_class_outside_vocabulary_is_skipped(tmp_path):
    frame = _frame(_base())
    result = _apply_row_corrections(frame, corrections_path=_corrections(
        tmp_path, (KEY, "instrument_type", "Corporate Bond"), (KEY, "lien_position", "Senior")))
    row = _row(result, KEY)
    assert row["instrument_type"] == "Delayed Draw Term Loan"
    assert row["lien_position"] == "First Lien"


def test_explicit_empty_class_withdraws_it(tmp_path):
    frame = _frame(_base())
    result = _apply_row_corrections(frame, corrections_path=_corrections(tmp_path, (KEY, "instrument_type", "")))
    value = _row(result, KEY)["instrument_type"]
    assert value is None or pd.isna(value)
