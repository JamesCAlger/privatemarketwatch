"""The field-status refresh replaces the named funds' rows and nothing else."""
import csv

import pytest

from scripts.refresh_ixbrl_field_status import splice

HEADER = ["cik", "accession_number", "raw_id_lower", "reference_rate_type", "reference_rate_status"]


def _write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_only_the_named_fund_is_replaced(tmp_path):
    existing = _write(tmp_path / "existing.csv", [
        ["0001812554", "A", "hg genesis | unsecured facility", "EURIBOR", "validation_needed"],
        ["0001812554", "A", "gone from the page", "", "blank"],
        ["0001838126", "B", "southern graphics", "SOFR", "value"]])
    fresh = _write(tmp_path / "fresh.csv", [["0001812554", "A", "hg genesis | unsecured facility", "EURIBOR", "value"]])
    counts = splice(existing, fresh, ["0001812554"], tmp_path / "out.csv")
    rows = _read(tmp_path / "out.csv")
    assert counts == {"kept": 1, "replaced": 2, "written": 1}
    assert [(r["cik"], r["reference_rate_status"]) for r in rows] == [("0001838126", "value"), ("0001812554", "value")]
    assert rows[0]["raw_id_lower"] == "southern graphics" and rows[0]["cik"] == "0001838126"  # leading zeros kept


def test_rows_for_a_fund_that_was_not_named_are_refused(tmp_path):
    existing = _write(tmp_path / "existing.csv", [["0001838126", "B", "southern graphics", "SOFR", "value"]])
    fresh = _write(tmp_path / "fresh.csv", [["0001838126", "B", "southern graphics", "", "blank"]])
    with pytest.raises(ValueError):
        splice(existing, fresh, ["0001812554"], tmp_path / "out.csv")


def test_a_column_added_since_the_artifact_was_written_is_empty_for_the_other_funds(tmp_path):
    existing = _write(tmp_path / "existing.csv", [["0001838126", "B", "southern graphics", "SOFR", "value"]])
    with open(tmp_path / "fresh.csv", "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([HEADER[:4] + ["printed_margin"] + HEADER[4:], ["0001812554", "A", "inovalon", "SOFR", "5.5", "value"]])
    splice(existing, tmp_path / "fresh.csv", ["0001812554"], tmp_path / "out.csv")
    rows = _read(tmp_path / "out.csv")
    assert list(rows[0]) == HEADER[:4] + ["printed_margin"] + HEADER[4:]
    assert [(r["cik"], r["printed_margin"], r["reference_rate_status"]) for r in rows] == [
        ("0001838126", "", "value"), ("0001812554", "5.5", "value")]


def test_a_re_read_that_lacks_a_column_is_refused(tmp_path):
    existing = _write(tmp_path / "existing.csv", [["0001812554", "A", "x", "", "blank"]])
    with open(tmp_path / "fresh.csv", "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([HEADER[:-1], ["0001812554", "A", "x", ""]])
    with pytest.raises(ValueError):
        splice(existing, tmp_path / "fresh.csv", ["0001812554"], tmp_path / "out.csv")
