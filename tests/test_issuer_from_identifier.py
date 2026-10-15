"""dispatch.issuer_from_identifier and dispatch.not_cash_markers: Stepstone's moving issuer segment and its
'Cash IR / PIK Rate' column label (2026-10-15, fund loop spx)."""
import json

import pandas as pd
import pytest

from pipeline.bdc_xbrl_wrapper import is_non_private_market_identifier
from pipeline.staging_bdc import issuer_from_identifier_settings
from pipeline.unified_holdings import _issuer_from_identifier

STEPSTONE = "0001950803"
SETTING = {
    "when_issuer_re": r"^\s*(?i:Reference\s+Rate|RRS?\b|RR\s*&|\d?M?\s*SOFR)|^\s*(?:MassMutual|BMO)\s+SPV\b",
    "patterns": [
        r"\|\s*([^|]+?)\s*\|\s*(?:MassMutual|BMO)\s+SPV",
        r"\|\s*(?:Insurance\s+Brokers)\s*([A-Z0-9][^|]*?)\s*\|\s*(?:Reference\s+Rate|RR\s*&?\s*S/F)",
        r"(?:^|\|)\s*([^|]*?[A-Za-z][^|]*?)\s*\|\s*(?:Reference\s+Rate|RR\s*&?\s*S/F)",
    ],
}


def _frame(rows, cik=STEPSTONE, source="bdc"):
    return pd.DataFrame({"source": source, "cik": cik,
                         "issuer_name": [r[0] for r in rows], "bdc_investment_identifier": [r[1] for r in rows]})


def test_label_named_rows_take_the_issuer_from_the_member():
    out = _issuer_from_identifier(_frame([
        ("RR & S/F", "NCNA Debt Inv. | FLSS | Insurance Brokers Alkeme Intermediary Holdings, LLC Revolving Credit | RR & S/F | 3M SOFR + 0.50% / 1.00%"),
        ("Reference Rate Spread / Floor", "Non-Controlled, Non-Affiliated Debt Investments | Environmental & Facilities Services | VTC Buyer Corp. Term A Loan | Reference Rate Spread / Floor | 3M SOFR"),
        ("MassMutual SPV I Facility", "Non Controlled Non Affiliated Debt Investments | First Lien Senior Secured | Accordion Partners LLC Initial Term Loan| MassMutual SPV I Facility | Industrials"),
    ]), {STEPSTONE: SETTING})
    assert out["issuer_name"].tolist() == ["Alkeme Intermediary Holdings, LLC Revolving Credit", "VTC Buyer Corp. Term A Loan",
                                           "Accordion Partners LLC Initial Term Loan"]


def test_real_issuer_names_and_other_funds_are_untouched():
    # false positive guard: a real name is not re-read even where a pattern would match its member
    member = "Non-Controlled, Non-Affiliated Debt Investments | Advertising | Amplify Buyer, Inc. Term Loan | Reference Rate Spread / Floor | 3M SOFR"
    frame = pd.concat([_frame([("Amplify Buyer, Inc. Term Loan", member)]),
                       _frame([("Reference Rate Spread / Floor", member)], cik="0001111111"),
                       _frame([("Reference Rate Spread / Floor", member)], source="nport")], ignore_index=True)
    out = _issuer_from_identifier(frame, {STEPSTONE: SETTING})
    assert out["issuer_name"].tolist() == ["Amplify Buyer, Inc. Term Loan", "Reference Rate Spread / Floor", "Reference Rate Spread / Floor"]


def test_a_catch_that_is_itself_a_label_or_no_match_keeps_the_name():
    out = _issuer_from_identifier(_frame([
        ("RR & S/F", "NCNA Debt Inv. | FLSS | 3M SOFR + 5.00% | RR & S/F | 9.10%"),
        ("3M SOFR + 5.00%", "no pipes at all"),
    ]), {STEPSTONE: SETTING})
    assert out["issuer_name"].tolist() == ["RR & S/F", "3M SOFR + 5.00%"]


def test_setting_needs_both_keys_and_a_capture_group(tmp_path):
    def wrapper(name, setting):
        (tmp_path / name).write_text(json.dumps({"cik": STEPSTONE, "dispatch": {"issuer_from_identifier": setting}}), encoding="utf-8")
    wrapper("a.json", SETTING)
    assert issuer_from_identifier_settings(tmp_path) == {STEPSTONE: SETTING}
    wrapper("a.json", {"when_issuer_re": "x", "patterns": ["no group"]})
    with pytest.raises(ValueError):
        issuer_from_identifier_settings(tmp_path)
    wrapper("a.json", {"patterns": ["(x)"]})
    with pytest.raises(ValueError):
        issuer_from_identifier_settings(tmp_path)


def test_not_cash_marker_keeps_a_loan_row_with_the_filers_cash_column_label():
    loan = ("NCNA Debt Inv. | FLSS | Health Care Equipment | CSHC Buyerco, LLC Closing Date Term Loan | RR & S/F | "
            "3M SOFR + 5.00% / 0.75% | Cash IR / PIK Rate | 8.73% | MD | 4/29/2033")
    # without the filer's setting the bare word 'cash' reads the loan as cash (the 2026-06-30 defect)
    assert is_non_private_market_identifier(loan)
    assert not is_non_private_market_identifier(loan, None, ("cash ir /",))


def test_not_cash_marker_never_clears_a_money_market_or_a_cash_row():
    # false positive guard: the setting clears only the bare-word check
    assert is_non_private_market_identifier("Money Market Fund | Cash IR / PIK Rate", None, ("cash ir /",))
    assert is_non_private_market_identifier("Cash and Cash Equivalents | Other cash accounts", None, ("cash ir /",))


def test_lien_abbreviation_fills_a_blank_lien_on_loans_only():
    from pipeline.unified_holdings import _lien_from_identifier
    frame = pd.DataFrame({
        "source": "bdc", "cik": [STEPSTONE, STEPSTONE, STEPSTONE, STEPSTONE, "0001111111"],
        "asset_category": ["LOAN", "LOAN", "FUND", "LOAN", "LOAN"],
        "lien_position": [None, "Second Lien", None, None, None],
        "bdc_investment_identifier": ["NCNA Debt Inv. | FLSS | Advertising | Acme LLC Term Loan",
                                      "NCNA Debt Inv. | FLSS | Advertising | Beta LLC Term Loan",
                                      "NCNA Private Credit Funds | FLSS | Gamma Fund LP",
                                      "NCNA Debt Inv. | Subordinated Notes | FLSSX Holdings CLO",
                                      "NCNA Debt Inv. | FLSS | Delta LLC Term Loan"]})
    out = _lien_from_identifier(frame, {STEPSTONE: {"First Lien": r"(?:^|\|)\s*FLSS\s*(?:\||$)"}})
    # filled on the blank loan; a set lien, a fund row, a word that only starts with FLSS and another fund are untouched
    assert out["lien_position"].tolist() == ["First Lien", "Second Lien", None, None, None]


def test_lien_setting_rejects_an_unknown_lien(tmp_path):
    from pipeline.staging_bdc import lien_from_identifier_patterns
    (tmp_path / "a.json").write_text(json.dumps({"cik": STEPSTONE, "dispatch": {"lien_from_identifier": {"Senior": "x"}}}), encoding="utf-8")
    with pytest.raises(ValueError):
        lien_from_identifier_patterns(tmp_path)
