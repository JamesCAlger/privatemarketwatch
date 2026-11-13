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
])
def test_parse_rate(line, code, total, floors):
    r = chk.parse_rate(line)
    assert r["code"] == code and r["total"] == pytest.approx(total) and r["floors"] == pytest.approx(floors)


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
