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
