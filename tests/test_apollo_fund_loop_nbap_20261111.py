"""Apollo Debt Solutions (0001837532), fund loop nbap 2026-11-11.

- Group headings printed in the company column before the company ('Gannett Gannett Holdings, LLC',
  'Health Care Health Care Providers & Services Advarra Advarra Holdings, Inc.') are cut by the wrapper's
  issuer_name_strip_re (exact-name alternatives); names where the cut would leave an ambiguous or misprinted
  company ('SAVATREE CI', 'Mariani CI', 'Tivity Health Health, Inc.') and printed names that only look like
  headings ('Investment Company 24 Bidco Limited') are left alone.
- Three filings print undrawn lines' negative cost in brackets but tag it unsigned
  (source_encodings.bracketed_unsigned_values); the 2024-12-31 and 2025-06-30 filings are not listed because
  their comparative block reads the other way.
- Context-keyed issuer-name and cost-sign corrections from the printed page are recorded.
"""
import csv
import re

import pytest

from pipeline import config

APOLLO = "0001837532"


def _strip():
    from pipeline import staging_bdc
    return re.compile(staging_bdc.issuer_name_strip_patterns()[APOLLO])


@pytest.mark.parametrize("name,expected", [
    ("Gannett Gannett Holdings, LLC", "Gannett Holdings, LLC"),
    ("Gannett Co., Inc. Gannett Holdings, LLC", "Gannett Holdings, LLC"),
    ("Health Care Health Care Providers & Services Advarra Advarra Holdings, Inc.", "Advarra Holdings, Inc."),
    ("Dental Care Alliance DCA Investment Holding LLC", "DCA Investment Holding LLC"),
    ("Trench Plate Rental Co. Trench Safety Solutions Holdings, LLC", "Trench Safety Solutions Holdings, LLC"),
    ("Apterra Project Ram Microsoft DC QTS Project Ram", "QTS Project Ram"),
    ("ECS Group Quito", "Quito"),
    ("Tivity Health Tivity Health, Inc.", "Tivity Health, Inc."),
])
def test_printed_group_heading_is_cut(name, expected):
    assert _strip().sub("", name, count=1) == expected


@pytest.mark.parametrize("name", [
    "SAVATREE CI", "Mariani CI", "Tivity Health Health, Inc.", "Investment Company 24 Bidco Limited",
    "CNSI CNSI Holdings, LLC", "Gannett Holdings, LLC", "Advarra Holdings, Inc.", "Gannett Gannett Holdings, LLC Extra",
])
def test_other_names_are_left_alone(name):
    assert _strip().sub("", name, count=1) == name


def test_bracketed_unsigned_filings_are_listed_and_the_misread_ones_are_not():
    from pipeline.printed_sign import listed_accessions
    listed = listed_accessions(APOLLO)
    assert {"0000950170-23-061985", "0000950170-24-031479", "0000950170-24-094137"} <= listed
    assert "0000950170-25-038785" not in listed and "0000950170-25-105984" not in listed


def test_page_corrections_are_recorded():
    with open(config.ROW_CORRECTIONS_BY_CONTEXT_FILE, encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["cik"] == APOLLO and r["author"] == "fund-agent-0001837532-nbap-2026-11-11"]
    names = {(r["report_date"], r["value"]) for r in rows if r["field"] == "issuer_name"}
    assert ("2026-03-31", "Quito") in names and ("2024-09-30", "All Star Recruiting Locums, LLC") in names
    costs = [r for r in rows if r["field"] == "cost"]
    assert costs and all(r["report_date"] == "2025-06-30" and float(r["value"]) < 0 for r in costs)
    assert all(r["src_context_id"] and "Printed (" in r["reason"] for r in rows)
    # round 3: instruments set to the printed instrument carry no member rate or maturity text
    instr = [r for r in rows if r["field"] == "instrument_description"]
    assert instr and all(r["value"].startswith("First Lien Secured Debt - ") and "Interest Rate" not in r["value"]
                         and "Maturity" not in r["value"] for r in instr)
    assert all(r["value"] == "USD" for r in rows if r["field"] == "principal_amount_currency")
    assert ("2024-06-30", "Ironhorse Purchaser, LLC") in names
