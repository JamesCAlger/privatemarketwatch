"""Source-shaped controls for the two diagnosed v11b staging failures."""
import pandas as pd
import pytest

from pipeline import accounting_scope, staging_bdc


def raw_rows(rows):
    columns = ('cik entity_name accession_number form_type filing_date report_date '
               'investment_identifier fair_value cost principal_amount interest_rate '
               'basis_spread reference_rate_type maturity_date pct_of_net_assets pik_rate '
               'shares_held unrealized_gain_loss dimensions_raw investment_type industry affiliation').split()
    return pd.DataFrame([{**dict.fromkeys(columns, ''), **row} for row in rows])


@pytest.fixture(autouse=True)
def no_production_overlay(monkeypatch, tmp_path):
    monkeypatch.setattr('pipeline.config.BDC_IXBRL_FIELD_STATUS_FILE', tmp_path / 'absent.csv')


def test_cash_in_named_portfolios_survives_staging_without_erasing_equal_parent_positions():
    cash = 'Dreyfus Government Cash Management - Institutional Shares | Emerald JV LP'
    rows = [dict(cik='0001803498', report_date='2026-03-31', fair_value='11462000',
                 cost='11462000', investment_identifier=cash,
                 dimensions_raw='investmentidentifieraxis=' + cash, src_context_id='cash')]
    for scope in ('', ' | Emerald JV LP', ' | Verdelite JV LP'):
        name = 'Acme Inc. - Term Loan' + scope
        rows.append(dict(cik='0001803498', report_date='2026-03-31', fair_value='100',
                         cost='95', investment_identifier=name,
                         dimensions_raw='investmentidentifieraxis=' + name,
                         src_context_id='loan' + str(len(rows))))
    result = staging_bdc._prepare_bdc(bdc_df=raw_rows(rows))
    result['row_id'] = result.src_context_id
    result = accounting_scope.annotate(result)
    assert len(result) == 4
    kept = result.set_index('src_context_id')
    assert kept.loc['cash', 'asset_category'] == 'CASH'
    assert kept.loc['cash', 'fair_value'] == 11462000
    assert kept.loc['cash', 'cost'] == 11462000
    assert kept.loc['cash', 'accounting_scope_id'] == '0001803498|reporting_entity=emerald jv lp'
    loans = kept.loc[['loan1', 'loan2', 'loan3']]
    assert loans.accounting_scope_id.nunique() == 3
    assert loans.fair_value.tolist() == [100, 100, 100]
    assert loans.is_subsidiary.tolist() == [0, 1, 1]


@pytest.mark.parametrize('reported_credit_facts', [True, False])
def test_goldman_flat_names_do_not_become_the_shared_reference_rate_label(reported_credit_facts):
    names = ['Coding Solutions Acquisition, Inc.', 'Governmentjobs.com, Inc. (dba NeoGov)',
             'Alpha Industry Systems LLC']
    values = [533000, 37151000, 100]
    # The actual two loans have separately tagged rates and spreads.
    # A textual rate label alone is not classification evidence.
    rates = ['0.1029', '0.1041', '0.1']
    rows = [dict(cik='0001772704', report_date='2023-03-31',
                 investment_identifier='Investment ' + name +
                     ' Industry Software Interest Rate 10.29% Reference Rate and Spread S + 5.50% Maturity 05/11/28',
                 fair_value=str(value), cost=str(value + 1),
                 interest_rate=rates[index] if reported_credit_facts else '',
                 basis_spread='0.055' if reported_credit_facts else '',
                 src_context_id='source' + str(index))
            for index, (name, value) in enumerate(zip(names, values))]
    rows.append(dict(cik='0001772704', report_date='2023-03-31',
                     investment_identifier='Investment Debt Investments', fair_value='50000000',
                     src_context_id='subtotal'))
    result = staging_bdc._prepare_bdc(bdc_df=raw_rows(rows)).set_index('src_context_id')
    assert 'subtotal' not in result.index
    assert len(result) == 3
    for index, (name, value) in enumerate(zip(names, values)):
        row = result.loc['source' + str(index)]
        assert row.issuer_name == name
        assert row.fair_value == value and row.cost == value + 1
        assert row.asset_category == ('LOAN' if reported_credit_facts else 'OTHER')


def _unspaced_clo_rows(cik):
    ident = ('Equity and Other Investments Structured Credit Eaton CLO Ltd, Series 2015-1A Structured Product '
             '($2,500par,due1/2030) Initial Acquisition Date 6/23/2022 Reference Rate and Spread SOFR+2.76% Interest Rate 8.09%')
    return raw_rows([dict(cik=cik, report_date='2023-09-30', investment_identifier=ident, fair_value='2394000',
                          cost='2252000', principal_amount='2500000', interest_rate='0.0809', basis_spread='0.0276',
                          dimensions_raw='investmentidentifieraxis=' + ident, src_context_id='clo')])


def test_unspaced_due_maturity_is_read_for_the_fund_that_declares_it(monkeypatch):
    """Sixth Street Specialty Lending writes '($2,500par,due1/2030)'; its wrapper sets staging.maturity_text_unspaced."""
    monkeypatch.setattr(staging_bdc, '_unspaced_due_ciks', lambda: {'0001508655'})
    row = staging_bdc._prepare_bdc(bdc_df=_unspaced_clo_rows('0001508655')).set_index('src_context_id').loc['clo']
    assert str(row.maturity_date)[:10] == '2030-01-31'
    assert row.maturity_date_source == 'identifier_text'


def test_unspaced_due_is_not_read_for_a_fund_without_the_setting(monkeypatch):
    monkeypatch.setattr(staging_bdc, '_unspaced_due_ciks', lambda: {'0001508655'})
    row = staging_bdc._prepare_bdc(bdc_df=_unspaced_clo_rows('0001803498')).set_index('src_context_id').loc['clo']
    assert str(row.maturity_date or '') in ('', 'None', 'nan', 'NaT')


def test_live_wrapper_declares_unspaced_due_for_sixth_street_specialty_only():
    assert staging_bdc._unspaced_due_ciks() == {'0001508655'}
    assert staging_bdc._cik_in_sql(set()) == 'FALSE'
