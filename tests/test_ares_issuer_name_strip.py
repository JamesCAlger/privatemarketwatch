"""Ares Capital's issuer-name strip cuts instrument text the filer's member glued to the company (nbar run, 2026-11-11).

In 2024-12-31, 2025-09-30 and 2025-12-31 some members carry no ', ' between company and instrument
('Doxim Inc. First lien senior secured loan', 'MC Accelerate ... (UK) Ltd.Z2 preferred shares'), so 22 rows
published the instrument inside issuer_name with a blank instrument. The page prints 'Doxim Inc. (13) Enterprise
content management provider First lien senior secured revolving loan ...'. The wrapper's issuer_name_strip_re
cuts the trailing instrument; issuer_name_strip_to_instrument keeps it as the instrument, and
instrument_description_strip_re drops the doubled 'First lien senior secured loan' of Titan BW.
"""
import re

import pytest

from pipeline.staging_bdc import instrument_description_strip_patterns, issuer_name_strip_patterns, \
    issuer_name_strip_to_instrument_ciks

CIK = "0001287750"


@pytest.fixture(scope="module")
def pattern():
    return issuer_name_strip_patterns()[CIK]


def test_strip_goes_to_instrument():
    assert CIK in issuer_name_strip_to_instrument_ciks()


@pytest.mark.parametrize("name, expected", [
    ("Doxim Inc. First lien senior secured loan", "Doxim Inc."),
    ("Doxim Inc. First lien senior secured revolving loan", "Doxim Inc."),
    ("Sport Maska Inc. First lien senior secured revolving loan 2", "Sport Maska Inc."),
    ("Titan BW Borrower L.P. First lien senior secured loan First lien senior secured loan", "Titan BW Borrower L.P."),
    ("MC Accelerate Co-Invest Feeder LP and MC CIF Wealth Management (UK) Ltd.Z2 preferred shares 1",
     "MC Accelerate Co-Invest Feeder LP and MC CIF Wealth Management (UK) Ltd."),
    ("Nordic Ferry Infrastructure AS Senior subordinated loan 2", "Nordic Ferry Infrastructure AS"),
    ("Zeppelin US Buyer Inc. and Providence Equity Partners IX-C L.P. Limited partnership interest",
     "Zeppelin US Buyer Inc. and Providence Equity Partners IX-C L.P."),
    ("MC Accelerate Co-Invest Feeder LP and MC CIF Wealth Management (UK) Ltd. Membership interest",
     "MC Accelerate Co-Invest Feeder LP and MC CIF Wealth Management (UK) Ltd."),
])
def test_glued_instrument_is_cut(pattern, name, expected):
    assert re.sub(pattern, "", name) == expected


@pytest.mark.parametrize("name", [
    # false-positive guard: printed company names, including ones that end in a number or hold finance words
    "Senior Direct Lending Program, LLC",
    "Ivy Hill Asset Management, L.P.",
    "PCG-Ares Sidecar Investment II, L.P.",
    "NBLY 2021-1 and KKR Nest Co-Invest L.P.",
    "ARES 2007-3R",
    "Alcami Corporation and ACM Note Holdings, LLC",
])
def test_company_names_unchanged(pattern, name):
    assert re.sub(pattern, "", name) == name


def test_doubled_instrument_text_dedup():
    inst = instrument_description_strip_patterns()[CIK]
    assert re.sub(inst, "", "First lien senior secured loan First lien senior secured loan") == "First lien senior secured loan"
    assert re.sub(inst, "", "First lien senior secured loan") == "First lien senior secured loan"
    assert re.sub(inst, "", "First lien senior secured loan 2") == "First lien senior secured loan 2"
