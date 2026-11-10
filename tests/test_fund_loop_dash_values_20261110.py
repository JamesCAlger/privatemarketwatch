"""Fund loop 2026-11-10 (D-252): positions printed with a dash for fair value and no fair-value tag.

Apollo Debt Solutions (0001837532): SK Neptune Husky Group Sarl term loan (par 9,588, cost 9,466 at
2026-03-31, printed fair value '-') and the Material+ PIK term loan were absent from published rows from
2024-12-31. Sixth Street Specialty Lending (0001508655): IntelePeer Series C/D warrants, Murchison preferred
units, TherapeuticsMD warrants and three other equity lines printed '- -' likewise. Each is declared at 0 in
the wrapper's source_encodings.untagged_values.
"""
import json
import re
from pathlib import Path

import pytest

from pipeline import config
from pipeline import page_labelled_contexts as plc

APOLLO, SIXTH = "0001837532", "0001508655"

NEPTUNE = [
    ("0000950170-25-038785", "C_f10a07fe-9bd5-4b74-88da-6353293274b6"),
    ("0000950170-25-068013", "C_1292467d-55ed-481e-ba30-b9b3b539b93b"),
    ("0000950170-25-105984", "C_5feace63-0731-4a6e-a518-59953cabaaa4"),
    ("0001193125-25-277723", "C_5d96d4e1-3715-41c4-a80d-6f3c5a1a0def"),
    ("0001193125-26-102386", "C_669029cd-2fea-4d94-acfa-55a68ae19db5"),
    ("0001193125-26-215667", "C_2c6db995-c495-4af2-8343-4d0bb1e8f01a"),
    ("0001193125-26-341358", "C_aa1312a2-d475-466d-b28e-3251b9a9d051"),
]
SIXTH_OWNER_ROWS = [  # IntelePeer Series D warrants, Murchison preferred units, TherapeuticsMD warrants, 2026-03-31
    ("0001193125-26-206313", "C_51d89782-cff4-4c6f-bbfc-f662476e0ad9"),
    ("0001193125-26-206313", "C_0ecd394e-6e72-4013-be2a-f8a6db3f2e7a"),
    ("0001193125-26-206313", "C_9c447bfe-4044-40bb-a9ff-1fe02740a429"),
    ("0000950170-25-100204", "C_d8979b15-9f41-4932-ae4b-327af1fbda56"),
]


def _declared_zero(cik):
    wrapper = json.loads((config.OVERRIDES_DIR / "bdc_xbrl_wrappers" / (cik + ".json")).read_text(encoding="utf-8"))
    out = []
    for line in wrapper["source_encodings"]["untagged_values"]:
        accession, context, field, value = line.split()[:4]
        if field == "fair_value" and float(value) == 0:
            out.append((accession, context))
    return out


@pytest.mark.parametrize("accession,context", NEPTUNE)
def test_neptune_term_loan_is_declared_at_zero_every_quarter_it_is_printed(accession, context):
    assert plc.untagged_value(APOLLO, accession, context, "fair_value") == 0


@pytest.mark.parametrize("accession,context", SIXTH_OWNER_ROWS)
def test_sixth_street_dash_equity_lines_are_declared_at_zero(accession, context):
    assert plc.untagged_value(SIXTH, accession, context, "fair_value") == 0


def test_a_declared_zero_never_replaces_a_tagged_fair_value():
    accession, context = NEPTUNE[-2]
    facts = {context: {"cost": 9466000.0, "principal_amount": 9588000.0, "fair_value": 1.0}}
    assert plc.fill_untagged_values(facts, {"cik": APOLLO, "accession_number": accession}) == 0
    assert facts[context]["fair_value"] == 1.0


def _row_cells(html_text, context):
    """Cells of each <tr> holding a fact on ``context`` and whether that row tags a fair value there."""
    from lxml import etree
    from pipeline.bdc_xbrl_html_bridge import _ixbrl_local, _row_grid
    root = etree.fromstring(html_text, etree.XMLParser(huge_tree=True, recover=True))
    rows = []
    for tr in root.iter():
        if _ixbrl_local(tr.tag) != "tr":
            continue
        facts = [el for el in tr.iter() if _ixbrl_local(el.tag).lower() == "nonfraction" and el.get("contextRef") == context]
        if facts:
            tagged_fv = any((el.get("name") or "").endswith(":InvestmentOwnedAtFairValue") for el in facts)
            rows.append(([c for c in _row_grid(tr) if c], tagged_fv))
    return rows


DASH = re.compile(r"^[-–—]$")


def _printed_dash_untagged(cik, accession, context):
    path = config.DATA_DIR / "raw" / "filings" / "bdc_html" / cik.lstrip("0") / (accession.replace("-", "") + ".html")
    rows = _row_cells(path.read_bytes(), context)
    return bool(rows) and all(not tagged and any(DASH.match(c) for c in cells) for cells, tagged in rows)


@pytest.mark.needs_cache
@pytest.mark.parametrize("cik", [APOLLO, SIXTH])
def test_every_declared_zero_is_a_printed_dash_with_no_fair_value_tag(cik):
    declared = _declared_zero(cik)
    assert declared
    bad = [d for d in declared if not _printed_dash_untagged(cik, *d)]
    assert not bad, bad


@pytest.mark.needs_cache
def test_a_row_with_a_tagged_fair_value_fails_the_dash_check():
    # Neptune's 2024-09-30 line prints '-' but the filer tagged a fair value of 0 on it: a declaration
    # there would be wrong, and the check must say so.
    assert not _printed_dash_untagged(APOLLO, "0000950170-24-124223", "C_3f21a5b7-3c6f-44d1-8f77-80bd2d6c2b30")
    # Hudson River Trading term loan (2025-12-31 column of the 2026-03-31 10-Q): printed '6,965 6,949 7,003' and tagged; no dash.
    assert not _printed_dash_untagged(APOLLO, "0001193125-26-215667", "C_c30d879e-742d-4b3a-a27d-0a255965dd33")


# --- Apollo printed company column (2026-11-10): group prefixes cut so a corrected quarter keeps its chain ---

def _apollo_strip():
    from pipeline import staging_bdc
    return re.compile(staging_bdc.issuer_name_strip_patterns()[APOLLO])


@pytest.mark.parametrize("name,expected", [
    ("CNSI Acentra Holdings, LLC", "Acentra Holdings, LLC"),
    ("Health Care Health Care Providers & Services CNSI Acentra Holdings, LLC.", "Acentra Holdings, LLC."),
    ("Omega Healthcare OMH-Healthedge Holdings, Inc.", "OMH-Healthedge Holdings, Inc."),
    ("Berry Global Vybond Buyer, LLC", "Vybond Buyer, LLC"),
    ("Bery Global Vybond Buyer, LLC", "Vybond Buyer, LLC"),
    ("Mavis Tire Express Services Mavis Tire Express Services TopCo, L.P.", "Mavis Tire Express Services TopCo, L.P."),
    ("ArcLight AL GCX Holdings, LLC", "AL GCX Holdings, LLC"),
    ("AL GCX Fund VIII AL GCX Fund VIII Holdings LLC", "AL GCX Fund VIII Holdings LLC"),
])
def test_apollo_group_prefix_is_cut(name, expected):
    assert _apollo_strip().sub("", name) == expected


@pytest.mark.parametrize("name", [
    "Acentra Holdings, LLC", "CNSI CNSI Holdings, LLC", "Berry Global, Inc.", "Mavis Tire Express Services Corp.",
    "AL GCX Holdings, LLC", "OMH-Healthedge Holdings, Inc.",
])
def test_apollo_names_without_the_group_prefix_are_left_alone(name):
    assert _apollo_strip().sub("", name) == name


def _apollo_corrections():
    import csv
    with open(config.OVERRIDES_DIR / "row_corrections.csv", encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["cik"] == APOLLO]


@pytest.mark.parametrize("quarter,needle,field,value", [
    # the fair-value tag sits on another company's member; the printed company column names the row
    ("2026-03-31", "Hudson River Trading LLC Investment Type", "issuer_name", "Dragon Buyer Inc"),
    ("2026-03-31", "MRO Parent Corporation Investment Type First Lien Secured Debt - Revolver", "issuer_name",
     "CT Technologies Intermediate Holdings"),
    ("2026-03-31", "Rochester Midland Corporation Investment Type First Lien Secured Debt - Delayed Draw", "issuer_name",
     "Olympus Water US Holding Corporation"),
    ("2026-03-31", "Rochester Midland Corporation Investment Type First Lien Secured Debt - Delayed Draw", "basis_spread", ""),
    ("2026-03-31", "Endeavor Operating Co LLC", "issuer_name", "Delivery Hero Finco LLC"),
    ("2023-03-31", "Embecta Corp. Investment Type", "coupon_type", "Fixed"),
])
def test_apollo_printed_row_corrections_are_recorded(quarter, needle, field, value):
    hits = [r for r in _apollo_corrections() if r["report_date"] == quarter and needle in r["bdc_investment_identifier"]
            and r["field"] == field and r["value"] == value]
    assert hits, (quarter, needle, field, value)


@pytest.mark.parametrize("quarter,par", [("2025-12-31", "152685000"), ("2026-03-31", "152304000")])
def test_cascade_parent_dollar_par_is_published_in_dollars(quarter, par):
    # Tagged U_GBP (2025-12-31) and U_EUR (2026-03-31); the line prints a dollar par with no currency code:
    # 'Cascade Parent Inc. First Lien Secured Debt - Term Loan S+575, 0.50% Floor 9/24/2031 152,685 150,460 150,395'.
    rows = [r for r in _apollo_corrections() if r["report_date"] == quarter
            and "Cascade Parent Inc." in r["bdc_investment_identifier"] and "Term Loan" in r["bdc_investment_identifier"]]
    fields = {r["field"]: r["value"] for r in rows}
    assert fields.get("principal_amount_currency") == "USD"
    assert fields.get("principal_amount_usd") == par
    assert fields.get("principal_fx_status") == "source_usd"


def test_a_printed_foreign_par_keeps_its_currency():
    # SumUp prints 'EUR 40,000': no USD currency correction may exist for it.
    hits = [r for r in _apollo_corrections() if "SumUp" in r["bdc_investment_identifier"]
            and r["field"] == "principal_amount_currency" and r["value"] == "USD"]
    assert not hits
