"""Regression tests for the HPS Corporate Lending Fund (CIK 1838126) 2025-12-31
bare-axis exclusion rule (1838126_2025q4_bare_axis_leak_exclusion, revised).

Covers verdict BDCSRC_0001838126_2025-12-31_BLOCKING_SOURCE_POSITION_LIKE_
PARSER_MISMATCH_1a08ff0732: the bare InvestmentIdentifierAxis rows in the
2025-12-31 10-K split into (a) ULTRA III, LLC joint-venture note-schedule facts
(excluded: the fund's exposure is its retained LLC-interest line) and (b) three
genuine main-SOI positions the filer tagged without the affiliation suffix
(admitted: SLF V AD1 Holdings, CCI Topco Preferred, AMR GP Ordinary Shares).

Uses the real promoted rule JSON and real filing fair values; synthetic frame,
no production files touched, no network.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.agent_rule import apply_rules, validate_rule

RULE_PATH = (Path(__file__).resolve().parent.parent / "data" / "overrides"
             / "agent_investigate_rules" / "1838126"
             / "1838126_2025q4_bare_axis_leak_exclusion.json")

Q4 = "2025-12-31"
ANCHOR = 25_337_420_000.0  # fund_financials investments_at_fair_value, 2025-12-31

# The three bare-axis rows printed in the fund's own consolidated SOI (kept).
MAIN_SOI_BARE = [
    ("SLF V AD1 Holdings, LLC", 9_298_000.0),
    ("CCI Topco, Inc. - Preferred Stock", 2_184_000.0),
    ("AMR GP Holdings Ltd - Ordinary Shares", 1_568_000.0),
]

# The 22 bare-axis rows printed only in the ULTRA III JV note schedule and its
# unfunded-commitment table (excluded). Values are the filing's dollar facts.
ULTRA_III_BARE = [
    ("Brandt Information Services, LLC", -21_000.0),
    ("Brandt Information Services, LLC 1", 114_047_000.0),
    ("Brandt Information Services, LLC 2", 39_968_000.0),
    ("Brandt Information Services, LLC 3", 23_961_000.0),
    ("Bright Light Buyer, Inc. 1", 235_993_000.0),
    ("Compsych Investments Corp 2", 433_000.0),
    ("Compsych Investments Corp.", 433_000.0),
    ("Compsych Investments Corp. 1", 151_360_000.0),
    ("EHOB, LLC", 103_976_000.0),
    ("Emerus Holdings, Inc. 1", 156_034_000.0),
    ("Emerus Holdings, Inc. 2", 91_482_000.0),
    ("FH BMX Buyer, Inc. 1", 129_338_000.0),
    ("FH BMX Buyer, Inc. 2", 34_519_000.0),
    ("FH BMX Buyer, Inc. 3", 37_042_000.0),
    ("FH BMX Buyer, Inc. 4", 221_000.0),
    ("FH BMX Buyer, Inc. 5", 66_000.0),
    ("FH BMX Buyer, Inc. 6", 221_000.0),
    ("Rsource Holdings, LLC 1", 168_890_000.0),
    ("Rsource Holdings, LLC 2", -1_258_000.0),
    ("Sentinel Buyer Corp.", -188_000.0),
    ("Sentinel Buyer Corp. 1", 228_542_000.0),
    ("Sentinel Buyer Corp. 2", -188_000.0),
]

# Sum of all affiliation-suffixed (main-schedule) rows in bdc_holdings at the
# time of authoring; represented in the fixture by one aggregate-value leaf per
# style so the anchor identity can be asserted without 823 literal rows.
SUFFIXED_TOTAL = 25_324_370_000.0
SUFFIXED_ROWS = [
    # (identifier, fair value) -- representative real rows + one balancing row
    ("Sentinel Buyer Corp. 2 | Non-Affiliated Issuer", 254_664_000.0),
    ("Sentinel Buyer Corp. 1 | Non-Affiliated Issuer", -210_000.0),
    ("Bright Light Buyer, Inc. | Non-Affiliated Issuer", 72_096_000.0),
    ("123Dentist Inc 1 | Non-Affiliated Issuer", 17_264_000.0),
    ("Club Car Wash Preferred, LLC - Preferred Stock 1 | | Non-Affiliated Issuer",
     16_598_000.0),
    ("REST OF MAIN SCHEDULE | Non-Affiliated Issuer",
     SUFFIXED_TOTAL - 254_664_000.0 + 210_000.0 - 72_096_000.0
     - 17_264_000.0 - 16_598_000.0),
]


def _load_rule():
    return json.loads(RULE_PATH.read_text(encoding="utf-8-sig"))


def _row(identifier, fv, report_date=Q4):
    return {
        "cik": "1838126",
        "report_date": report_date,
        "issuer_name": identifier.split(" | ")[0],
        "bdc_investment_identifier": identifier.split(" | ")[0],
        "bdc_dimensions_raw": f"investmentidentifieraxis={identifier}",
        "fair_value": fv,
    }


def _frame(extra_rows=()):
    rows = [_row(i, fv) for i, fv in MAIN_SOI_BARE]
    rows += [_row(i, fv) for i, fv in ULTRA_III_BARE]
    rows += [_row(i, fv) for i, fv in SUFFIXED_ROWS]
    rows += list(extra_rows)
    return pd.DataFrame(rows)


def test_rule_file_is_valid():
    assert validate_rule(_load_rule()) == []


def test_main_soi_bare_leaf_rows_admitted():
    """The blocker row SLF V AD1 Holdings, LLC (and the two bare equity
    positions) are printed in the fund's own SOI and must survive the rule."""
    corrected, audits = apply_rules(_frame(), [_load_rule()])
    kept = set(corrected["bdc_investment_identifier"])
    assert audits[0]["status"] == "ok"
    for identifier, _fv in MAIN_SOI_BARE:
        assert identifier in kept, f"main-SOI bare position dropped: {identifier}"


def test_ultra_iii_jv_note_rows_still_rejected():
    """All 22 ULTRA III note-schedule facts (JV portfolio + its unfunded
    commitment rows) are excluded -- they are the investee's holdings."""
    corrected, audits = apply_rules(_frame(), [_load_rule()])
    kept_dims = set(corrected["bdc_dimensions_raw"])
    for identifier, _fv in ULTRA_III_BARE:
        assert f"investmentidentifieraxis={identifier}" not in kept_dims, (
            f"ULTRA III JV row leaked back into holdings: {identifier}")
    assert audits[0]["rows_excluded"] == len(ULTRA_III_BARE) == 22
    assert audits[0]["per_quarter"][Q4]["rows"] == 22
    assert audits[0]["per_quarter"][Q4]["fv"] == pytest.approx(1_514_871_000.0)


def test_suffixed_main_schedule_rows_not_excluded():
    """False-positive guard: affiliation-suffixed position leaves (including
    same-issuer names that also appear in the JV schedule, and double-pipe
    variants) are never touched by the bare-axis predicate."""
    corrected, _ = apply_rules(_frame(), [_load_rule()])
    kept_dims = set(corrected["bdc_dimensions_raw"])
    for identifier, _fv in SUFFIXED_ROWS:
        assert f"investmentidentifieraxis={identifier}" in kept_dims, (
            f"suffixed main-schedule row wrongly excluded: {identifier}")


def test_kept_total_reconciles_to_balance_sheet_anchor():
    """Kept fair value equals investments_at_fair_value to the dollar --
    the independent check the partition is grounded on."""
    corrected, _ = apply_rules(_frame(), [_load_rule()])
    assert corrected["fair_value"].sum() == pytest.approx(ANCHOR)


def test_other_period_rows_out_of_scope():
    """Comparative/other-quarter rows (e.g. the Q1-2026 ULTRA III schedule
    carries the same bare identifiers) are untouched by this 2025-12-31 rule."""
    q1_rows = [_row("EHOB, LLC", 90_446_000.0, report_date="2026-03-31"),
               _row("Brandt Information Services, LLC 1", 112_857_000.0,
                    report_date="2026-03-31")]
    corrected, audits = apply_rules(_frame(extra_rows=q1_rows), [_load_rule()])
    q1 = corrected[corrected["report_date"] == "2026-03-31"]
    assert len(q1) == 2, "out-of-scope quarter rows must not be excluded"
    assert "2026-03-31" not in audits[0]["per_quarter"]


def test_bare_subtotal_header_rows_still_rejected():
    """Negative case: a bare aggregate/subtotal fact from the same filing has
    no affiliation suffix and is not one of the three admitted positions, so
    it stays excluded (never admitted by the narrowed keep-list)."""
    extra = [_row("Total Investment Portfolio", 1_514_360_000.0),
             _row("Total First Lien Debt", 1_501_028_000.0)]
    corrected, audits = apply_rules(_frame(extra_rows=extra), [_load_rule()])
    kept = set(corrected["bdc_investment_identifier"])
    assert "Total Investment Portfolio" not in kept
    assert "Total First Lien Debt" not in kept
    assert audits[0]["rows_excluded"] == 24
