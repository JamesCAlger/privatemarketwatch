"""BCRED's issuer-name strip keeps the fund's own JV LP interests whole (D-254, 2026-11-10).

The wrapper's issuer_name_strip_re removes a trailing 'Emerald JV LP' / 'Verdelite JV LP' holder label
from a borrower's member name. Applied to the fund's own interests ('BCRED Emerald JV LP - LP Interest'
is split to issuer 'BCRED Emerald JV LP') it left the issuer as 'BCRED' on 16 published rows,
2024-09-30 to 2026-06-30. The page prints 'BCRED Emerald JV LP - LP Interest (6)(16) 1/19/2022 ...'.
"""
import re

import pytest

from pipeline.staging_bdc import issuer_name_strip_patterns

CIK = "0001803498"


@pytest.fixture(scope="module")
def pattern():
    return issuer_name_strip_patterns()[CIK]


@pytest.mark.parametrize("name", ["BCRED Emerald JV LP", "BCRED Verdelite JV LP"])
def test_fund_jv_interest_keeps_its_name(pattern, name):
    assert re.sub(pattern, "", name) == name


@pytest.mark.parametrize("name, expected", [
    # holder labels on borrowers in the JV schedules are still cut (false-positive guard)
    ("MH Sub I, LLC, Verdelite JV LP", "MH Sub I, LLC"),
    ("Polyphase Elevator Holding Co. Emerald JV LP", "Polyphase Elevator Holding Co."),
    ("Allied Universal Holdco LLC, Emerald JV LP 2", "Allied Universal Holdco LLC"),
    ("Emerald JV LP, 2U, Inc.", "2U, Inc."),
    # row numbers still cut, CLO series numbers kept
    ("Riser Merger Sub, Inc. 1", "Riser Merger Sub, Inc."),
    ("Pikes Peak CLO 10", "Pikes Peak CLO 10"),
])
def test_other_names_unchanged_behaviour(pattern, name, expected):
    assert re.sub(pattern, "", name).strip() == expected
