"""Candidate ledger rules (pipeline/candidate_rules.py): built and measured, not switched on.

Positives are shaped on real rows from docs/investigations/v05_observations.csv; each rule also
has false-positive guards on legitimate rows.
"""
import duckdb
import pandas as pd
import pytest

from pipeline import candidate_rules as cr


def _run(rule, rows):
    con = duckdb.connect()
    frame = pd.DataFrame(rows)
    if "row_id" not in frame:
        frame["row_id"] = [f"r{i}" for i in range(len(frame))]
    for col, default in (("cik", "0000000001"), ("report_date", "2025-12-31"), ("accession_number", "a1")):
        if col not in frame:
            frame[col] = default
    cr.prepare(con, frame)
    return rule(con)


def _ids(df):
    return set(df["row_id"])


# ---------------------------------------------------------------- rule 1: issuer name vs page

def test_issuer_industry_and_group_prefix_flags():
    # MidCap 2023: 'Software Zendesk Zendesk, Inc.' published; the page prints 'Zendesk, Inc.'
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "z", "issuer_name": "Software Zendesk Zendesk, Inc.", "extracted_industry": "Software",
         "printed_row": "Zendesk, Inc. | First Lien Secured Debt | SOFR+ 650 | 06/22/29 | $ 9,000 | $ 8,900 | $ 8,950"},
    ])
    assert _ids(out) == {"z"}
    assert out.iloc[0]["kind"] == "not_the_printed_name" and out.iloc[0]["basis"] == "page"


def test_issuer_member_name_not_the_printed_company_flags():
    # Blue Owl Technology Income 2023-06-30: 'CVET Midco 2, L.P.' for the printed 'Covetrus Inc.'
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "c", "issuer_name": "CVET Midco 2, L.P.",
         "printed_row": "Covetrus Inc.(11) | Second lien senior secured loan | S + | 9.25 % | 10/2030 | 25,000 | 24,517 | 24,188 | 1.8 %"},
        # MidCap: a group-name word of the legal name is not the name
        {"row_id": "g", "issuer_name": "Global Solutions, LLC",
         "printed_row": "Continuum Global Solutions, LLC | First Lien Secured Debt | SOFR+ 500 | 1,000 | 990 | 995"},
        # Apollo Debt Solutions: the member's group name in front of the legal name
        {"row_id": "ap", "issuer_name": "Southern Veterinary Partners Southern Veterinary Partners, LLC",
         "printed_row": "Southern Veterinary Partners, LLC | First Lien Secured Debt - Term Loan | S+325, 0.00% Floor | 12/4/2031 | 24,938"},
        # instrument text left in the name
        {"row_id": "cb", "issuer_name": "Cannon Bridge Designated Activity Company, Private asset-backed investment 1",
         "printed_row": "Cannon Bridge Designated Activity Company (10) | Private asset-backed investment | 10.56% | Euribor (S)"},
    ])
    assert _ids(out) == {"c", "g", "ap", "cb"}


def test_issuer_spacing_only_is_its_own_kind():
    # owner 2026-11-10: a whitespace-only difference is its own, informational kind; a difference in
    # punctuation (a lost apostrophe) that the folded comparison cannot see stays spacing_only
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "ct", "issuer_name": "Circus Trix Holdings LLC",
         "printed_row": "CircusTrix Holdings LLC | First Lien Secured Debt | SOFR+675, 1.00% Floor | 07/18/28 | 4,000"},
        {"row_id": "ob", "issuer_name": "OBrien Holdings LLC",
         "printed_row": "O'Brien Holdings LLC | First Lien Secured Debt | SOFR+675, 1.00% Floor | 07/18/28 | 4,000"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"ct": "whitespace_only", "ob": "spacing_only"}


def test_issuer_fund_label_printed_as_the_name_is_not_flagged():
    # Overland Advantage: 'U.S. Treasury Bill' is the fund's own industry label and the printed name
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "tb", "issuer_name": "U.S. Treasury Bill", "extracted_industry": "U.S. Treasury Bill",
         "printed_row": "U.S. Treasury Bill | 4.28% | 8/7/2025 | 160,000 | $157,670 | $157,633 | 33.12 %"},
    ])
    assert out.empty


def test_issuer_shape_fallback_flags_when_row_not_on_page():
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "s", "issuer_name": "Debt Investments Capital Markets Cliffwater, LLC"},
        {"row_id": "i", "issuer_name": "Health Care Equipment"},
        {"row_id": "h", "issuer_name": "Software Zendesk Zendesk, Inc.", "extracted_industry": "Software"},
    ])
    kinds = dict(zip(out["row_id"], out["kind"]))
    assert kinds == {"s": "begins_with_section_word", "i": "equals_industry_label", "h": "begins_with_industry_label"}
    assert set(out["basis"]) == {"shape"}


def test_issuer_guards_legitimate_names():
    out = _run(cr.issuer_name_differs_from_page, [
        # footnote marks and punctuation folded
        {"row_id": "l", "issuer_name": "Lighthouse Lab Services",
         "printed_row": "Lighthouse Lab Services (5) | Senior Secured First Lien Revolver | S + 575 (100 Floor) | 11.27% | 10/2027 | 614 | 605 | 0.1 | 583"},
        {"row_id": "p", "issuer_name": "Picard Holdco, Inc.",
         "printed_row": "Picard Holdco, Inc.(8)(23) | Senior A Preferred Stock | S + 12.00 % PIK | N/A | 52,848 | 55,887 | 60,955 | 2.8 %"},
        {"row_id": "w", "issuer_name": "Galway Borrower LLC",
         "printed_row": "Galway Borrower, LLC | Financials | Delayed Draw Term Loan | 10.74 % | 39,209 | 38,926 | 38,621"},
        # a company named after an industry word, on the page and off it
        {"row_id": "a", "issuer_name": "Insurance Auto Auctions, Inc.", "extracted_industry": "Automobiles",
         "printed_row": "Insurance Auto Auctions, Inc. | First lien | S + 5.00 % | 1,000 | 990 | 995"},
        {"row_id": "b", "issuer_name": "Insurance Auto Auctions, Inc.", "extracted_industry": "Automobiles"},
        # industry cell printed before the name
        {"row_id": "k", "issuer_name": "Cyan Investors LP", "extracted_industry": "Healthcare Equipment and Supplies",
         "printed_row": "Healthcare Equipment and Supplies Cyan Investors LP (6)(9) | LP Units | - | 610 | 535 | 535"},
        # a later tranche printed without its company: not comparable, and its name has no bad shape
        {"row_id": "t", "issuer_name": "Acme Holdings, LLC",
         "printed_row": "First Lien Delayed Draw Term Loan | S + 5.00 % | 1,000 | 990 | 995"},
        # Ares: the row begins with the instrument (company printed on the row above)
        {"row_id": "ar", "issuer_name": "UKG Inc. and H&F Unite Partners, L.P.",
         "printed_row": "Limited partnership interests | 05/2019 | 12,583,556 | 12.6 | 17.8 | (2)(6)"},
        {"row_id": "z2", "issuer_name": "MC Accelerate Co-Invest Feeder LP",
         "printed_row": "Z2 preferred shares | 12.00% (6.00% PIK) | 08/2025 | 08/2031 | 15,586"},
        # New Mountain: the row begins with its industry heading
        {"row_id": "nm", "issuer_name": "Michael Baker International, LLC", "extracted_industry": "Business Services",
         "printed_row": "Business Services | First Lien(4) | SOFR(M) | + | 4.00% | 8.32% | 01/2025 | 12/2028 | 9,975"},
        # ... and with no extracted industry: the cell heads rows of several different issuers
        {"row_id": "nm1", "issuer_name": "KWOR Acquisition, Inc.",
         "printed_row": "Healthcare | Subordinated(4) | SOFR(Q)* | + | 8.00%/PIK | 11.67% | 02/2025 | 8,055"},
        {"row_id": "nm2", "issuer_name": "CCBlue Bidco, Inc.",
         "printed_row": "Healthcare | First Lien(2)(4) | SOFR(Q)* | + | 2.50% | 10.27% | 12/2021 | 49,042"},
        {"row_id": "nm3", "issuer_name": "DECA Dental Holdings LLC",
         "printed_row": "Healthcare | First Lien(2)(3)(4) | SOFR(Q) | + | 5.75% | 10.18% | 08/2021 | 28,086"},
        # a leading 'The' printed and not published
        {"row_id": "db", "issuer_name": "Dun & Bradstreet Corporation",
         "printed_row": "The Dun & Bradstreet Corporation | First lien senior secured loan | 6.59% | SOFR (M) | 2.25%"},
        # a count in brackets inside the name cell
        {"row_id": "ta", "issuer_name": "Talos Energy Inc.",
         "printed_row": "Talos Energy Inc. (12,138 shares of common stock) | (6)(13) | 1/2023 | 250 | 210"},
    ])
    assert out.empty, out[["row_id", "kind"]]


def test_issuer_later_tranche_instrument_cells_are_not_compared():
    # 2026-10-20 review: five continuation rows whose first cell is an instrument the stop list missed
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "bb", "issuer_name": "Perimeter Master Note Business Trust",
         "printed_row": "Structured Secured Note - Class B | 5.4% Cash | 03/2029 | 181 | 181 | 181"},
        {"row_id": "be", "issuer_name": "Perimeter Master Note Business Trust",
         "printed_row": "Structured Secured Note - Class E | 11.4% Cash | 03/2029 | 8,503 | 8,503 | 8,503"},
        {"row_id": "ih", "issuer_name": "Ivy Hill Asset Management, L.P.",
         "printed_row": "Member interest (100.00% interest) | (6)(11) | 06/2009 | 1,924.6 | 1,924.6"},
        {"row_id": "rc", "issuer_name": "Raptor US Buyer II Corp.",
         "printed_row": "12,832 Class C | 03/2023 | 1,283 | 1,288 | 0.1%"},
        {"row_id": "re", "issuer_name": "Raptor US Buyer II Corp.",
         "printed_row": "12,832 Class E | 03/2023 | 1,283 | 1,287 | 0.1%"},
    ])
    assert out.empty, out[["row_id", "kind"]]


def test_issuer_names_with_class_interest_or_a_number_are_still_compared():
    rows = [
        # Kayne Anderson prints 'Class Valuation'; Bain '1375 Owner LLC'; a name containing 'Interest'
        {"row_id": "cv", "issuer_name": "Class Valuation",
         "printed_row": "Class Valuation | First Lien Senior Secured | S + 5.50% | 1,000 | 990 | 995"},
        {"row_id": "is", "issuer_name": "Interest Solutions Inc",
         "printed_row": "Interest Solutions Inc | First lien | S + 5.00 % | 1,000 | 990 | 995"},
        {"row_id": "ow", "issuer_name": "1375 Owner LLC",
         "printed_row": "1375 Owner LLC (4)(5) | First Lien Senior Secured Loan | 9.00% | 1,000 | 990 | 995"},
        {"row_id": "sc", "issuer_name": "Structured Credit Partners JV, LLC",
         "printed_row": "Structured Credit Partners JV, LLC | Class A | 1,000 | 990"},
    ]
    assert _run(cr.issuer_name_differs_from_page, rows).empty
    # the same printed rows under another published name still flag
    wrong = [dict(r, issuer_name=n) for r, n in zip(rows, ["Apex Valuation", "Omega Solutions Inc", "1375 Mezz LLC",
                                                            "Credit Partners Feeder LLC"])]
    out = _run(cr.issuer_name_differs_from_page, wrong)
    assert _ids(out) == {"cv", "is", "ow", "sc"}
    assert set(out["kind"]) == {"not_the_printed_name"} and set(out["basis"]) == {"page"}


# ---------------------------------------------------------------- rule 2: unit counts

def test_units_labelled_count_differs_flags():
    # Golub 2023: IRGSE Class A published 8,800,000 (another row's) for the printed 33,790,171
    out = _run(cr.unit_count_differs_from_row_text, [
        {"row_id": "u", "asset_category": "EQUITY_COMMON", "shares_held": 8_800_000, "shares_held_source": "derived_proxy",
         "issuer_name": "IRGSE Holding Corp.", "printed_row": "Class A Units ( 33,790,171 units) | 12/21/2018 | 21,842 | 17,993 | 1.3 %"},
        {"row_id": "n", "asset_category": "EQUITY_PREFERRED", "shares_held": None,
         "bdc_investment_identifier": "Talos Energy Inc. (12,138 shares of common stock)"},
    ])
    kinds = dict(zip(out["row_id"], out["kind"]))
    assert kinds == {"u": "labelled_count_differs", "n": "labelled_count_not_published"}


def test_units_proxy_count_not_on_row_flags():
    # Crescent: Integrity common published the neighbouring preferred's 1,247 for the printed 287,484
    out = _run(cr.unit_count_differs_from_row_text, [
        {"row_id": "i", "asset_category": "EQUITY_COMMON", "shares_held": 1247, "shares_held_source": "derived_proxy",
         "printed_row": "Integrity Marketing Acquisition, LLC | Common Stock | 287,484 | 533 | 0.1 | 937"},
    ])
    assert list(out["kind"]) == ["proxy_count_not_on_row"]


def test_units_guards():
    out = _run(cr.unit_count_differs_from_row_text, [
        {"row_id": "ok", "asset_category": "EQUITY_COMMON", "shares_held": 33_790_171,
         "printed_row": "Class A Units ( 33,790,171 units) | 12/21/2018 | 21,842 | 17,993 | 1.3 %"},
        # a preferred whose page prints no units, published with none
        {"row_id": "np", "asset_category": "EQUITY_PREFERRED", "shares_held": None,
         "printed_row": "Bluesight, Inc. | Class A Preferred | 9.00 % PIK | 12/2023 | 1,659 | 1,773"},
        # 'Class A-1 Units' is a class name, not a count of one unit
        {"row_id": "cls", "asset_category": "EQUITY_COMMON", "shares_held": 500,
         "bdc_investment_identifier": "Equity Securities, Class A-1 Units"},
        # a derived count that is on the row is fine; a percent membership interest is not a count
        {"row_id": "px", "asset_category": "EQUITY_COMMON", "shares_held": 162, "shares_held_source": "derived_proxy",
         "printed_row": "Scp Mechanical Services Holdco, LLC (p) | Class B Units | 162 | 161,740 | 75,578"},
        {"row_id": "pct", "asset_category": "EQUITY_COMMON", "shares_held": 19,
         "printed_row": "Twin Brook Segregated Equity Holdings, LLC | Equity - 2.11 % membership interest | 19 | 15 | 0.00 %"},
        # rounding of a fractional count
        {"row_id": "fr", "asset_category": "EQUITY_COMMON", "shares_held": 923857.68,
         "printed_row": "LLC Units (923,857.7 units) | n/a | 10/21 | n/a | 9"},
        # a year before a column label is not a count (Trinity's member text)
        {"row_id": "yr", "asset_category": "EQUITY_COMMON", "shares_held": 1000,
         "bdc_investment_identifier": "Equipment Leasing Services, LLC Type of Investment Equity Investment Date "
                                      "January 30, 2026 Shares 1,000 Membership Interest"},
        # not equity
        {"row_id": "loan", "asset_category": "LOAN", "shares_held": 5,
         "printed_row": "Acme (100 units) | First lien | 1,000 | 990"},
    ])
    assert out.empty, out[["row_id", "kind"]]


# ---------------------------------------------------------------- rule 3: PIK printed

def test_pik_printed_not_published_flags():
    out = _run(cr.pik_printed_not_published, [
        # Crescent Lighthouse 2023-12-31: '(including 75 PIK)' in the terms; no pik_rate
        {"row_id": "l", "pik_rate": None,
         "bdc_investment_identifier": "Investments United States Debt Investments Health Care Equipment & Services "
                                      "Lighthouse Behavioral Health Solutions, LLC Investment Type Senior Secured First Lien "
                                      "Term Loan Interest Term S + 650 (100 Floor) (Including 75 PIK) Interest Rate 11.36%"},
        # Golub Sundy Village 2025-12-31
        {"row_id": "s", "pik_rate": None,
         "printed_row": "Sundy Village West Mezz Borrower, LLC (12) | SF | 11.50 % | 15.28 % PIK | 12/21/2023 | 1/15/2027 | 14,625 | 14,625 | 14,877 | 0.5 %"},
        # bare basis points, whole coupon PIK
        {"row_id": "b", "pik_rate": 0.0, "printed_row": "Acme | Unsecured Debt | 1250 PIK | 12.50% | 05/2029 | 1,000"},
    ])
    figs = dict(zip(out["row_id"], out["printed"]))
    kinds = dict(zip(out["row_id"], out["kind"]))
    # D-207: the member-only Lighthouse row is the weaker kind; the printed rows raise
    assert kinds == {"l": "pik_member_text_only", "s": "pik_printed_not_published", "b": "pik_printed_not_published"}
    assert figs == {"l": "0.75", "s": "15.28", "b": "12.5"}


def test_pik_value_mismatch_flags():
    out = _run(cr.pik_printed_not_published, [
        {"row_id": "m", "pik_rate": 2.5, "printed_row": "Acme | First lien | S + 6.25% (incl. 5.25% PIK) | 10.07% | 02/28/2030"},
        # MidCap HomeRenew: pik_rate holds the floor
        {"row_id": "h", "pik_rate": 2.5, "printed_row": "HomeRenew Buyer, Inc. | First Lien Secured Debt - Term Loan | "
                                                          "SOFR+650 PIK, 2.50% Floor | 04/14/30 | 3,192 | 3,192 | 3,192"},
        # North Haven Cyara: tag 2.2 for the printed 2.25 -- rounded to fewer decimals, passes
        {"row_id": "r", "pik_rate": 2.2, "printed_row": "Cyara AcquisitionCo, LLC | First Lien Debt | S + | 6.25% (incl. 2.25% PIK) | 9.75"},
        # Antares Vertex: 3.8 for the printed 3.83 (labelled false alarm)
        {"row_id": "v", "pik_rate": 3.8, "printed_row": "Vertex Service Partners, LLC | (7)(13)(15)(17) | First Lien Delayed Draw "
                                                          "Term Loan | S + 5.25% | 8.90% (Incl. 3.83% PIK) | 11/8/2030 | 1,502"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"m": "pik_value_mismatch", "h": "pik_value_mismatch"}


def test_pik_raised_on_the_page_only():
    out = _run(cr.pik_printed_not_published, [
        # HPS Foundation Automotive: printed on the row, not published -> raised on the page
        {"row_id": "fa", "pik_rate": None,
         "printed_row": "Foundation Automotive US Corp (4)(7)(18) | SF + | 7.75% PIK | 12/24/2027 | 18,779 | 18,571 | 10,095"},
        # Diameter BVI (labelled false alarm): member '(5.00% PIK)', the DDTL row prints no PIK
        {"row_id": "bvi", "pik_rate": None, "bdc_investment_identifier": "BVI Medical, Inc., Delayed Draw Term Loan (5.00% PIK)",
         "printed_row": "BVI Medical, Inc. | Delayed Draw Term Loan | S + 5.00% | 9.50% | 06/2031 | 2,000 | 1,931"},
        # AB American Physician (labelled false alarm): member 3.00% PIK, page 3.50% PIK = published
        {"row_id": "app", "pik_rate": 3.5,
         "bdc_investment_identifier": "US Corporate Debt | American Physician Partners, LLC | Delayed Draw Term Loan | (S + 6.75%; 1.00% Floor; 3.00% PIK)",
         "printed_row": "American Physician Partners, LLC | Healthcare | Delayed Draw Term Loan | (S + 6.75%; 1.00% Floor; 3.50% PIK) | 3/31/2026"},
    ])
    got = {r.row_id: (r.kind, r.basis) for r in out.itertuples()}
    assert got == {"fa": ("pik_printed_not_published", "page"), "bvi": ("pik_member_text_only", "member_page_silent")}


def test_pik_guards():
    out = _run(cr.pik_printed_not_published, [
        {"row_id": "pike", "pik_rate": None, "printed_row": "Pike Electric Corp. | (8) | SOFR + | 3.00 % | 1,000"},
        {"row_id": "toggle", "pik_rate": None, "printed_row": "Acme | Senior notes (PIK toggle, not elected) | 9.00 % | 1,000"},
        {"row_id": "class", "pik_rate": None, "printed_row": "Acme Series 2 PIK Notes | 9.00 % | 1,000"},
        {"row_id": "zero", "pik_rate": None, "printed_row": "Acme | First lien | S + 5.00 %, 0.00 % PIK | 1,000"},
        {"row_id": "word", "pik_rate": None, "bdc_investment_identifier": "Rent Newco, LLC, Class H PIK Preferred Equity"},
        # published and printed agree, including split cells and a cash/PIK pair
        {"row_id": "incl", "pik_rate": 3.75, "printed_row": "Acme | 12.75% (incl. 3.75% PIK) | 12.75% | 10/31/2027"},
        {"row_id": "split", "pik_rate": 2.0, "printed_row": "Acme | 12.00 | % | 2.00 | % PIK | 6/10/2022"},
        {"row_id": "pair", "pik_rate": 2.5, "printed_row": "EFC | Senior Unsecured Term Loan | 11.0 % Cash, 2.5 % PIK | 03/23 | 669"},
        # fully PIK: printed, published, not compared
        {"row_id": "full", "pik_rate": 11.29, "printed_row": "Buckeye | 11.29 % ( 100 % PIK) | 12/31/2024 | 4,099"},
    ])
    assert out.empty, out[["row_id", "kind", "printed"]]


def test_pik_whole_coupon_after_benchmark_passes_d232():
    # D-232 (owner 2026-10-25): '<benchmark> + m % PIK <coupon> %', whole coupon PIK, pik_rate = coupon
    out = _run(cr.pik_printed_not_published, [
        # T Series Applitools
        {"row_id": "appl", "pik_rate": 11.35,
         "printed_row": "Applitools, Inc. (4) (6) (10) (11) S + 6.25 % PIK 11.35 % 5/25/2029 7,229 7,134 7,015 0.87"},
        # the same row as the page reader joins its cells (rftsc 2023-09-30)
        {"row_id": "appl_cells", "pik_rate": 11.35,
         "printed_row": "Applitools, Inc. | (4) (6) (10) (11) | S + | 6.25% PIK | 11.35% | 5/25/2029 | 7,229 | 7,134 | 7,015 | 0.87"},
        # Commonwealth Kent
        {"row_id": "kent", "pik_rate": 14.44,
         "printed_row": "Kent Holdco, LLC | First Lien Term Loan | SOFR + 9.00 % PIK | 14.44 % | 02/25/2027 | 4,000"},
        # tenor printed after the benchmark code
        {"row_id": "tenor", "pik_rate": 11.6, "printed_row": "Acme | Term Loan | S (Q) + 6.25 % PIK | 11.60 % | 1,000"},
        # the margin itself still passes, as before
        {"row_id": "margin", "pik_rate": 6.25, "printed_row": "Acme | Term Loan | S + 6.25 % PIK | 11.35 % | 1,000"},
    ])
    assert out.empty, out[["row_id", "kind", "printed"]]


def test_pik_whole_coupon_d232_false_positives():
    out = _run(cr.pik_printed_not_published, [
        # T Series Continental Battery 2025-09-30: no benchmark printed before the PIK figure; separate ruling
        {"row_id": "cont", "pik_rate": 11.29,
         "printed_row": "Continental Battery Merger Sub, Inc. (4) (6) (10) 7.00 % PIK 11.29 % 1/20/2027 5,000 4,950 4,800 0.60"},
        {"row_id": "cont_cells", "pik_rate": 11.29,
         "printed_row": "Continental Battery Merger Sub, Inc. | (4) (6) (10) | First Lien Debt | 7.00% PIK | 11.29% | 1/20/2027 | 5,000"},
        # partial PIK: the PIK figure is inside '(incl. ...)', not after the benchmark
        {"row_id": "partial", "pik_rate": 10.3,
         "printed_row": "Acme | First Lien | S + 6.00 % (incl. 2.00 % PIK) 10.30 % | 1,000"},
        # whole-coupon format, pik_rate equal to no printed figure
        {"row_id": "other", "pik_rate": 9.75,
         "printed_row": "Applitools, Inc. (4) (6) (10) (11) S + 6.25 % PIK 11.35 % 5/25/2029 7,229 7,134 7,015 0.87"},
        # whole-coupon format, pik_rate equal to a printed percent below the margin (a floor)
        {"row_id": "floor", "pik_rate": 1.0,
         "printed_row": "Acme | Term Loan | S + 6.25 % PIK, 1.00 % Floor | 11.35 % | 1,000"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {
        "cont": "pik_value_mismatch", "cont_cells": "pik_value_mismatch", "partial": "pik_value_mismatch", "other": "pik_value_mismatch",
        "floor": "pik_value_mismatch"}


def test_pik_whole_coupon_basis_points_and_benchmark_cell_pass():
    # REQ-rfcr-1 / REQ-rfbn-1 (owner 2026-11-04): rows as the page reader joins them in the accepted sandboxes
    out = _run(cr.pik_printed_not_published, [
        # Crescent Mario Purchaser last-out 2023-03-31 (rfcrf)
        {"row_id": "mario", "pik_rate": 15.66, "printed_row": "Mario Purchaser, LLC (10) | Unitranche First Lien - Last Out "
                                                              "Term Loan | S + 1075 PIK | 15.66% | 04/2032 | 3,207 | 3,103 | 0.4 | 3,107"},
        # Crescent AX VI second lien, euro benchmark
        {"row_id": "axvi", "pik_rate": 13.23, "printed_row": "AX VI INV2 Holding AB (Voff) (6)(11) | Senior Secured Second Lien "
                                                             "Term Loan | E + 1000 PIK | 13.23% | 08/2030 | 1,931 | 1,902"},
        # Crescent Integro, floor after PIK
        {"row_id": "integro", "pik_rate": 16.83, "printed_row": "Integro Parent, Inc. (11) | Senior Secured First Lien Term Loan | "
                                                                "S + 1225 PIK (100 Floor) | 16.83% | 706 | 706 | 0.1 | 706"},
        # 0001899017 Masco: benchmark in its own cell, no '+'
        {"row_id": "masco", "pik_rate": 13.25, "printed_row": "Masco (6)(15)(17)(21) | Subordinated Debt | EURIBOR | 10.00% PIK | "
                                                              "13.25 | % | 10/4/2032 | 5,000 | 5,348 | 5,102"},
        # 0001899017 Cube 2026-06-30: a dash cell between the benchmark and the margin
        {"row_id": "cube", "pik_rate": 13.73, "printed_row": "First Lien Senior Secured Loan - Delayed Draw | SONIA | — | "
                                                             "10.00% PIK | 13.73% | 5/22/2032 | 2,334 | 3,190 | 3,098"},
        # Commonwealth VardimanBlack 2024-09-30 / 2024-12-31 (D-218): pik_rate = R - 5.00
        {"row_id": "vard", "pik_rate": 7.3, "printed_row": "VardimanBlack Holdings, LLC - Term Loan | Health Care Equipment & "
                                                           "Services | SOFR + 2.00% PIK + 5.00% | 12.30% | 3/18/2027 | 19,825"},
        {"row_id": "vard_fixed", "pik_rate": 6.65, "printed_row": "VardimanBlack Holdings, LLC | Health Care Equipment & Services | "
                                                                 "SOFR + 2.00% PIK + 5.00% Fixed | 11.65% | 3/18/2027 | 20,173"},
    ])
    assert out.empty, out[["row_id", "kind", "printed"]]


def test_pik_whole_coupon_basis_points_false_positives():
    out = _run(cr.pik_printed_not_published, [
        # Continental Battery 2025-09-30: no benchmark on the row; stays for its own ruling
        {"row_id": "cont", "pik_rate": 11.29, "printed_row": " Battery Company | (5) (11) (12) (13) | First Lien Debt | 7.00% PIK | "
                                                            "11.29% | 07/20/2028 | 6,473 | 6,415 | 1,992 | 0.18"},
        # a bps margin with a pik_rate that is no printed figure
        {"row_id": "bps_other", "pik_rate": 14.0, "printed_row": "Mario Purchaser, LLC | Last Out Term Loan | S + 1075 PIK | 15.66% | 04/2032"},
        # a partial PIK printed in basis points: the PIK part is inside the bracket, not after the benchmark
        {"row_id": "bps_partial", "pik_rate": 11.36, "printed_row": "Lighthouse | Term Loan | S + 650 (100 Floor) (Including 75 PIK) | 11.36% | 1,000"},
        # MidCap HomeRenew: pik_rate holds the floor
        {"row_id": "floor", "pik_rate": 2.5, "printed_row": "HomeRenew Buyer, Inc. | First Lien Secured Debt - Term Loan | "
                                                            "SOFR+650 PIK, 2.50% Floor | 04/14/30 | 3,192"},
        # benchmark cell with a cash margin and a separate PIK cell is not a whole coupon
        {"row_id": "cell_partial", "pik_rate": 9.5, "printed_row": "Acme | SOFR | 5.00% | 2.00% PIK | 9.50% | 1,000"},
        # VardimanBlack with the whole printed rate as pik_rate: the 5.00 fixed leg is cash (D-218)
        {"row_id": "vard_whole", "pik_rate": 12.3, "printed_row": "VardimanBlack Holdings, LLC - Term Loan | Health Care Equipment & "
                                                                 "Services | SOFR + 2.00% PIK + 5.00% | 12.30% | 3/18/2027 | 19,825"},
        # VardimanBlack with a pik_rate that is R less the wrong leg
        {"row_id": "vard_other", "pik_rate": 10.3, "printed_row": "VardimanBlack Holdings, LLC - Term Loan | Health Care Equipment & "
                                                                 "Services | SOFR + 2.00% PIK + 5.00% | 12.30% | 3/18/2027 | 19,825"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {k: "pik_value_mismatch" for k in (
        "cont", "bps_other", "bps_partial", "floor", "cell_partial", "vard_whole", "vard_other")}


def test_pik_figure_with_no_leading_zero_reads_as_a_fraction():
    # Varagon (CIK 1784700) prints a PIK figure as '( .50 % PIK)', which the rule read as 50.
    # '.50', '0.50' and '5.0' must each read as printed.
    out = _run(cr.pik_printed_not_published, [
        {"row_id": "dot", "pik_rate": None, "printed_row": "Acme | Term Loan | SOFR + 6.00 % (M) | 11.43 % ( .50 % PIK) | 1,000"},
        {"row_id": "zero", "pik_rate": None, "printed_row": "Acme | Term Loan | SOFR + 6.00 % | 11.43 % ( 0.50 % PIK) | 1,000"},
        {"row_id": "five", "pik_rate": None, "printed_row": "Acme | Term Loan | SOFR + 6.00 % | 11.43 % ( 5.0 % PIK) | 1,000"},
        {"row_id": "bare", "pik_rate": None, "printed_row": "Acme | Term Loan | S + 600 (including .50 PIK) | 1,000"},
    ])
    assert dict(zip(out["row_id"], out["printed"])) == {"dot": "0.5", "zero": "0.5", "five": "5.0", "bare": "0.5"}
    # a published 0.50 agrees with '.50'; false-positive guard: a whole '5 %' is still 5, not 0.5
    out = _run(cr.pik_printed_not_published, [
        {"row_id": "dot_ok", "pik_rate": 0.5, "printed_row": "Acme | Term Loan | 11.43 % ( .50 % PIK) | 1,000"},
        {"row_id": "whole", "pik_rate": 0.5, "printed_row": "Acme | Term Loan | 11.43 % ( 5 % PIK) | 1,000"},
        {"row_id": "whole_ok", "pik_rate": 5.0, "printed_row": "Acme | Term Loan | 11.43 % ( 5 % PIK) | 1,000"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"whole": "pik_value_mismatch"}
    assert list(out["printed"]) == ["5.0"]


def test_units_figure_with_no_leading_zero_is_not_read_as_a_whole_number():
    # '.50 %' on a row is 0.5: a proxy count of 50 is not on the row; 1,250 printed still is
    out = _run(cr.unit_count_differs_from_row_text, [
        {"row_id": "dot", "asset_category": "EQUITY_COMMON", "shares_held": 50, "shares_held_source": "derived_proxy",
         "printed_row": "Acme Holdings | Class A Units | .50 % | 1,250 | 900"},
        {"row_id": "ok", "asset_category": "EQUITY_COMMON", "shares_held": 1250, "shares_held_source": "derived_proxy",
         "printed_row": "Acme Holdings | Class A Units | .50 % | 1,250 | 900"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"dot": "proxy_count_not_on_row"}


# ---------------------------------------------------------------- rule 4: industry coverage

def _funded(n, missing, report_date, extra=None):
    rows = []
    for i in range(n):
        rows.append({"row_id": f"{report_date}-{i}", "report_date": report_date, "fair_value": 10.0,
                     "asset_category": "LOAN", "gics_sub_industry": None if i < missing else "Application Software",
                     "extracted_industry": None})
    return rows + (extra or [])


def test_industry_low_coverage_quarter_flags_its_rows():
    rows = _funded(30, 10, "2023-03-31")
    out = _run(cr.industry_not_published, rows)
    assert len(out) == 10 and set(out["kind"]) == {"no_industry_at_all"}


def test_industry_guards():
    rows = (_funded(30, 1, "2023-06-30")            # 97 pct: above the bar
            + _funded(5, 5, "2023-09-30")           # too few funded rows to judge
            + [{"row_id": "cash", "report_date": "2023-06-30", "fair_value": 50.0, "asset_category": "CASH"},
               {"row_id": "undrawn", "report_date": "2023-06-30", "fair_value": 0.0, "asset_category": "LOAN"}])
    out = _run(cr.industry_not_published, rows)
    assert out.empty
    con = duckdb.connect()
    frame = pd.DataFrame(rows)
    frame["cik"] = "0000000001"
    frame["accession_number"] = "a"
    cr.prepare(con, frame)
    cov = cr.industry_coverage(con)
    assert list(cov["n_funded"]) == [30, 5]


# ---------------------------------------------------------------- rule 5: preferred as common

def test_preferred_as_common_flags():
    out = _run(cr.preferred_published_as_common, [
        # NC Fund 2023: 'Series A-3 Preferred Units' printed, published COMMON_EQUITY
        {"row_id": "bm", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY",
         "issuer_name": "BroadcastMed Holdco, LLC",
         "printed_row": "BroadcastMed Holdco, LLC (4) (8) (9) | Series A-3 Preferred Units | 10/4/2022 | 43,679 | 655 | 826 | 0.32 %"},
        # Kennedy Lewis / Commonwealth LNG: 13.00 % PIK, class common, member typo 'Preffered'
        {"row_id": "lng", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY", "pik_rate": 13.0,
         "issuer_name": "Commonwealth LNG Intermediate Parent, LLC",
         "bdc_investment_identifier": "Commonwealth LNG Intermediate Parent, LLC, Preffered Equity"},
        # a fixed rate on a common row (Stone Point 'Equity 12.50 %')
        {"row_id": "gt", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY", "interest_rate": 12.5,
         "issuer_name": "GT Polaris Holdings, Inc", "printed_row": "GT Polaris Holdings, Inc | Equity | 12.50 % | 6/6/2022 | 10,618,747"},
    ])
    kinds = dict(zip(out["row_id"], out["kind"]))
    # D-207: a rate alone on a common row ('GT Polaris Equity 12.50 %') is no longer a flag
    assert kinds == {"bm": "text_says_preferred", "lng": "text_and_rate"}


def test_preferred_rate_only_units_are_not_flagged():
    # Ares 'Class A units 8.00% PIK': the filer does not call them preferred (owner ruling D-207)
    out = _run(cr.preferred_published_as_common, [
        {"row_id": "pt", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY", "pik_rate": 8.0,
         "issuer_name": "PracticeTek Purchaser, LLC", "instrument_description": "Class A units",
         "printed_row": "Class A units | 8.00% PIK | 03/2021 | 33,220,282 | 23.5 | 34.3 | (2)"},
        # ... while the filer's own 'Senior preference shares' with a rate still flags
        {"row_id": "mc", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY", "pik_rate": 12.5,
         "issuer_name": "McLaren Group Limited",
         "printed_row": "McLaren Group Limited | Automobile manufacturer and retailer | Senior preference shares | 12.50% PIK | 08/2021"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"mc": "text_and_rate"}


def test_preferred_as_common_guards():
    out = _run(cr.preferred_published_as_common, [
        {"row_id": "pfs", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY",
         "issuer_name": "Preferred Freezer Services, LLC",
         "printed_row": "Preferred Freezer Services, LLC | Common Stock | 1,000 | 990 | 995"},
        {"row_id": "war", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY",
         "issuer_name": "Acme", "instrument_description": "Warrants to purchase Series B Preferred Stock"},
        {"row_id": "conv", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY",
         "issuer_name": "Acme", "instrument_description": "Common stock (converted from Series A Preferred)"},
        {"row_id": "pref", "asset_category": "EQUITY_PREFERRED", "index_classification": "PREFERRED_EQUITY",
         "issuer_name": "Acme", "instrument_description": "Series A Preferred", "pik_rate": 8.0},
        {"row_id": "plain", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY",
         "issuer_name": "Acme", "instrument_description": "Class A Units"},
    ])
    assert out.empty, out[["row_id", "kind"]]


def test_rules_registry_and_output_columns():
    assert set(cr.RULES) == {"issuer_name_differs_from_page", "unit_count_differs_from_row_text",
                             "pik_printed_not_published", "industry_not_published", "preferred_published_as_common"}
    for rule in cr.RULES.values():
        out = _run(rule, [{"row_id": "x", "issuer_name": "Acme, Inc.", "asset_category": "LOAN", "fair_value": 1.0,
                           "gics_sub_industry": "Application Software"}])
        assert list(out.columns) == cr.OUTPUT_COLUMNS


def test_nothing_in_the_build_imports_candidate_rules():
    import pathlib
    import re
    repo = pathlib.Path(__file__).resolve().parents[1]
    imports = re.compile(r"(?m)^\s*(from\s+pipeline(\.candidate_rules|\s+import\s+[^\n]*\bcandidate_rules\b)"
                         r"|import\s+pipeline\.candidate_rules)")
    # Wired 2026-10-19 (D-207): the shadow identity engine is the one build-side importer; read-only
    # evidence scripts (scripts/v05_evidence/) may import it too.
    users = [p.name for root in ("pipeline", "scripts") for p in (repo / root).rglob("*.py")
             if imports.search(p.read_text(encoding="utf-8", errors="ignore"))
             and p.name != "candidate_rules.py" and "v05_evidence" not in p.parts]
    assert users == ["shadow_identity_engine.py"], users


# ---------------------------------------------------------------- 2026-10-18 review fixes (D-207)

def test_issuer_name_printed_elsewhere_in_the_filing_passes():
    out = _run(cr.issuer_name_differs_from_page, [
        # Antares 2026-03-31 (labelled false alarm): this row prints 'ClearCapital', a sibling row 'Clear Capital'
        {"row_id": "cc1", "issuer_name": "Clear Capital Holdings, LLC",
         "printed_row": "ClearCapital Holdings, LLC | (7)(13) | First Lien Revolver | S + 5.00% | 1,000"},
        {"row_id": "cc2", "issuer_name": "Clear Capital Holdings, LLC",
         "printed_row": "Clear Capital Holdings, LLC | (7)(13) | First Lien Term Loan | S + 5.00% | 9,000"},
        # Apollo group prefix: the legal name printed elsewhere does not rescue the glued name
        {"row_id": "gn1", "issuer_name": "Gannett Gannett Holdings, LLC",
         "printed_row": "Gannett Holdings, LLC | First Lien Secured Debt - Term Loan | S+511, 0.50% Floor | 44,195"},
        {"row_id": "gn2", "issuer_name": "Gannett Holdings, LLC",
         "printed_row": "Gannett Holdings, LLC | First Lien Secured Debt - Revolver | S+511, 0.50% Floor | 1,000"},
    ])
    assert _ids(out) == {"gn1"}


def test_issuer_trailing_legal_form_difference_passes():
    out = _run(cr.issuer_name_differs_from_page, [
        # Bain (labelled false alarm): member adds 'LLC', the page prints 'IMA Financial Group (14)'
        {"row_id": "ima", "issuer_name": "IMA Financial Group LLC",
         "printed_row": "IMA Financial Group (14) | First Lien Senior Secured Loan | S + 3.00% | 2,988"},
        {"row_id": "inc", "issuer_name": "Kele Holdco Inc",
         "printed_row": "Kele Holdco, Inc. | First Lien | S + 4.50% | 1,355"},
        # MSD (labelled real): a member typo is not a legal-form difference
        {"row_id": "msd", "issuer_name": "USA Debunk, LLC",
         "printed_row": "USA Debusk, LLC | First Lien Term Loan | S + 5.50% | 10,000"},
    ])
    assert _ids(out) == {"msd"}


def test_issuer_page_flags_suppressed_in_a_blind_fund_quarter():
    # NMF SLF I (labelled false alarms): the company sits on its own row, so nearly every instrument
    # row has no name cell; the one with an industry first cell leaks through unless suppressed
    blind = [{"row_id": f"b{i}", "report_date": "2024-09-30", "issuer_name": "Sierra Enterprises, LLC",
              "printed_row": "First Lien | SOFR(Q) | 5.00% | 9.60% | 1,000"} for i in range(9)]
    leak = {"row_id": "leak", "report_date": "2024-09-30", "issuer_name": "Sierra Enterprises, LLC",
            "printed_row": "Food & Beverage | First Lien | SOFR(Q) | 5.00% | 9.60% | 25,646"}
    shape = {"row_id": "shape", "report_date": "2024-09-30", "issuer_name": "Debt Investments Capital Markets Cliffwater, LLC"}
    # the same leak in a fund-quarter the page test can see is raised
    seen = [{"row_id": "seen", "report_date": "2024-12-31", "issuer_name": "Sierra Enterprises, LLC",
             "printed_row": "Food & Beverage | First Lien | SOFR(Q) | 5.00% | 9.60% | 25,646"},
            {"row_id": "ok", "report_date": "2024-12-31", "issuer_name": "Coyote Buyer, LLC",
             "printed_row": "Coyote Buyer, LLC | First Lien | SOFR(Q) | 5.00% | 9.60% | 1,000"}]
    out = _run(cr.issuer_name_differs_from_page, blind + [leak, shape] + seen)
    assert _ids(out) == {"shape", "seen"}  # shape-basis flags are not suppressed
    spots = out.attrs["blind_spots"].set_index("report_date")
    assert bool(spots.loc["2024-09-30", "page_test_suppressed"])
    assert (spots.loc["2024-09-30", "n_no_name_cell"], spots.loc["2024-09-30", "n_no_printed_row"]) == (9, 1)
    assert not bool(spots.loc["2024-12-31", "page_test_suppressed"])


def test_units_issuer_name_digit_and_printed_count_pass():
    out = _run(cr.unit_count_differs_from_row_text, [
        # Diameter (labelled false alarm): 'Holdings 1 LLC Class B Interests' is not a count of 1
        {"row_id": "vci", "asset_category": "EQUITY_COMMON", "shares_held": 1237, "issuer_name": "VCI Asset Holdings 1 LLC",
         "bdc_investment_identifier": "VCI Asset Holdings 1 LLC Class B Interests",
         "printed_row": "VCI Asset Holdings 1 LLC | Class B Interests | 1,237 | 1,250 | 1,273"},
        # Ares PFL (labelled false alarm): member 'up to 3,280,444 shares', page and published 3,223,122
        {"row_id": "pfl", "asset_category": "EQUITY_COMMON", "shares_held": 3223122,
         "issuer_name": "Professional Fighters League, LLC and PFL MMA, Inc.",
         "bdc_investment_identifier": "Professional Fighters League, LLC and PFL MMA, Inc., Warrant to purchase up to 3,280,444 shares of Series E preferred stock",
         "printed_row": "Warrant to purchase up to 3,223,122 shares of Series E preferred stock | 01/2021 | 3,223,122 | 0.4 | 0.8"},
        # a real labelled count still flags with a digit in the name
        {"row_id": "h2", "asset_category": "EQUITY_COMMON", "shares_held": 700, "issuer_name": "Acme Holdings 2 LLC",
         "printed_row": "Acme Holdings 2 LLC (5,000 units) | 03/2022 | 500 | 650"},
        # BCRED Point Broadband (labelled real): Class B carries Class A's count
        {"row_id": "pb", "asset_category": "EQUITY_COMMON", "shares_held": 15636, "shares_held_source": "derived_proxy",
         "issuer_name": "Point Broadband Holdings, LLC",
         "printed_row": "Point Broadband Holdings, LLC - Class B Common Units | (4) | 10/1/2021 | 685,760 | 1,955 | 2,482 | 0.01"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"h2": "labelled_count_differs", "pb": "proxy_count_not_on_row"}


def test_units_scale_unclear_is_its_own_kind():
    out = _run(cr.unit_count_differs_from_row_text, [
        # HPS Wash & Wax (labelled unclear): 'Par Amount/Units' 6,312, published 6,312,000
        {"row_id": "ww", "asset_category": "EQUITY_COMMON", "shares_held": 6312000, "shares_held_source": "derived_proxy",
         "issuer_name": "Wash & Wax Group LP", "printed_row": "Wash & Wax Group LP (4)(20)(22) | 6,312 | 8,547 | 6,991"},
        # Crescent Iris (labelled real): 577 for the printed 576,923 is not a units-scale question
        {"row_id": "ir", "asset_category": "EQUITY_COMMON", "shares_held": 577, "shares_held_source": "derived_proxy",
         "issuer_name": "Iris Buyer, LLC", "printed_row": "Iris Buyer, LLC | Common Stock | 576,923 | - | 0.0 | 56"},
        # Barings Xeinadin: the row labels the count, so x1000 is an error, not a scale question
        {"row_id": "xe", "asset_category": "EQUITY_COMMON", "shares_held": 36532680, "shares_held_source": "derived_proxy",
         "issuer_name": "Xeinadin Bidco Limited", "printed_row": "Common Stock (36,533 shares) | N/A | 05/22 | N/A | 452 | 431"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"ww": "units_scale_unclear", "ir": "proxy_count_not_on_row",
                                                     "xe": "labelled_count_differs"}


def test_industry_exemption_and_warning_level():
    def rows(cik, n, missing, rd):
        return [{"row_id": f"{cik}-{rd}-{i}", "cik": cik, "report_date": rd, "fair_value": 10.0, "asset_category": "LOAN",
                 "gics_sub_industry": None if i < missing else "Application Software"} for i in range(n)]
    data = (rows("0002049733", 30, 30, "2025-06-30")    # Blackstone Private Real Estate Credit: exempt
            + rows("0000000009", 30, 30, "2025-06-30")  # the same gap elsewhere is a finding
            + rows("0000000009", 30, 4, "2025-09-30"))  # 0.867: warning, no rows raised
    con = duckdb.connect()
    frame = pd.DataFrame(data)
    frame["accession_number"] = "a"
    cr.prepare(con, frame)
    out = cr.industry_not_published(con)
    assert set(out["cik"]) == {"0000000009"} and set(out["report_date"]) == {"2025-06-30"} and len(out) == 30
    levels = {(r.cik, r.report_date): r.level for r in cr.industry_coverage(con).itertuples()}
    assert levels == {("0000000009", "2025-06-30"): "finding", ("0000000009", "2025-09-30"): "warning",
                      ("0002049733", "2025-06-30"): "exempt"}
    assert cr.INDUSTRY_EXEMPTIONS["0002049733"]["evidence"]


# ---------------------------------------------------------------- 2026-10-19 re-sample follow-ups

def test_issuer_other_group_entity_on_the_row_flags_again():
    # MidCap 2024-09-30 (labelled real): the equity row prints 'Wildcat Parent LP'; the loan rows of the
    # same borrower print 'Wildcat BuyerCo, Inc.', which must not rescue the equity row
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "eq", "issuer_name": "Wildcat BuyerCo, Inc.",
         "printed_row": "Wildcat Parent LP | Common Equity - Common Stock | N/A | N/A | 1,070 Shares | 107 | 290"},
        {"row_id": "tl", "issuer_name": "Wildcat BuyerCo, Inc.",
         "printed_row": "Wildcat BuyerCo, Inc. | First Lien Secured Debt - Term Loan | SOFR+575, 1.00% Floor | 02/26/27 | 17,000"},
    ])
    assert list(out["row_id"]) == ["eq"] and list(out["kind"]) == ["not_the_printed_name"]


def test_issuer_spelling_printed_for_the_same_issuer_in_another_quarter_passes():
    # 26North (labelled false alarm): 'Ascend Partner Services LLC' printed through 2024-12-31,
    # 'Ascend Partners Services LLC' from 2025-03-31; published 'Partner' throughout
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "old", "report_date": "2024-12-31", "accession_number": "a1", "issuer_name": "Ascend Partner Services LLC",
         "printed_row": "Ascend Partner Services LLC (3)(7) | First Lien Senior Secured Revolving Loan | SOFR + 5.00% | 645"},
        {"row_id": "new", "report_date": "2025-03-31", "accession_number": "a2", "issuer_name": "Ascend Partner Services LLC",
         "printed_row": "Ascend Partners Services LLC (3)(7)(11) | First Lien Senior Secured Revolving Loan | SOFR + 5.00% | 645"},
        # a member typo printed nowhere in the fund still flags (Sixth Street 'Scropio' for 'Scorpio')
        {"row_id": "typo", "report_date": "2025-03-31", "accession_number": "a2", "issuer_name": "Scropio Bidco",
         "printed_row": "Scorpio Bidco (3)(4) | First-lien loan (EUR 75,326 par, due 4/2031) | 4/4/2024 | E + 5.75%"},
    ])
    assert list(out["row_id"]) == ["typo"]


def test_preferred_heading_only_is_the_weaker_kind():
    out = _run(cr.preferred_published_as_common, [
        # AB 2026-03-31 (labelled unclear): 'Class A Units' under the filer's 'U.S. Preferred Stock' heading
        {"row_id": "avant", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY",
         "issuer_name": "Avant NewCo Holdings, L.P.",
         "bdc_investment_identifier": "U.S. Preferred Stock - 1.01% | Avant NewCo Holdings, L.P. | Class A Units | Digital Infrastructure & Services",
         "printed_row": "Avant NewCo Holdings, L.P. | Class A Units | Digital Infrastructure & Services | 12/31/2025 | 375,804"},
        # AB 2023 title-cased member with the heading after the name
        {"row_id": "netskope", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY",
         "issuer_name": "Netskope Inc",
         "bdc_investment_identifier": "Netskope Inc - U.s.preferred Stock At Two Point Zero Three Percentage - Series G"},
        # the row itself says preferred: stays a finding (Blue Owl PCF)
        {"row_id": "pcf", "asset_category": "EQUITY_COMMON", "index_classification": "COMMON_EQUITY", "pik_rate": 15.0,
         "issuer_name": "PCF Holdco, LLC",
         "bdc_investment_identifier": "U.S. Preferred Stock - 0.5% | PCF Holdco, LLC",
         "printed_row": "PCF Holdco, LLC (dba PCF Insurance Services)(16)(17) | Series A Preferred Units | 15.00% PIK | N/A"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"avant": "preferred_heading_only", "netskope": "preferred_heading_only",
                                                     "pcf": "text_and_rate"}


def test_ledger_rows_keep_weaker_kinds_out_of_findings():
    con = duckdb.connect()
    frame = pd.DataFrame([
        {"row_id": "f", "issuer_name": "Gannett Gannett Holdings, LLC",
         "printed_row": "Gannett Holdings, LLC | First Lien | S+511 | 44,195"},
        {"row_id": "w", "issuer_name": "Wash & Wax Group LP", "asset_category": "EQUITY_COMMON", "shares_held": 6312000,
         "shares_held_source": "derived_proxy", "printed_row": "Wash & Wax Group LP (4)(20)(22) | 6,312 | 8,547 | 6,991"},
        {"row_id": "h", "issuer_name": "Avant NewCo Holdings, L.P.", "asset_category": "EQUITY_COMMON",
         "bdc_investment_identifier": "U.S. Preferred Stock - 1.01% | Avant NewCo Holdings, L.P. | Class A Units",
         "printed_row": "Avant NewCo Holdings, L.P. | Class A Units | 12/31/2025 | 375,804"},
    ])
    frame["cik"], frame["report_date"], frame["accession_number"] = "0000000001", "2025-12-31", "a"
    cr.prepare(con, frame)
    tested, info, blind = cr.ledger_rows(con)
    found = tested[tested["finding"] > 0]
    assert list(zip(found["rule_name"], found["row_id"])) == [("issuer_name_printed", "f")]
    assert {("units_printed", "w"), ("preferred_printed", "h")} <= set(
        (r.rule_name, r.row_id) for r in tested.itertuples())  # tested, but not findings
    assert {"units_scale_unclear", "preferred_heading_only"} <= set(info["kind"])
    assert set(tested["rule_name"]) <= set(cr.LEDGER_NAMES.values()) and not blind.empty


# ---------------------------------------------------------------- check repairs, owner ruling 2026-11-10

def test_issuer_whitespace_only_joins_are_informational():
    # rf26c Penn TRGRP 2024-03-31 / 2024-09-30 (a <br/> or block div inside the company cell) and rfabf
    # Mykaarma 2023-12-31 (two spans): the reader joined the words; the published name is the printed one
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "penn", "issuer_name": "Penn TRGRP Holdings LLC",
         "printed_row": "Penn TRGRP HoldingsLLC (2) | First Lien Senior Secured Term Loan | Diversified Financial Services | "
                        "SOFR + 7.750% | 13.059 | % | 06/2028 | 9,900"},
        {"row_id": "penn_q3", "issuer_name": "Penn TRGRP Holdings LLC",
         "printed_row": "Penn TRGRP HoldingsLLC(2) | First Lien Senior Secured Term Loan | Diversified Financial Services | "
                        "SOFR + 7.750 | % | 12.354 | %"},
        {"row_id": "myk", "issuer_name": "Mykaarma Acquisition LLC", "pik_rate": 3.75,
         "printed_row": "Mykaarma AcquisitionLLC(2) (6) | Software & Tech Services | Revolver | 8.38% (S + 3.00%; 3.75% PIK; "
                        "1.00% Floor) | 03/21/2028 | 100"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"penn": "whitespace_only", "penn_q3": "whitespace_only",
                                                     "myk": "whitespace_only"}
    con = duckdb.connect()
    frame = pd.DataFrame([{"row_id": "penn", "issuer_name": "Penn TRGRP Holdings LLC",
                           "printed_row": "Penn TRGRP HoldingsLLC (2) | First Lien Senior Secured Term Loan | 9,900"}])
    frame["cik"], frame["report_date"], frame["accession_number"] = "0000000001", "2024-03-31", "a"
    cr.prepare(con, frame)
    tested, info, _ = cr.ledger_rows(con)
    names = tested[tested["rule_name"] == "issuer_name_printed"]
    assert list(names["finding"]) == [0.0] and "whitespace_only" in set(info["kind"])


def test_issuer_whitespace_rule_still_flags_real_differences():
    out = _run(cr.issuer_name_differs_from_page, [
        # a letter differs as well as the space
        {"row_id": "letter", "issuer_name": "Penn TRGRP Holdings LLC",
         "printed_row": "Penn TRGRP HoldingLLC (2) | First Lien Senior Secured Term Loan | 9,900"},
        # the joined name runs on into another word: 'Acme Fund' is not the printed 'AcmeFund2 Holdings'
        {"row_id": "runon", "issuer_name": "Acme Fund",
         "printed_row": "AcmeFund2 Holdings | First Lien Senior Secured Term Loan | 9,900"},
        # a different company on the row
        {"row_id": "other", "issuer_name": "Mykaarma Acquisition LLC",
         "printed_row": "Zendesk, Inc.(2) (6) | Software & Tech Services | Revolver | 6.25% | 100"},
        # rg2 (0001742313) 2023-03-31: the build spelt the letters apart; the page prints 'LVF', 'MCP', 'LLC'
        {"row_id": "lvf", "issuer_name": "L V F Holdings, Inc.",
         "printed_row": "LVF Holdings, Inc. (~) | SF | 6.40 | % | 11.30 | % | 6/10/2021"},
        {"row_id": "mcp", "issuer_name": "M C P Shaw Acquisitionco, L L C",
         "printed_row": "MCP Shaw Acquisitionco, LLC (~~) (~~~) | SF | 6.00 | % | 11.16 | %"},
        # bpxh (0001902649) 2025-06-30: the published name lost its closing bracket
        {"row_id": "cut", "issuer_name": "WH Borrower, LLC (WHP",
         "printed_row": "WH Borrower, LLC (WHP) | First Lien Term Loan | SOFR(Q) | 0.50 | % | 4.75 | %"},
        # mfxi (0001278752) 2024-09-30: the page prints a space the published name lacks; a reader join
        # cannot add a space, so this is a spelling difference and stays a finding
        {"row_id": "garda", "issuer_name": "GardaWorld Security Corporation",
         "printed_row": "Garda World Security Corporation | First Lien Secured Debt - Term Loan | SOFR+350 | 1,000"},
    ])
    kinds = dict(zip(out["row_id"], out["kind"]))
    assert set(kinds) == {"letter", "runon", "other", "lvf", "mcp", "cut", "garda"}
    assert kinds["other"] == "not_the_printed_name"
    assert not ({"whitespace_only"} & set(kinds.values()))
    assert set(kinds.values()) <= cr.FINDING_KINDS["issuer_name_differs_from_page"]


def test_issuer_dash_cell_is_not_a_name_and_cash_heading_is_the_name():
    out = _run(cr.issuer_name_differs_from_page, [
        # rfovb (Overland) 2024-12-31: the em dash after the bill was read as its name cell
        {"row_id": "tb_dash", "issuer_name": "U.S. Treasury Bill", "extracted_industry": "U.S. Treasury Bill",
         "asset_category": "CASH", "index_classification": "CASH", "report_date": "2024-12-31",
         "printed_row": "U.S. Treasury Bill | — | 4.27% | 5/1/2025 | 137,000 | $ | 135,140 | $ | 135,117 | 31.49 | %"},
        # 2025-06-30: no printed row joined; the name is the heading the fund prints over its cash rows
        {"row_id": "tb_none", "issuer_name": "U.S. Treasury Bill", "asset_category": "CASH", "index_classification": "CASH",
         "report_date": "2025-06-30"},
    ])
    assert out.empty, out[["row_id", "kind"]]


def test_issuer_cash_heading_exemption_false_positives():
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "tb_head", "issuer_name": "U.S. Treasury Bill", "extracted_industry": "U.S. Treasury Bill",
         "asset_category": "CASH", "index_classification": "CASH",
         "printed_row": "U.S. Treasury Bill | — | 4.27% | 5/1/2025 | 137,000"},
        # a loan named after the fund's cash heading is still an industry label as a name
        {"row_id": "loan", "issuer_name": "U.S. Treasury Bill", "asset_category": "LOAN"},
        # a cash row named after a GICS label still flags
        {"row_id": "gics", "issuer_name": "Health Care Equipment", "extracted_industry": "Health Care Equipment",
         "asset_category": "CASH", "index_classification": "CASH"},
        # a cash row named with a section word still flags
        {"row_id": "sect", "issuer_name": "Cash Equivalents", "asset_category": "CASH", "index_classification": "CASH"},
        # a dash cell does not hide a different printed company
        {"row_id": "dash_other", "issuer_name": "Acme Holdings LLC",
         "printed_row": "Zenith Partners LLC | – | First Lien | 9,900"},
    ])
    kinds = dict(zip(out["row_id"], out["kind"]))
    assert kinds == {"loan": "equals_industry_label", "gics": "equals_industry_label",
                     "sect": "begins_with_section_word", "dash_other": "not_the_printed_name"}


def _pik_convention(rows, funds=("0001885968",), exclusions=()):
    con = duckdb.connect()
    frame = pd.DataFrame(rows)
    for col, default in (("cik", "0001885968"), ("report_date", "2025-09-30"), ("accession_number", "a1")):
        if col not in frame:
            frame[col] = default
        frame[col] = frame[col].fillna(default)
    cr.prepare(con, frame)
    return cr.pik_printed_not_published(con, whole_coupon_funds=set(funds), whole_coupon_exclusions=set(exclusions))


def test_pik_whole_coupon_convention_without_benchmark_passes():
    # rftsc Continental Battery 2025-09-30 (D-232): opted-in fund, no benchmark printed on the line
    out = _pik_convention([
        {"row_id": "cont", "pik_rate": 11.29, "printed_row": "Continental Battery Company | (5) (11) (12) (13) | First Lien Debt | "
                                                             "7.00% PIK | 11.29% | 07/20/2028 | 6,473 | 6,415 | 1,992 | 0.1"},
        # the margin still passes
        {"row_id": "margin", "pik_rate": 7.0, "printed_row": "Continental Battery Company | First Lien Debt | 7.00% PIK | 11.29%"},
        # a row the build marked as whole coupon, in a fund that is not opted in
        {"row_id": "marked", "cik": "0000000009", "pik_rate": 11.29, "src_transforms": "pik_rate:whole_coupon_printed",
         "printed_row": "Acme | First Lien Debt | 7.00% PIK | 11.29% | 1,000"},
    ])
    assert out.empty, out[["row_id", "kind", "printed"]]


def test_pik_whole_coupon_convention_false_positives():
    out = _pik_convention([
        # outside the convention: today's comparison (the same line flags)
        {"row_id": "not_opted", "cik": "0000000009", "pik_rate": 11.29,
         "printed_row": "Continental Battery Company | First Lien Debt | 7.00% PIK | 11.29% | 07/20/2028"},
        # a row the fund lists as "not ACCESSION CONTEXT": left on today's comparison
        {"row_id": "excluded", "pik_rate": 11.29, "src_context_id": "c-9", "accession_number": "acc-9",
         "printed_row": "Continental Battery Company | First Lien Debt | 7.00% PIK | 11.29% | 07/20/2028"},
        # opted in, pik_rate equal to neither the margin nor the coupon
        {"row_id": "neither", "pik_rate": 9.5,
         "printed_row": "Continental Battery Company | First Lien Debt | 7.00% PIK | 11.29% | 07/20/2028"},
        # opted in, pik_rate equal to a printed percent below the PIK figure (a floor)
        {"row_id": "floor", "pik_rate": 1.0,
         "printed_row": "Acme | First Lien Debt | 7.00% PIK, 1.00% Floor | 11.29% | 1,000"},
        # opted in, pik_rate a percent far above the margin (a 23-point benchmark is not a coupon reading)
        {"row_id": "far", "pik_rate": 30.0, "printed_row": "Acme | First Lien Debt | 7.00% PIK | 30.00% | 1,000"},
        # opted in, floating PIK leg with a fixed cash leg: the whole rate is not all PIK (D-218)
        {"row_id": "leg", "pik_rate": 12.3, "printed_row": "VardimanBlack Holdings, LLC - Term Loan | SOFR + 2.00% PIK + 5.00% | "
                                                           "12.30% | 3/18/2027"},
    ], exclusions=(("0001885968", "acc-9", "c-9"),))
    assert dict(zip(out["row_id"], out["kind"])) == {k: "pik_value_mismatch" for k in (
        "not_opted", "excluded", "neither", "floor", "far", "leg")}


# ---------------------------------------------------------------- check repairs, D-263 (2026-11-13)

def test_issuer_investment_company_legal_name_is_not_a_section_word():
    # REQ-NBAP-1, Apollo Debt Solutions 2023-03-31 .. 2026-06-30: the page prints the company
    # 'Investment Company 24 Bidco Limited' over its block; the tranche lines start with the instrument
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "ic24", "issuer_name": "Investment Company 24 Bidco Limited",
         "printed_row": "First Lien Secured Debt | E+575, 0.00% Floor | 7/11/2029 | EUR | 5,406 | 4,646 | 4,976 | (3)(4)"},
        {"row_id": "ic24_dd", "issuer_name": "Investment Company 24 Bidco Limited"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"ic24": "investment_company_name", "ic24_dd": "investment_company_name"}
    con = duckdb.connect()
    frame = pd.DataFrame([{"row_id": "ic24", "issuer_name": "Investment Company 24 Bidco Limited",
                           "printed_row": "First Lien Secured Debt | E+575, 0.00% Floor | 7/11/2029 | 4,976"},
                          {"row_id": "ok", "issuer_name": "Zendesk, Inc.",
                           "printed_row": "Zendesk, Inc. | First Lien Secured Debt | S+650 | 9,000"}])
    frame["cik"], frame["report_date"], frame["accession_number"] = "0001837532", "2023-03-31", "a"
    cr.prepare(con, frame)
    tested, info, _ = cr.ledger_rows(con)
    names = tested[tested["rule_name"] == "issuer_name_printed"]
    assert list(names["finding"]) == [0.0, 0.0] and "investment_company_name" in set(info["kind"])


def test_issuer_investment_company_repair_still_flags_section_words():
    out = _run(cr.issuer_name_differs_from_page, [
        # a section heading left in front of a company still flags
        {"row_id": "inv", "issuer_name": "Investments Acme Holdings LLC"},
        {"row_id": "nc", "issuer_name": "Non-Controlled Acme Holdings LLC"},
        {"row_id": "fl", "issuer_name": "First Lien Acme Holdings LLC"},
        # 'Investment Company' with no legal form is not a legal name
        {"row_id": "bare", "issuer_name": "Investment Company 24 Bidco"},
        # a category path after the words still flags as one
        {"row_id": "path", "issuer_name": "Investment Company - Debt Investments Acme LLC"},
        # a comparable row is still compared with the page
        {"row_id": "page", "issuer_name": "Investment Company 24 Bidco Limited",
         "printed_row": "Version 1 Bidco Limited | First Lien Secured Debt | E+575 | 4,976"},
    ])
    kinds = dict(zip(out["row_id"], out["kind"]))
    assert kinds == {"inv": "begins_with_section_word", "nc": "begins_with_section_word", "fl": "begins_with_section_word",
                     "bare": "begins_with_section_word", "path": "holds_category_path", "page": "not_the_printed_name"}
    assert set(kinds.values()) <= cr.FINDING_KINDS["issuer_name_differs_from_page"]


_OTG = "OTG Concessions Management, LLC and Octa Parent Holdings, LLC"
_AHR = "AHR Funding Holdings, Inc. and AHR Parent Holdings, LP"
_END = "Endeavor Bidco LLC and Endeavor TopCo, Inc."


def _ares_group_rows():
    # Ares Capital 2024-09-30 (company | business description | investment | ...): the first line of each
    # group prints the company; later lines leave the company (and sometimes the description) blank
    rows = [
        {"row_id": "otg1", "issuer_name": _OTG, "bdc_investment_identifier": f"{_OTG}, Second lien notes",
         "printed_row": f"{_OTG} | Airport restaurant operator | Second lien notes | 10.00% PIK | 02/2024 | 02/2031 | 8.0 | 7.2 | (2)"},
        {"row_id": "otg2", "issuer_name": _OTG, "bdc_investment_identifier": f"{_OTG}, Participation rights",
         "printed_row": "Participation rights | 02/2024 | 02/2054 | 1 | - | - | (2)"},
        {"row_id": "ahr1", "issuer_name": _AHR, "bdc_investment_identifier": f"{_AHR}, Series A preferred shares",
         "printed_row": f"{_AHR} | Provider of revenue cycle management solutions to hospitals | Series A preferred shares | 12.75% PIK | 46.2"},
        {"row_id": "ahr2", "issuer_name": _AHR, "bdc_investment_identifier": f"{_AHR}, Preferred units",
         "printed_row": "Provider of Revenue Cycle Management solutions to hospitals | Preferred units | 8.00% PIK | 07/2022 | 9,900 | 12.2 | (2)"},
        {"row_id": "end1", "issuer_name": _END, "bdc_investment_identifier": f"{_END}, First lien senior secured loan",
         "printed_row": f"{_END} | Global securities finance trading platform | First lien senior secured loan | 9.38% | SOFR (Q) | 6.0"},
        {"row_id": "end2", "issuer_name": _END, "bdc_investment_identifier": f"{_END}, Class A common units",
         "printed_row": "Trading platform for securities finance | Class A common units | 08/2024 | 1,859 | 1.9 | 1.9"},
    ]
    return [{"accession_number": "a1", **r} for r in rows]


def test_issuer_continuation_lines_are_informational():
    # REQ-NBAR-1 (Ares) and REQ-NBAS-1 (Ares Strategic Income: company | investment | ..., member ordinal)
    out = _run(cr.issuer_name_differs_from_page, _ares_group_rows() + [
        {"row_id": "caif1", "issuer_name": "CAIF 1", "accession_number": "a2",
         "bdc_investment_identifier": "CAIF 1 | Commercial mortgage-backed security 1",
         "printed_row": "CAIF 1 | Commercial mortgage-backed security | 9.50% | SONIA (Q) | 5.75% | 08/2035 | 26,145.2 | (6)(13)"},
        {"row_id": "caif2", "issuer_name": "CAIF 1", "accession_number": "a2",
         "bdc_investment_identifier": "CAIF 1 | Commercial mortgage-backed security 2",
         "printed_row": "Commercial mortgage-backed security | 10.90% | SONIA (Q) | 7.15% | 08/2035 | 13,182.1 | (6)(13)"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"otg2": "continuation_line", "ahr2": "continuation_line",
                                                     "end2": "continuation_line", "caif2": "continuation_line"}
    con = duckdb.connect()
    frame = pd.DataFrame(_ares_group_rows())
    frame["cik"], frame["report_date"], frame["accession_number"] = "0001287750", "2024-09-30", "a"
    cr.prepare(con, frame)
    tested, info, _ = cr.ledger_rows(con)
    names = tested[tested["rule_name"] == "issuer_name_printed"]
    assert names["finding"].sum() == 0 and "continuation_line" in set(info["kind"])


def test_issuer_continuation_repair_still_flags_a_different_company():
    rows = _ares_group_rows()
    out = _run(cr.issuer_name_differs_from_page, rows + [
        # a different company printed in full (company | description | instrument): same cell as the first line
        {"row_id": "other_full", "accession_number": "a1", "issuer_name": _OTG, "bdc_investment_identifier": f"{_OTG}, Class A units",
         "printed_row": "Wildcat Parent LP | Airport restaurant operator | Class A units | 06/2022 | 41,000 | 6.7"},
        # a lead cell that is another issuer the fund publishes, on a short line
        {"row_id": "other_issuer", "accession_number": "a1", "issuer_name": _OTG, "bdc_investment_identifier": f"{_OTG}, Common units",
         "printed_row": f"{_END} | Common units | 06/2022 | 41,000 | 6.7"},
        # no line of the filing prints the company: nothing to continue
        {"row_id": "orphan", "accession_number": "a1", "issuer_name": "Acme Holdings LLC", "bdc_investment_identifier": "Acme Holdings LLC, Preferred units",
         "printed_row": "Provider of widgets | Preferred units | 8.00% PIK | 9,900 | 12.2"},
        # the group's first line is in another filing
        {"row_id": "other_filing", "issuer_name": _OTG, "accession_number": "a9",
         "bdc_investment_identifier": f"{_OTG}, Participation rights",
         "printed_row": "Participation rights | 02/2024 | 02/2054 | 1 | - | - | (2)"},
        # the member does not name the published issuer
        {"row_id": "member", "accession_number": "a1", "issuer_name": _OTG, "bdc_investment_identifier": "Octa Parent Holdings, LLC, Participation rights",
         "printed_row": "Participation rights | 02/2024 | 02/2054 | 1 | - | - | (2)"},
    ])
    kinds = dict(zip(out["row_id"], out["kind"]))
    found = {k: v for k, v in kinds.items() if v in cr.FINDING_KINDS["issuer_name_differs_from_page"]}
    assert found == {k: "not_the_printed_name" for k in ("other_full", "other_issuer", "orphan", "other_filing", "member")}
    assert {kinds[k] for k in ("otg2", "ahr2", "end2")} == {"continuation_line"}


def test_issuer_reordered_co_obligors_are_informational():
    # REQ-NBAR-1 reorderings: Ares 2025-12-31 Mustang / Senske and Steward Partners
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "mustang",
         "issuer_name": "Mustang Prospects Holdco, LLC, Mustang Prospects Purchaser, LLC and Senske Acquisition, Inc.",
         "printed_row": "Mustang Prospects Purchaser, LLC, Senske Acquisition, Inc., and Mustang Prospects Holdco, LLC (13) | "
                        "Provider of lawn care | First lien senior secured loan | 9.17% | SOFR (Q) | 0.3"},
        {"row_id": "steward",
         "issuer_name": "Steward Partners Global Advisory, LLC, Steward Partners Intermediate II, LLC, Steward Partners "
                        "Investment Advisory, LLC, and Steward Partners New Holdings, LLC",
         "printed_row": "Steward Partners Global Advisory, LLC, Steward Partners Investment Advisory, LLC, Steward Partners "
                        "Intermediate II, LLC, and Steward Partners New Holdings, LLC (13) | Wealth management | First lien | 4.9"},
    ])
    assert dict(zip(out["row_id"], out["kind"])) == {"mustang": "reordered_co_obligors", "steward": "reordered_co_obligors"}


def test_issuer_reorder_repair_still_flags_different_co_obligors():
    out = _run(cr.issuer_name_differs_from_page, [
        # a co-obligor dropped from the published name (Ares Steward 2025-12-31)
        {"row_id": "dropped", "issuer_name": "Steward Partners Global Advisory, LLC and Steward Partners Investment Advisory, LLC",
         "printed_row": "Steward Partners Global Advisory, LLC, Steward Partners Investment Advisory, LLC, Steward Partners "
                        "Intermediate II, LLC and Steward Partners New Holdings, LLC (13) | Wealth management | First lien | 6.9"},
        # a co-obligor spelt differently (Ares Truck-Lite: 'Clarience Technologies, LLC' / 'Clarity Technologies Holdings, LP')
        {"row_id": "spelt", "issuer_name": "Truck-Lite Co., LLC, ECCO Holdings Corp. and Clarience Technologies, LLC",
         "printed_row": "Clarity Technologies Holdings, LP, Truck-Lite Co., LLC and ECCO Holdings Corp. (13) | "
                        "Provider of safety products | First lien | 0.0"},
        # words swapped between co-obligors are not a reordering
        {"row_id": "swapped", "issuer_name": "Acme Holdings LLC and Beta Partners LLC",
         "printed_row": "Beta Holdings LLC and Acme Partners LLC | Software | First lien | 1.0"},
        # a single name is never a reordering
        {"row_id": "single", "issuer_name": "Holdings Acme LLC",
         "printed_row": "Acme Holdings LLC | Software | First lien | 1.0"},
        # 'and' for the printed '&' in the same order is not a reordering (0001572694 2024-03-31, first measurement)
        {"row_id": "amp", "issuer_name": "HS4 AcquisitionCo, Inc. (dba HotSchedules and Fourth)",
         "printed_row": "HS4 AcquisitionCo, Inc. (dba HotSchedules & Fourth) | Hotels, Restaurants & Leisure | 11.18% | 3,129"},
    ])
    kinds = dict(zip(out["row_id"], out["kind"]))
    assert kinds == {k: "not_the_printed_name" for k in ("dropped", "spelt", "swapped", "single", "amp")}
