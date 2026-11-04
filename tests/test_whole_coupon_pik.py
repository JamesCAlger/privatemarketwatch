"""Whole-coupon PIK extraction rule (pipeline/whole_coupon_pik.py, D-232; owner 2026-11-04)."""
import math

import pandas as pd
import pytest

from pipeline import whole_coupon_pik as wc


def _parse(text):
    got = wc.parse(pd.Series([text]))
    m, c = got.iloc[0]["margin"], got.iloc[0]["coupon"]
    return None if math.isnan(m) else (round(m, 4), round(c, 4))


@pytest.mark.parametrize("text, expected", [
    # Crescent Mario Purchaser last-out 2023-03-31 (basis points)
    ("Mario Purchaser, LLC (10) | Unitranche First Lien - Last Out Term Loan | S + 1075 PIK | 15.66% | 04/2032 | 3,207", (10.75, 15.66)),
    # Crescent Integro: floor after PIK
    ("Integro Parent, Inc. (11) | Senior Secured First Lien Term Loan | S + 1225 PIK (100 Floor) | 16.83% | 706", (12.25, 16.83)),
    # Crescent AX VI: euro benchmark
    ("AX VI INV2 Holding AB (Voff) (6)(11) | Senior Secured Second Lien Term Loan | E + 1000 PIK | 13.23% | 08/2030", (10.0, 13.23)),
    # T Series Applitools, cells joined and printed as one line
    ("Applitools, Inc. | (4) (6) (10) (11) | S + | 6.25% PIK | 11.35% | 5/25/2029 | 7,229", (6.25, 11.35)),
    ("Applitools, Inc. (4) (6) (8) S + 6.25 % PIK 11.35 % PIK 05/25/2029 7,023", (6.25, 11.35)),
    # Silver Capital Wine.com
    ("Wine.com, LLC | Beverages | 16.58 % | S + 12.00 % PIK | 04/03/27 | 2,141", (12.0, 16.58)),
    # Commonwealth Kent
    ("Kent Water Sports Holdings, LLC - Delayed Draw Loan Last-Out | Consumer Durables & Apparel | SOFR + 9.00 % PIK | 14.44 % | 12/31/2025", (9.0, 14.44)),
    # Commonwealth Kent 2024-09-30: a floor between the margin and the PIK word
    ("Kent Water Sports Holdings, LLC - Delayed Draw Term Loan First-Out (4)(11) | Consumer Durables & Apparel | "
     "SOFR + 10.00% (1.00% floor) PIK | 15.51% | 10/18/2027 | 5,862", (10.0, 15.51)),
    # 0001899017 Masco / Cube: benchmark in its own cell
    ("Masco (6)(15)(17)(21) | Subordinated Debt | EURIBOR | 10.00% PIK | 13.25 | % | 10/4/2032 | 5,000", (10.0, 13.25)),
    ("First Lien Senior Secured Loan - Delayed Draw | SONIA | — | 10.00% PIK | 13.73% | 5/22/2032", (10.0, 13.73)),
])
def test_parse_whole_coupon_forms(text, expected):
    assert _parse(text) == expected


@pytest.mark.parametrize("text", [
    # Commonwealth VardimanBlack: floating PIK leg plus a fixed cash leg (D-218)
    "VardimanBlack Holdings, LLC - Term Loan | Health Care Equipment & Services | SOFR + 2.00% PIK + 5.00% | 12.30% | 3/18/2027",
    # T Series Continental Battery 2025-09-30: no benchmark on the row
    "Continental Battery Company | (5) (11) (12) (13) | First Lien Debt | 7.00% PIK | 11.29% | 07/20/2028",
    # partial PIK inside a bracket
    "Lighthouse | Term Loan | S + 650 (100 Floor) (Including 75 PIK) | 11.36% | 1,000",
    "Acme | First Lien | S + 6.00 % (incl. 2.00 % PIK) 10.30 % | 1,000",
    # cash and PIK margins in separate cells after a benchmark cell
    "Acme | SOFR | 5.00% | 2.00% PIK | 9.50% | 1,000",
    # cash margin plus PIK margin
    "Acme | Term Loan | S + 4.00% + 2.50% PIK | 11.00% | 1,000",
    "Acme | Term Loan | S + 3.25% Cash + 3.00% PIK | 11.00% | 1,000",
    # toggle
    "Acme | Term Loan | S + 6.00% PIK Toggle | 10.30% | 1,000",
    # a bracket between margin and PIK that is not a floor
    "Acme | Term Loan | S + 6.00% (2.00% cash) PIK | 10.30% | 1,000",
    "Acme | Term Loan | S + 6.00% (Q) PIK | 10.30% | 1,000",
    # a bare margin under 25 is not read as basis points
    "Acme | Term Loan | S + 7 PIK | 11.30% | 1,000",
    # no coupon printed after the margin
    "Foundation Automotive US Corp (4)(7)(18) | SF + | 7.75% PIK | 12/24/2027 | 18,779",
    # a coupon below the margin, or a benchmark implausibly large
    "Acme | Term Loan | S + 1075 PIK | 9.00% | 1,000",
    "Acme | Term Loan | S + 650 PIK | 19.00% | 1,000",
    # two whole-coupon forms on one row
    "Acme | S + 650 PIK | 11.00% | S + 700 PIK | 11.50%",
])
def test_parse_rejects(text):
    assert _parse(text) is None


def _frame(**kw):
    base = {"asset_category": "LOAN", "interest_rate": 15.66, "pik_rate": 10.75, "basis_spread": 10.75}
    base.update(kw)
    return pd.DataFrame([base])


def _eligible(frame, text="Mario | S + 1075 PIK | 15.66% | 04/2032"):
    return bool(wc.eligible(frame, wc.parse(pd.Series([text], index=frame.index))).iloc[0])


def test_eligible_when_tags_agree_with_page():
    assert _eligible(_frame())
    assert _eligible(_frame(pik_rate=None))                     # PIK not tagged
    assert _eligible(_frame(basis_spread=None))                 # spread not tagged
    assert _eligible(_frame(pik_rate=15.66))                    # already the coupon


def test_not_eligible_when_tags_disagree():
    assert not _eligible(_frame(interest_rate=14.0))            # rate tag is not the printed coupon
    assert not _eligible(_frame(interest_rate=None))            # no rate tag: nothing to read
    assert not _eligible(_frame(pik_rate=3.0))                  # PIK tag is another figure
    assert not _eligible(_frame(basis_spread=6.0))              # spread tag is a cash margin
    assert not _eligible(_frame(asset_category="EQUITY"))       # loans only


CRESCENT = "0001633336"
MARIO = "Mario Purchaser, LLC (10) | Unitranche First Lien - Last Out Term Loan | S + 1075 PIK | 15.66% | 04/2032 | 3,207"
COSMETIC = "Cosmetic Solutions LLC | First lien senior secured term loan | S + | 6.50% PIK | 12.11% | 10/17/2025 | 2,810"


def _staged(**kw):
    row = {"cik": CRESCENT, "accession_number": "0000950170-23-020540", "report_date": "2023-03-31",
           "bdc_investment_identifier": "Mario Purchaser LLC Last Out", "asset_category": "LOAN",
           "interest_rate": 15.66, "pik_rate": 10.75, "basis_spread": 10.75, "src_transforms": "interest_rate:rate_x100"}
    row.update(kw)
    return row


def _status(tmp_path, rows):
    path = tmp_path / "bdc_ixbrl_field_status.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_apply_sets_the_printed_coupon_for_an_opted_in_fund(tmp_path):
    status = _status(tmp_path, [
        {"cik": CRESCENT, "accession_number": "0000950170-23-020540", "report_date": "2023-03-31",
         "period_role": "current", "raw_id_lower": "mario purchaser llc last out", "printed_row": MARIO},
        # a comparative-period row with another print is not read
        {"cik": CRESCENT, "accession_number": "0000950170-23-020540", "report_date": "2023-03-31",
         "period_role": "comparative", "raw_id_lower": "mario purchaser llc last out", "printed_row": "x | S + 900 PIK | 14.00%"},
    ])
    staged = pd.DataFrame([_staged(), _staged(bdc_investment_identifier="Other loan")])
    out = wc.apply(staged, status, funds={CRESCENT})
    assert out.loc[0, "pik_rate"] == pytest.approx(15.66)
    assert out.loc[0, "src_transforms"] == "interest_rate:rate_x100;" + wc.TRANSFORM
    assert out.loc[1, "pik_rate"] == pytest.approx(10.75) and wc.TRANSFORM not in out.loc[1, "src_transforms"]
    # idempotent
    again = wc.apply(out, status, funds={CRESCENT})
    assert again.loc[0, "src_transforms"].count(wc.TRANSFORM) == 1


def test_apply_is_off_for_a_fund_without_the_setting(tmp_path):
    # 0001913724 prints the same form and its par grows by margin/4 (cash benchmark, PIK margin): not a whole coupon
    other = "0001913724"
    status = _status(tmp_path, [{"cik": other, "accession_number": "a1", "report_date": "2023-12-31",
                                 "period_role": "current", "raw_id_lower": "cosmetic", "printed_row": COSMETIC}])
    staged = pd.DataFrame([_staged(cik=other, accession_number="a1", report_date="2023-12-31",
                                   bdc_investment_identifier="Cosmetic", interest_rate=12.11, pik_rate=6.5, basis_spread=6.5)])
    out = wc.apply(staged, status, funds={CRESCENT})
    assert out.loc[0, "pik_rate"] == pytest.approx(6.5) and wc.TRANSFORM not in out.loc[0, "src_transforms"]


def test_apply_leaves_a_listed_margin_row_of_an_opted_in_fund(tmp_path):
    # HPS Chord Searchlight 2025-12-31: printed 'SF + | 6.75% PIK | 10.59%', par grows 1.60 % a quarter (margin/4 1.69)
    hps = "0001838126"
    chord = "Chord Searchlight, L.P (4)(5)(6)(10)(25) | SF + | 6.75% PIK | 10.59 | % | 7/16/2030 | 111,493"
    status = _status(tmp_path, [
        {"cik": hps, "accession_number": "0001628280-26-020206", "report_date": "2025-12-31", "period_role": "current",
         "raw_id_lower": "chord", "printed_row": chord},
        {"cik": hps, "accession_number": "0001628280-26-020206", "report_date": "2025-12-31", "period_role": "current",
         "raw_id_lower": "pcp", "printed_row": chord.replace("Chord Searchlight, L.P", "PCP CW")},
    ])
    base = dict(cik=hps, accession_number="0001628280-26-020206", report_date="2025-12-31",
                interest_rate=10.59, pik_rate=6.75, basis_spread=None)
    staged = pd.DataFrame([_staged(**base, bdc_investment_identifier="chord", src_context_id="c-841"),
                           _staged(**base, bdc_investment_identifier="pcp", src_context_id="c-900")])
    out = wc.apply(staged, status, funds={hps}, exclusions={(hps, "0001628280-26-020206", "c-841")})
    assert out.loc[0, "pik_rate"] == pytest.approx(6.75) and wc.TRANSFORM not in out.loc[0, "src_transforms"]
    assert out.loc[1, "pik_rate"] == pytest.approx(10.59) and wc.TRANSFORM in out.loc[1, "src_transforms"]


def test_apply_leaves_a_member_printed_twice_and_a_disagreeing_tag(tmp_path):
    status = _status(tmp_path, [
        {"cik": CRESCENT, "accession_number": "a1", "report_date": "2023-03-31", "period_role": "current",
         "raw_id_lower": "twice", "printed_row": MARIO},
        {"cik": CRESCENT, "accession_number": "a1", "report_date": "2023-03-31", "period_role": "current",
         "raw_id_lower": "twice", "printed_row": MARIO.replace("1075", "1100")},
        {"cik": CRESCENT, "accession_number": "a1", "report_date": "2023-03-31", "period_role": "current",
         "raw_id_lower": "tagdiffers", "printed_row": MARIO},
    ])
    staged = pd.DataFrame([_staged(accession_number="a1", bdc_investment_identifier="twice"),
                           _staged(accession_number="a1", bdc_investment_identifier="tagdiffers", interest_rate=14.0)])
    out = wc.apply(staged, status, funds={CRESCENT})
    assert list(out["pik_rate"]) == [10.75, 10.75]
