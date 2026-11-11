"""Ares Strategic Income's issuer-name strip cuts the asset-backed instrument the filer's member glues to the company
(nbas run, 2026-11-11).

From 2024-03-31 to 2026-03-31 the members of the fund's asset-backed rows read 'Isthmus Capital LLC, Private asset-backed
investment 1' or 'THPT 2023-THL, Commercial mortgage-backed security' with no separate instrument, so 251 rows published
the instrument inside issuer_name with a blank instrument (issuer_name_printed, 180 of 191 flagged rows). The page prints
'Isthmus Capital LLC Private asset-backed investment 9.50 % 06/2030 ...'. The wrapper's issuer_name_strip_re cuts the
trailing instrument (with the member's row number); issuer_name_strip_to_instrument keeps it as the instrument.
"""
import re

import pandas as pd
import pytest

from pipeline.staging_bdc import issuer_name_strip_patterns, issuer_name_strip_to_instrument_ciks
from pipeline.unified_holdings import _strip_issuer_names

CIK = "0001918712"


@pytest.fixture(scope="module")
def pattern():
    return issuer_name_strip_patterns()[CIK]


def test_strip_goes_to_instrument():
    assert CIK in issuer_name_strip_to_instrument_ciks()


@pytest.mark.parametrize("name, expected", [
    ("Isthmus Capital LLC, Private asset-backed investment 1", "Isthmus Capital LLC"),
    ("Vantage Data Centers Europe S.a r.l., Private asset backed investment", "Vantage Data Centers Europe S.a r.l."),
    ("THPT 2023-THL, Commercial mortgage-backed security", "THPT 2023-THL"),
    ("CAIF 1, Commercial mortgage-backed security 2", "CAIF 1"),
    ("JPMMT 2026-ACES1 , Residential mortgage-backed security", "JPMMT 2026-ACES1"),
    ("ALP CFO 2025, L.P. and Alp CFO 2025 (Offshore Feeder) A, L.P., Private asset-backed investment 3",
     "ALP CFO 2025, L.P. and Alp CFO 2025 (Offshore Feeder) A, L.P."),
    ("TI VI Holdings 1, L.P., Private asset-backed investment", "TI VI Holdings 1, L.P."),
])
def test_glued_instrument_is_cut(pattern, name, expected):
    assert re.sub(pattern, "", name) == expected


@pytest.mark.parametrize("name", [
    # false-positive guard: printed company names of this fund, including ones ending in a number or a finance word
    "CAIF 1",
    "TI VI Holdings 1, L.P.",
    "MCF CLO 12 LLC",
    "A8 - A (Feeder) L.P.",
    "OAKC 2021-16",
    "Steward Partners Global Advisory, LLC and Steward Partners Investment Advisory, LLC",
    "Sunbit Receivables Trust IV",
    # a loan member keeps its instrument (not this pattern's job)
    "Zayo Group Holdings, Inc., First lien senior secured loan",
    # left as filed on purpose: four Cannon Bridge tranches with tied fair values are told apart only by the
    # member's row number in the name; cut, the matcher re-paired them across tranches (nbasb: 4 correct links lost)
    "Cannon Bridge Designated Activity Company, Private asset-backed investment 1",
    "Cannon Bridge Designated Activity Company, Private asset-backed investment 5",
])
def test_other_names_unchanged(pattern, name):
    assert re.sub(pattern, "", name) == name


def test_printed_instrument_from_a_correction_is_not_overwritten(pattern):
    """Review round 2 (nbasd): on 8 rows the member says 'Private asset-backed investment' but the page prints another
    instrument ('Preferred shares', 'Class A common units', a first lien loan). Their row corrections set the printed
    instrument AND the printed company; with the company already clean the strip cuts nothing, so the printed instrument
    stays exactly as corrected (no 'Private asset-backed investment' put in front of it, no overwrite)."""
    frame = pd.DataFrame({"source": ["bdc"] * 3, "cik": [CIK] * 3,
                          "issuer_name": ["TI VI Holdings 1, L.P.", "GCM HVAC Holdco, LLC and GCM HVAC Topco, LLC",
                                          "Quintain Investments Holdings Limited"],
                          "instrument_description": ["Preferred shares", "First lien senior secured loan", "Class B common units"]})
    out = _strip_issuer_names(frame.copy(), {CIK: pattern}, {CIK})
    assert out["instrument_description"].tolist() == frame["instrument_description"].tolist()
    assert out["issuer_name"].tolist() == frame["issuer_name"].tolist()


def test_correcting_only_the_instrument_would_be_prefixed(pattern):
    """Why the corrections set the company too: with the member name left as filed, the strip puts its cut text in
    front of a different instrument ('Private asset-backed investment Preferred shares'), which is wrong."""
    frame = pd.DataFrame({"source": ["bdc"], "cik": [CIK],
                          "issuer_name": ["TI VI Holdings 1, L.P., Private asset-backed investment"],
                          "instrument_description": ["Preferred shares"]})
    out = _strip_issuer_names(frame, {CIK: pattern}, {CIK})
    assert out["instrument_description"].iloc[0] != "Preferred shares"


def test_cut_text_becomes_blank_instrument(pattern):
    frame = pd.DataFrame({"source": ["bdc", "bdc"], "cik": [CIK, CIK],
                          "issuer_name": ["Isthmus Capital LLC, Private asset-backed investment 2", "MCF CLO 12 LLC"],
                          "instrument_description": [None, "Private asset-backed investment"]})
    out = _strip_issuer_names(frame, {CIK: pattern}, {CIK})
    assert out["issuer_name"].tolist() == ["Isthmus Capital LLC", "MCF CLO 12 LLC"]
    assert out["instrument_description"].tolist() == ["Private asset-backed investment 2", "Private asset-backed investment"]
