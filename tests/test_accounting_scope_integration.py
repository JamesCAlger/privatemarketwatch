"""Preserve reporting scopes at both staging and unified duplicate boundaries."""
import pandas as pd
import pytest

from pipeline.staging_bdc import _prepare_bdc
from pipeline.unified_holdings import build_unified_holdings


@pytest.mark.slow
@pytest.mark.staging_sql
@pytest.mark.parametrize('value', [-15.0, 0.0, 100.0])
def test_scope_distinctions_survive_while_same_scope_affiliation_duplicates_collapse(
        tmp_path, monkeypatch, value):
    base = dict(cik='100', entity_name='Test BDC', accession_number='0000000100-26-000001',
        form_type='10-Q', filing_date='2026-05-01', report_date='2026-03-31', period='2026-03-31',
        investment_identifier='Acme Corp - First Lien Term Loan', fair_value=value, cost=0,
        principal_amount=100, shares_held='', interest_rate=8.5, basis_spread=3.0,
        reference_rate_type='SOFR', maturity_date='2029-01-01', pct_of_net_assets='', pik_rate='',
        unrealized_gain_loss='', investment_type='', industry='', affiliation='')
    paths = [
        ('parent-a', 'affiliationaxis=Affiliated'),
        ('parent-b', 'affiliationaxis=NonAffiliated'),
        ('jv1-a', 'nonconsolidatedsubsidiaryaxis=JV1|affiliationaxis=Affiliated'),
        ('jv1-b', 'nonconsolidatedsubsidiaryaxis=JV1|affiliationaxis=NonAffiliated'),
        ('jv2', 'nonconsolidatedsubsidiaryaxis=JV2'),
        ('unknown-a', 'nonconsolidatedsubsidiaryaxis='),
        ('unknown-b', 'nonconsolidatedsubsidiaryaxis='),
    ]
    raw = pd.DataFrame([dict(base, src_context_id=context, dimensions_raw=dimensions)
                        for context, dimensions in paths])
    staged = _prepare_bdc(raw)
    assert len(staged) == 5
    assert set(staged.src_context_id) >= {'jv2', 'unknown-a', 'unknown-b'}
    # Exercise the next boundary on exactly these prepared rows, without
    # repeating expensive parsing or hiding its preceding assertions.
    monkeypatch.setattr('pipeline.staging_bdc._prepare_bdc', lambda *args, **kwargs: staged.copy())
    monkeypatch.setattr('pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE',
                        tmp_path/'private_markets_holdings.csv')
    pd.DataFrame([dict(cik='0000000100', entity_name='Test BDC')]).to_csv(
        tmp_path/'combined_universe.csv', index=False)
    result = build_unified_holdings(bdc_df=raw, nport_df=pd.DataFrame(),
                                   output_file=tmp_path/'private_markets_holdings.csv')
    assert len(result) == 5
    assert result.row_id.nunique() == 5
    assert result.accounting_scope_id.nunique() == 5
    assert result.fair_value.tolist() == [value] * 5
    assert result.accounting_record_class.value_counts().to_dict() == {
        'underlying_schedule': 2, 'unresolved_underlying_schedule': 2, 'parent_schedule': 1}
