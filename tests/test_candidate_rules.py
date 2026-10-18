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
    out = _run(cr.issuer_name_differs_from_page, [
        {"row_id": "ct", "issuer_name": "Circus Trix Holdings LLC",
         "printed_row": "CircusTrix Holdings LLC | First Lien Secured Debt | SOFR+675, 1.00% Floor | 07/18/28 | 4,000"},
    ])
    assert list(out["kind"]) == ["spacing_only"]


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
    # read-only evidence scripts (scripts/v05_evidence/, e.g. the measurement and review scripts) may import it
    users = [p for root in ("pipeline", "scripts") for p in (repo / root).rglob("*.py")
             if imports.search(p.read_text(encoding="utf-8", errors="ignore"))
             and p.name != "candidate_rules.py" and "v05_evidence" not in p.parts]
    assert users == [], users


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
