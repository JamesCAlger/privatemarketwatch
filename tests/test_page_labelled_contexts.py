"""Positions tagged on a subtotal context and named from the page; twin members; unnamed labels."""
import pandas as pd
import pytest

from pipeline import page_labelled_contexts as plc
from pipeline import staging_bdc


def _row(context, cells, concept='us-gaap:InvestmentOwnedAtFairValue'):
    tds = ''.join('<td style="x">%s</td>' % cell for cell in cells[:-1])
    tds += '<td><ix:nonFraction name="%s" contextRef="%s" scale="3">%s</ix:nonFraction></td>' % (concept, context, cells[-1])
    return '<tr class="r">' + tds + '</tr>'


def test_single_row_group_is_named_from_its_printed_row():
    page = _row('c-283', ['Star Holding, LLC<sup>@#(8)(26)</sup>', 'Senior secured', 'SF +', '4.50', '17,079', '16,939', '17,104'])
    assert plc.labelled_contexts(page, {'c-283'}) == {'c-283': 'Star Holding, LLC | Senior secured'}


def test_subtotal_and_total_rows_are_not_positions():
    page = (_row('c-118', ['161,373', '160,771', '3.5', '158,632'])
            + _row('c-119', ['Total equity investments', '61,047', '1.5', '64,837'])
            + _row('c-120', ['Southeast', '$', '1,892,252']))
    assert plc.labelled_contexts(page, {'c-118', 'c-119', 'c-120'}) == {}


def test_context_printed_on_two_rows_or_tagged_with_another_concept_is_left_alone():
    page = (_row('c-1', ['Acme, Inc.', 'One stop', '100'])
            + _row('c-1', ['Beta, LLC', 'One stop', '100'])
            + _row('c-2', ['Gamma, LLC', 'One stop', '5'], concept='us-gaap:InvestmentOwnedAtCost')
            + _row('c-9', ['Delta, LLC', 'One stop', '7']))
    assert plc.labelled_contexts(page, {'c-1', 'c-2'}) == {}


def test_only_a_listed_axis_combination_is_adopted(monkeypatch, tmp_path):
    combo = frozenset({'equitysecuritiesbyindustryaxis', 'investmenttypeaxis'})
    monkeypatch.setattr(plc, '_combos_by_cik', lambda: {'0000000042': frozenset({combo})})
    (tmp_path / '42').mkdir()
    (tmp_path / '42' / '000000004226000001.html').write_text(
        _row('c-1', ['Acme, Inc.', 'Senior secured', '10']) + _row('c-2', ['Northeast', 'Region', '10']), encoding='utf-8')
    contexts = {
        'c-1': {'is_investment': False, 'investment_identifier': '',
                'dimensions_raw': 'equitysecuritiesbyindustryaxis=SoftwareMember|investmenttypeaxis=SeniorMember'},
        'c-2': {'is_investment': False, 'investment_identifier': '', 'dimensions_raw': 'statementgeographicalaxis=NortheastMember'},
    }
    meta = {'cik': '42', 'accession_number': '0000000042-26-000001'}
    assert plc.adopt_page_labelled_contexts(contexts, meta, html_cache_dir=tmp_path) == 1
    assert contexts['c-1']['is_investment'] and contexts['c-1']['investment_identifier'] == 'Acme, Inc. | Senior secured'
    assert not contexts['c-2']['is_investment']
    assert plc.adopt_page_labelled_contexts(dict(contexts), {'cik': '43', 'accession_number': 'x'}, html_cache_dir=tmp_path) == 0


def _raw(rows):
    columns = ('cik entity_name accession_number form_type filing_date report_date '
               'investment_identifier fair_value cost principal_amount interest_rate '
               'basis_spread reference_rate_type maturity_date pct_of_net_assets pik_rate '
               'shares_held unrealized_gain_loss dimensions_raw investment_type industry affiliation').split()
    return pd.DataFrame([{**dict.fromkeys(columns, ''), **row} for row in rows])


@pytest.fixture
def no_production_overlay(monkeypatch, tmp_path):
    monkeypatch.setattr('pipeline.config.BDC_IXBRL_FIELD_STATUS_FILE', tmp_path / 'absent.csv')


def test_goldman_equal_valued_twin_members_are_both_kept(no_production_overlay):
    base = ('Investment Debt Investments United States 1st Lien/Senior Secured Debt Airwavz Solutions, Inc. Industry Wireless '
            'Telecommunication Services Interest Rate 9.07% Reference Rate and Spread S + 5.25% Maturity 03/31/27')
    rows = [dict(cik='0001920145', report_date='2025-12-31', accession_number='a', investment_identifier=base + suffix,
                 dimensions_raw='investmentidentifieraxis=' + base + suffix, fair_value='5759000', cost='5778000',
                 principal_amount='5817000', interest_rate='0.0907', src_context_id='twin' + suffix.strip())
            for suffix in (' One', ' Two')]
    # Control: the same member under two affiliation paths is still one position.
    other = base.replace('Airwavz Solutions, Inc.', 'Other Borrower, Inc.')
    for path in ('nonaffiliated', 'affiliated'):
        rows.append(dict(cik='0001920145', report_date='2025-12-31', accession_number='a', investment_identifier=other,
                         dimensions_raw='investmentidentifieraxis=' + other + '|investmentissueraffiliationaxis=' + path,
                         fair_value='100000', cost='100000', principal_amount='100000', interest_rate='0.0907',
                         src_context_id='same' + path))
    result = staging_bdc._prepare_bdc(bdc_df=_raw(rows))
    assert sorted(c for c in result.src_context_id if c.startswith('twin')) == ['twinOne', 'twinTwo']
    assert sum(c.startswith('same') for c in result.src_context_id) == 1


def test_sixth_street_unnamed_equity_label_takes_the_issuer_printed_on_the_page(no_production_overlay):
    label = 'Equity and Other Investments Healthcare 128,321 Ordinary Shares Initial Acquisition Date 3/24/2023'
    rows = [dict(cik='0001925309', report_date='2023-12-31', accession_number='a', investment_identifier=label,
                 dimensions_raw='investmentidentifieraxis=' + label, fair_value='12875000', cost='12875000',
                 shares_held='128321', src_context_id='raptor')]
    result = staging_bdc._prepare_bdc(bdc_df=_raw(rows)).set_index('src_context_id')
    assert result.loc['raptor', 'issuer_name'] == 'Raptor US Buyer II Corp.'
    assert result.loc['raptor', 'fair_value'] == 12875000


def test_a_listed_misdated_context_is_redated_and_a_stale_listing_is_left_alone(monkeypatch):
    listing = {('0000000042', '0000000042-25-000030'): {'c-285': ('2024-12-31', '2025-03-31'),
                                                         'c-9': ('2024-12-31', '2025-03-31')}}
    monkeypatch.setattr(plc, '_misdated_by_accession', lambda: listing)
    contexts = {'c-285': {'period': '2024-12-31'}, 'c-286': {'period': '2024-12-31'}, 'c-9': {'period': '2025-03-31'}}
    meta = {'cik': '42', 'accession_number': '0000000042-25-000030'}
    assert plc.correct_misdated_contexts(contexts, meta) == 1
    assert contexts['c-285']['period'] == '2025-03-31'
    assert contexts['c-286']['period'] == '2024-12-31'
    assert contexts['c-9']['period'] == '2025-03-31'
    other = {'c-285': {'period': '2024-12-31'}}
    assert plc.correct_misdated_contexts(other, {'cik': '42', 'accession_number': '0000000042-25-000031'}) == 0
    assert other['c-285']['period'] == '2024-12-31'


class TestUntaggedValues:
    """A value the filer printed and did not tag, declared in the wrapper."""

    DECLARED = {("0001925309", "0000950170-25-021144"): {"C_1": {"fair_value": 49063000.0}}}

    def _declare(self, monkeypatch):
        monkeypatch.setattr(plc, "_untagged_by_accession", lambda: self.DECLARED)
        return {"cik": "1925309", "accession_number": "0000950170-25-021144"}

    def test_fills_a_missing_value_only(self, monkeypatch):
        meta = self._declare(monkeypatch)
        facts = {"C_1": {"cost": 49063000.0}}
        assert plc.fill_untagged_values(facts, meta) == 1
        assert facts["C_1"]["fair_value"] == 49063000.0

    def test_never_replaces_a_tagged_value(self, monkeypatch):
        meta = self._declare(monkeypatch)
        facts = {"C_1": {"cost": 49063000.0, "fair_value": 48000000.0}}
        assert plc.fill_untagged_values(facts, meta) == 0
        assert facts["C_1"]["fair_value"] == 48000000.0

    def test_leaves_other_filings_and_empty_contexts_alone(self, monkeypatch):
        meta = self._declare(monkeypatch)
        assert plc.fill_untagged_values({"C_1": {}}, meta) == 0
        assert plc.fill_untagged_values({"C_1": {"cost": 1.0}}, {"cik": "1925309", "accession_number": "other"}) == 0

    def test_the_declared_value_can_be_looked_up_for_reverification(self, monkeypatch):
        self._declare(monkeypatch)
        assert plc.untagged_value("1925309", "0000950170-25-021144", "C_1", "fair_value") == 49063000.0
        assert plc.untagged_value("1925309", "0000950170-25-021144", "C_1", "cost") is None
        assert plc.untagged_value("1925309", "0000950170-25-021144", "C_2", "fair_value") is None
        assert plc.untagged_value("1803498", "0000950170-25-021144", "C_1", "fair_value") is None


class TestDeclaredContextIdentifiers:
    """A wrapper names a position context the filer left without an identifier member."""

    DECLARED = {("0001588272", "0001193125-25-180608"): {"P_Bio": "Common Stocks | Bioplastics | PlantSwitch, Inc. (Series A-2)"}}

    def _declare(self, monkeypatch):
        monkeypatch.setattr(plc, "_named_by_accession", lambda: self.DECLARED)
        return {"cik": "1588272", "accession_number": "0001193125-25-180608"}

    def test_names_an_unnamed_context(self, monkeypatch):
        meta = self._declare(monkeypatch)
        contexts = {"P_Bio": {"is_investment": False, "dimensions_raw": "x"}, "other": {"is_investment": False}}
        assert plc.name_declared_contexts(contexts, meta) == 1
        assert contexts["P_Bio"]["is_investment"] is True
        assert contexts["P_Bio"]["investment_identifier"] == "Common Stocks | Bioplastics | PlantSwitch, Inc. (Series A-2)"
        assert contexts["other"]["is_investment"] is False

    def test_never_renames_a_context_that_already_names_a_position(self, monkeypatch):
        meta = self._declare(monkeypatch)
        contexts = {"P_Bio": {"is_investment": True, "investment_identifier": "as filed"}}
        assert plc.name_declared_contexts(contexts, meta) == 0
        assert contexts["P_Bio"]["investment_identifier"] == "as filed"

    def test_a_member_the_wrapper_reads_as_a_category_row_takes_the_declared_name(self, monkeypatch):
        import re
        meta = self._declare(monkeypatch)
        monkeypatch.setattr(plc, "_category_marker", lambda cik: re.compile(r"(?i)^\s*(?:First\s+Lien\s+Senior\s+Secured\s+Term\s+Loan)\s*$"))
        bare = {"P_Bio": {"is_investment": True, "investment_identifier": "First Lien Senior Secured Term Loan"}}
        assert plc.name_declared_contexts(bare, meta) == 1
        assert bare["P_Bio"]["investment_identifier"] == "Common Stocks | Bioplastics | PlantSwitch, Inc. (Series A-2)"
        named = {"P_Bio": {"is_investment": True, "investment_identifier": "Acme, First Lien Senior Secured Term Loan"}}
        assert plc.name_declared_contexts(named, meta) == 0
        assert named["P_Bio"]["investment_identifier"] == "Acme, First Lien Senior Secured Term Loan"

    def test_other_filings_and_missing_contexts_are_left_alone(self, monkeypatch):
        meta = self._declare(monkeypatch)
        assert plc.name_declared_contexts({"elsewhere": {"is_investment": False}}, meta) == 0
        other = {"P_Bio": {"is_investment": False}}
        assert plc.name_declared_contexts(other, {"cik": "1588272", "accession_number": "0001193125-25-282550"}) == 0
        assert other["P_Bio"]["is_investment"] is False
