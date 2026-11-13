"""Margin reading of the agentA retirement check (scripts/v05_evidence/agenta_retirement_check.py):
the floor is never the margin, and the published spread is the cash + PIK total (D-031)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "v05_evidence"))

import agenta_retirement_check as chk  # noqa: E402


@pytest.mark.parametrize("line, code, total, floors", [
    ("Acme | First Lien Term Loan | S + 5.25 % | 9.07 % | 12/17/2027", "SOFR", 5.25, []),
    ("MGP | First Lien Secured Debt - Term Loan | S + 525 , 1.00 % Floor | 3/1/2030", "SOFR", 5.25, [1.0]),
    ("VetStrategy | C + 700 ( 100 Floor) | 10.59 % | 08/2027", "CDOR", 7.0, [1.0]),
    ("Skydio | First Lien DDTL A | SOFR(M) 2.50 % 5.00 % Cash 8.73 % 12/4/2029", "SOFR", 5.0, [2.5]),
    ("GTY | First Lien DDTL | SOFR(Q) 1.00 % 2.50 % Cash + 4.13 % PIK 10.30 % 7/9/2029", "SOFR", 6.63, [1.0]),
    ("Streamland | Last Out Term Loan | SOFR(Q) - 6.76 % PIK 10.43 % 3/31/2029", "SOFR", 6.76, []),
    ("Material | Term Loan | S+1600 (Includes 8.03% PIK) | 8/19/2027", "SOFR", 16.0, []),
    ("Hurricane | Term Loan | SONIA+625 Cash plus 6.25% PIK, 1.00% Floor | 11/21/2029", "SONIA", 12.5, [1.0]),
    ("Magaya | Term Loan 9.42 % ( S + 0.00 %; 0.75 % Floor; 5.75 % PIK) 7/26/2030", "SOFR", 5.75, [0.75]),
    ("Dan Newlin | Revolving Line of Credit SOFR 6.50 % 3/10/2026 1/28/2031", "SOFR", 6.5, []),
    # R2-1: basis points with a thousands separator
    ("QuantiTech | Term Loan | 3M | S+1,000 | 15.31 | % | 2/4/2026", "SOFR", 10.0, []),
    ("PRA Events | First Lien | 3M L+1,050 | 17.00 % | 8/7/2025 | 1,234 | 1,200", "LIBOR", 10.5, []),
    # R2-4: a seven-letter code
    ("Mertus | Term Loan | EURIBOR + 6.25% | 10.02 % | 6/30/2029", "EURIBOR", 6.25, []),
])
def test_parse_rate(line, code, total, floors):
    r = chk.parse_rate(line)
    assert r["code"] == code and r["total"] == pytest.approx(total) and r["floors"] == pytest.approx(floors)


@pytest.mark.parametrize("line", [
    "Walnut Parent | Term Loan | SOFR | + | 2.88% (3.38% PIK) | (Q) | 10.07% | 6/2/2022 | 11/9/2029",
    "Great Lakes Dental | Unitranche First Lien Revolver | S + 725 (300 PIK), 100 Floor | 11.10% | 06/2027",
    # R2-3: the space-separated form of the same shape
    "Titan Cloud | Term Loan | SOFR | 2.00% (4.60% PIK) | 11.94 % | 9/7/2029",
    "Mertus | Term Loan | EURIBOR | 6.25% (0.75% PIK) | 10.02 % | 6/30/2029",
    # R2-4: a minus after the code
    "X | Term Loan | SOFR - 0.10% | 4.50 % | 6/30/2029",
    # R2-5: two margin alternatives on one line
    "PT Intermediate | First Lien | (S +CSA + 4.75%/ S + 5.00% incl. 1.75% PIK) | 9.31 % | 11/1/2028",
    "Y | First Lien | (S + 5.75% cash)/S + 6% incl. 120bp PIK | 10.1 % | 11/1/2028",
])
def test_parenthetical_pik_without_includes_is_ambiguous(line):
    # one filer means cash 2.88 plus PIK 3.38 (published 6.26), another means 7.25 of which 3.00 PIK
    assert chk.parse_rate(line)["total"] is None


def test_two_unlabelled_numbers_are_ambiguous():
    r = chk.parse_rate("X | First Lien | SOFR(M) 1.00 % 4.73 % 10.72 % 12/30/2027")
    assert r["total"] is None
    ok, _ = chk.field_ok("basis_spread", 4.73, "X | SOFR(M) 1.00 % 4.73 % 10.72 % 12/30/2027")
    assert not ok


def test_cash_only_published_where_total_is_cash_plus_pik_fails():
    line = "GTY | SOFR(Q) 1.00 % 2.50 % Cash + 4.13 % PIK 10.30 % 7/9/2029"
    assert not chk.field_ok("basis_spread", 2.50, line)[0]
    assert not chk.field_ok("basis_spread", 1.00, line)[0]  # the floor
    assert chk.field_ok("basis_spread", 6.63, line)[0]


def test_maturity_needs_the_readers_maturity_cell():
    line = "X | 3/15/24 | Term Loan | SOFR + 6.25 % | 2/24/28"
    assert not chk.field_ok("maturity_date", "2028-02-24", line, mat_cell=None)[0]   # blank / unconfirmed cell
    assert chk.field_ok("maturity_date", "2028-02-24", line, mat_cell="2028-02-24")[0]
    assert not chk.field_ok("maturity_date", "2024-03-15", line, mat_cell="2028-02-24")[0]  # acquisition date


# Legend-dependent codes (2026-11-14). MSD 0001849894 MYOB 2026-06-30 prints 'B + 5.50 %' (wrapper B=BBSW);
# BCRED 0001803498 FFML Holdco 2024-09-30 prints 'B+ 6.25 %' with the legend 'BKBM or B' (NZD).
MYOB = ("MYOB Invest Co Pty Ltd and MYOB US Borrower LLC AUS(9)(10) B + 5.50 % 0.75 % 9.99 % "
        "(Incl 3.00 % PIK) 6/6/2030 AUD 77,196 49,580 51,391 1.47")
FFML = "FFML Holdco Ltd | First Lien Senior Secured Loan | B+ 6.25 % | 10.97 % | 11/30/2028 | NZD 1,000"


def test_b_margin_is_read_and_its_benchmark_is_unresolved():
    r = chk.parse_rate(MYOB)
    assert r["total"] == pytest.approx(5.50) and r["code_resolved"] is False and r["code"] == "LEGEND:B"
    assert chk.field_ok("basis_spread", 5.50, MYOB)[0]
    assert not chk.field_ok("basis_spread", 5.00, MYOB)[0]          # the stale label's margin still fails
    for bench in ("BBSY", "BBSW", "BKBM", "LEGEND:B", None):     # no legend: the reference fails closed
        assert not chk.field_ok("reference_rate_type", bench, MYOB)[0]


def test_b_is_resolved_only_from_the_filers_legend():
    from pipeline.printed_margin import parse_rate, reference_codes
    bcred = reference_codes("0001803498", "2024-09-30")
    r = parse_rate(FFML, bcred)
    assert r["total"] == pytest.approx(6.25) and r["code"] == "BKBM" and r["code_resolved"]
    assert parse_rate(FFML)["code"] != "BBSY" and not parse_rate(FFML)["code_resolved"]
    assert not chk.field_ok("reference_rate_type", "BBSY", FFML, codes=bcred)[0]
    assert not chk.field_ok("reference_rate_type", "BBSY", FFML)[0]
    assert chk.field_ok("reference_rate_type", "BKBM", FFML, codes=bcred)[0]
    assert parse_rate(MYOB, reference_codes("0001849894", "2026-06-30"))["code"] == "BBSW"
    # a dated legend: HPS B=BBSW to 2024-09-30, BBSY from 2024-12-31; no report date, no dated code
    assert parse_rate(MYOB, reference_codes("0001838126", "2024-09-30"))["code"] == "BBSW"
    assert parse_rate(MYOB, reference_codes("0001838126", "2024-12-31"))["code"] == "BBSY"
    assert not parse_rate(MYOB, reference_codes("0001838126", None))["code_resolved"]


def test_s_c_sa_are_legend_dependent_too():
    from pipeline.printed_margin import parse_rate, reference_codes
    line = "Acme | First Lien Term Loan | S + 5.25 % | 9.07 % | 12/17/2027"
    assert not parse_rate(line)["code_resolved"]
    assert not chk.field_ok("reference_rate_type", "SOFR", line)[0]            # no legend: fail closed
    assert parse_rate(line, reference_codes("0001803498", "2025-12-31"))["code"] == "SONIA"   # BCRED S=SONIA
    assert parse_rate(line, reference_codes("0001849894", "2025-12-31"))["code"] == "SOFR"
    assert chk.field_ok("reference_rate_type", "SOFR", line, codes={"S": "SOFR"})[0]
    assert not chk.field_ok("reference_rate_type", "SOFR", line, codes={"S": "SONIA"})[0]
    assert not parse_rate("X | C + 700 | 08/2027")["code_resolved"]
    assert not parse_rate("X | SA + 5.00 % | 08/2027")["code_resolved"]
    assert parse_rate("X | SA + 5.00 % | 08/2027", {"SA": "SONIA"})["code"] == "SONIA"
    # codes every wrapper reads the same way still resolve without a legend
    for text, bench in (("X | E + 6.00 % | 1/1/2030", "EURIBOR"), ("X | SOFR + 6.00 % | 1/1/2030", "SOFR"),
                        ("X | L + 600 | 1/1/2030", "LIBOR"), ("X | P + 1.00 % | 1/1/2030", "PRIME")):
        assert parse_rate(text)["code"] == bench and parse_rate(text)["code_resolved"]


def test_a_rating_b_plus_is_not_a_margin_alternative():
    from pipeline.printed_margin import parse_rate
    # 'B+' with no number after it is not a second benchmark expression
    assert parse_rate("Acme (rated B+) | First Lien | S + 5.25 % | 9.07 % | 12/17/2027")["total"] == pytest.approx(5.25)
    # a second 'B + n' expression on the line is
    assert parse_rate("X | First Lien | S + 5.25 % / B + 5.50 % | 12/17/2027")["total"] is None
    # 'B' needs a '+': 'Tranche B 5.00 %' is no benchmark
    assert parse_rate("X | Term Loan Tranche B 5.00 % | 12/17/2027") is None
