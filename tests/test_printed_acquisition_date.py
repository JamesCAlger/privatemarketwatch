"""The acquisition date printed in a schedule's own column reaches the holdings where none is tagged.

Ares Capital prints 'Acquisition Date' as MM/YYYY on every tranche and BCRED as M/D/YYYY (since
its 2024-09-30 10-Q); neither tags us-gaap:InvestmentAcquisitionDate. The page reader resolved the
column but the field-status artifact and its overlay dropped it (2026-10-14).
"""
import pandas as pd

from pipeline.bdc_xbrl_html_bridge import (
    apply_ixbrl_field_status_overlay,
    build_field_status_rows,
    field_status,
)

HEADER = {0: "Company", 1: "Spread", 2: "Acquisition Date", 3: "Maturity Date", 4: "Principal"}


def test_a_month_year_acquisition_cell_under_its_header_is_a_value():
    out = field_status("acquisition_date", ["Flexera Software LLC", "4.75 %", "08/2025", "08/2032", "18.6"], HEADER)
    assert out["status"] == "value"
    assert out["value"] == "2025-08-31"


def test_a_full_date_acquisition_cell_is_read():
    out = field_status("acquisition_date", ["JSS Holdings, Inc.", "SOFR + 5.00 %", "12/29/2021", "11/8/2031", "247,803"], HEADER)
    assert (out["value"], out["status"]) == ("2021-12-29", "value")


def test_an_empty_acquisition_cell_is_blank_not_a_maturity():
    out = field_status("acquisition_date", ["Poseidon IntermediateCo, Inc.", "4.50 %", "", "06/2032", "27,126.3"], HEADER)
    assert out["value"] == ""
    assert out["status"] == "blank"


def test_field_status_rows_carry_the_acquisition_date():
    bridges = [{"investment_identifier": "Acme 1", "maturity_date": "2029-05-25", "maturity_status": "value",
                "acquisition_date": "2024-11-08", "acquisition_status": "value", "lien_position": ""}]
    common = {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "period": "2025-12-31"}
    flat = [{**common, "investment_identifier": "Acme 1", "fair_value": 1e6},
            {**common, "investment_identifier": "Ghost 1", "fair_value": 1e6}]
    by = {r["raw_id_lower"]: r for r in build_field_status_rows(bridges, flat, {})}
    assert (by["acme 1"]["acquisition_date"], by["acme 1"]["acquisition_status"]) == ("2024-11-08", "value")
    assert by["ghost 1"]["acquisition_status"] == "not_found"


def _staged(**over):
    row = {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
           "bdc_investment_identifier": "Acme 1", "maturity_date": "", "reference_rate_type": "",
           "lien_position": "", "reference_rate_source": "", "bdc_acquisition_date": "", "src_transforms": ""}
    row.update(over)
    return pd.DataFrame([row])


def _status(**over):
    row = {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31", "raw_id_lower": "acme 1",
           "acquisition_date": "2024-11-08", "acquisition_status": "value"}
    row.update(over)
    return [row]


def test_overlay_fills_a_blank_acquisition_date_and_says_it_came_from_the_page():
    out = apply_ixbrl_field_status_overlay(_staged(), _status())
    assert out.iloc[0]["bdc_acquisition_date"] == "2024-11-08"
    assert "bdc_acquisition_date:printed_page" in out.iloc[0]["src_transforms"]


def test_overlay_never_replaces_a_tagged_acquisition_date():
    out = apply_ixbrl_field_status_overlay(_staged(bdc_acquisition_date="2023-01-15"), _status())
    assert out.iloc[0]["bdc_acquisition_date"] == "2023-01-15"
    assert "bdc_acquisition_date:printed_page" not in out.iloc[0]["src_transforms"]


def test_overlay_ignores_an_acquisition_date_read_without_its_header():
    out = apply_ixbrl_field_status_overlay(_staged(), _status(acquisition_status="validation_needed"))
    assert out.iloc[0]["bdc_acquisition_date"] == ""


def test_staging_reads_rows_that_carry_only_an_acquisition_date(tmp_path):
    from pipeline.staging_bdc import read_ixbrl_field_status
    path = tmp_path / "bdc_ixbrl_field_status.csv"
    pd.DataFrame([
        {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "raw_id_lower": "acme 1",
         "maturity_status": "blank", "lien_status": "blank", "reference_rate_status": "blank",
         "sector_status": "blank", "acquisition_date": "2024-11-08", "acquisition_status": "value"},
        {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "raw_id_lower": "beta 1",
         "maturity_status": "blank", "lien_status": "blank", "reference_rate_status": "blank",
         "sector_status": "blank", "acquisition_date": "", "acquisition_status": "blank"},
    ]).to_csv(path, index=False)
    frame = read_ixbrl_field_status(path)
    assert list(frame["raw_id_lower"]) == ["acme 1"]
    assert frame.iloc[0]["acquisition_date"] == "2024-11-08"


def test_staging_reads_an_artifact_written_before_the_acquisition_columns(tmp_path):
    from pipeline.staging_bdc import read_ixbrl_field_status
    path = tmp_path / "bdc_ixbrl_field_status.csv"
    pd.DataFrame([{"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "raw_id_lower": "acme 1",
                   "maturity_date": "2029-01-31", "maturity_status": "value", "lien_status": "blank",
                   "reference_rate_status": "blank"}]).to_csv(path, index=False)
    frame = read_ixbrl_field_status(path)
    assert list(frame["raw_id_lower"]) == ["acme 1"]


def test_overlay_drops_a_printed_date_after_the_report_date():
    out = apply_ixbrl_field_status_overlay(_staged(), _status(acquisition_date="2026-08-31"))
    assert out.iloc[0]["bdc_acquisition_date"] == ""


def test_overlay_does_not_add_an_acquisition_column_to_frames_without_one():
    staged = _staged().drop(columns=["bdc_acquisition_date"])
    out = apply_ixbrl_field_status_overlay(staged, _status())
    assert "bdc_acquisition_date" not in out.columns
