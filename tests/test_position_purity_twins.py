"""PP02 (duplicate dimension candidate) must not fire on twin lines on distinct members.

Owner ruling 2026-11-04 (b02-twin-lines-by-financing-facility-printed-separately): SPX Private
Credit Fund prints 'Kite Midco II LTD Term Loan B1 ... 5,290 5,226 5,211' twice, once per
financing facility (footnote (11)); each line sits on its own investment member, so the two rows
are two positions. A fact repeated on a second dimension path of the SAME member stays flagged.
"""
import pandas as pd

from pipeline.position_purity import build_position_purity_diagnostics

KITE = "NCNA Debt Inv. | FLSS | Advertising | Kite Midco II LTD Term Loan B1 | 6M SOFR + 4.50% | MD | 11/19/2031"


def _row(identifier, dims):
    return {"source": "bdc", "cik": "0001950803", "entity_name": "SPX Private Credit Fund",
            "report_date": "2026-06-30", "period": "2026-06-30", "accession_number": "0001193125-26-351731",
            "issuer_name": "Kite Midco II LTD", "instrument_description": "Term Loan B1",
            "bdc_investment_identifier": identifier, "bdc_dimensions_raw": dims,
            "fair_value": "5211000.0", "cost": "5226000.0", "principal_amount": "5290000.0",
            "shares_held": "", "cusip": "", "isin": ""}


def _duplicate_rows(rows):
    diagnostics, _ = build_position_purity_diagnostics(pd.DataFrame(rows), None)
    if not len(diagnostics):
        return 0
    return int((diagnostics["issue_family"] == "duplicate_dimension_candidate").sum())


def test_twin_lines_on_distinct_members_are_not_duplicates():
    rows = [_row(KITE, "investmentidentifieraxis=" + KITE),
            _row(KITE + " One", "investmentidentifieraxis=" + KITE + " One")]
    assert _duplicate_rows(rows) == 0


def test_twin_suffix_after_a_separator_and_numbered_twins():
    pipe = KITE.replace(" | MD | 11/19/2031", " | 11/19/2031")
    assert _duplicate_rows([_row(pipe, "investmentidentifieraxis=" + pipe),
                            _row(pipe + " | One", "investmentidentifieraxis=" + pipe + " | One")]) == 0
    assert _duplicate_rows([_row("Behavox Ltd 1", "investmentidentifieraxis=Behavox Ltd 1"),
                            _row("Behavox Ltd 2", "investmentidentifieraxis=Behavox Ltd 2")]) == 0


def test_members_with_a_typo_or_other_terms_are_separate_positions():
    """SPX 2025-12-31 prints twin lines whose members differ by a typed spread; tranches on
    members with other terms and equal (often zero) figures are not dimension duplicates either."""
    a = "Acme First Lien Term Loan | 1M SOFR + 0.75% / 0.75% | 8.47% | 10/15/2032"
    b = "Acme First Lien Term Loan | 1M SOFR + 4.75% / 0.75% | 8.47% | 10/15/2032 One"
    assert _duplicate_rows([_row(a, "investmentidentifieraxis=" + a), _row(b, "investmentidentifieraxis=" + b)]) == 0


def test_same_member_on_two_dimension_paths_is_still_a_duplicate():
    rows = [_row(KITE, "investmentidentifieraxis=" + KITE),
            _row(KITE, "investmentidentifieraxis=" + KITE + "; legalentityaxis=SPV I")]
    assert _duplicate_rows(rows) == 2


def test_a_repeated_member_alongside_a_twin_still_flags_the_group():
    rows = [_row(KITE, "investmentidentifieraxis=" + KITE),
            _row(KITE, "investmentidentifieraxis=" + KITE + "; legalentityaxis=SPV I"),
            _row(KITE + " One", "investmentidentifieraxis=" + KITE + " One")]
    assert _duplicate_rows(rows) == 3


def test_a_row_without_a_member_is_still_a_duplicate_candidate():
    rows = [_row(KITE, "investmentidentifieraxis=" + KITE),
            _row("", "industryaxis=Advertising")]
    assert _duplicate_rows(rows) == 2
