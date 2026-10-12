"""Industry read from the filer's printed heading (owner ruling 2026-10-11), not guessed from the company name."""
import re

import pandas as pd

from pipeline import unified_holdings as uh
from pipeline.bdc_xbrl_html_bridge import _NOT_AN_INDUSTRY_RE, apply_ixbrl_field_status_overlay


def _holdings(rows):
    frame = pd.DataFrame(rows)
    for column, default in (("source", "bdc"), ("index_classification", "DIRECT_LENDING")):
        if column not in frame:
            frame[column] = default
    return frame


def test_the_filers_industry_replaces_the_name_keyed_label_where_it_maps(monkeypatch):
    monkeypatch.setattr(uh, "printed_industry_gics", lambda labels: {"Software": ("Application Software", "alias")})
    out = uh._apply_printed_industry(_holdings([
        {"extracted_industry": "Software", "gics_sub_industry": "Advertising"},
        {"extracted_industry": "Services: Unknown", "gics_sub_industry": "Advertising"},
        {"extracted_industry": "", "gics_sub_industry": "Food Retail"}]))
    assert out["gics_sub_industry"].tolist() == ["Application Software", "Advertising", "Food Retail"]


def test_cash_rows_and_other_sources_are_left_alone(monkeypatch):
    monkeypatch.setattr(uh, "printed_industry_gics", lambda labels: {"Software": ("Application Software", "alias")})
    out = uh._apply_printed_industry(_holdings([
        {"extracted_industry": "Software", "gics_sub_industry": "", "index_classification": "CASH"},
        {"extracted_industry": "Software", "gics_sub_industry": "", "source": "nport"}]))
    assert out["gics_sub_industry"].tolist() == ["", ""]


def test_a_gics_name_maps_to_itself_and_an_unknown_label_maps_to_nothing(monkeypatch):
    from pipeline import gics_mapping
    monkeypatch.setattr(gics_mapping, "_load_cache", lambda: {})
    mapping = uh.printed_industry_gics(["Application Software", "Zzz Not An Industry", ""])
    assert mapping["Application Software"][0] == "Application Software"
    assert "Zzz Not An Industry" not in mapping and "" not in mapping


def test_headings_that_are_not_industries_are_recognised():
    pattern = re.compile(_NOT_AN_INDUSTRY_RE)
    for heading in ("Non-controlled/non-affiliated - debt commitments", "Unfunded", "Interest", "Cash and Cash Equivalents",
                    "Non-controlled affiliate company investment:", "Total Investments", "First Lien Debt", "None"):
        assert pattern.search(heading), heading
    for heading in ("Software", "Services: Business", "Investment Funds & Vehicles", "Banking, Finance, Insurance & Real Estate",
                    "Health Care Equipment & Supplies", "Real Estate Investment Trusts"):
        assert not pattern.search(heading), heading


def test_the_printed_heading_fills_a_blank_industry_only():
    staged = pd.DataFrame({
        "cik": ["0000000001"] * 3, "accession_number": ["A"] * 3, "report_date": ["2026-03-31"] * 3,
        "bdc_investment_identifier": ["Acme, Term Loan", "Beta, Term Loan", "Gamma, Revolver"],
        "bdc_dimensions_raw": ["investmentidentifieraxis=Acme, Term Loan", "investmentidentifieraxis=Beta, Term Loan",
                               "investmentidentifieraxis=Gamma, Revolver"],
        "extracted_industry": ["", "Chemicals", ""], "maturity_date": [""] * 3, "reference_rate_type": [""] * 3,
        "lien_position": [""] * 3})
    status = pd.DataFrame({
        "cik": ["0000000001"] * 3, "accession_number": ["A"] * 3, "report_date": ["2026-03-31"] * 3,
        "raw_id_lower": ["acme, term loan", "beta, term loan", "gamma, revolver"],
        "maturity_date": [""] * 3, "maturity_status": ["blank"] * 3, "reference_rate_type": [""] * 3,
        "reference_rate_status": ["blank"] * 3, "lien_position": [""] * 3, "lien_status": ["blank"] * 3,
        "gics_sector": ["Software", "Machinery", "Unfunded"], "sector_status": ["value", "value", "value"]})
    out = apply_ixbrl_field_status_overlay(staged, status)
    assert out["extracted_industry"].tolist() == ["Software", "Chemicals", ""]
