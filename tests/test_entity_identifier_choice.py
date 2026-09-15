"""Cached name evidence survives deterministic representative selection."""
import pandas as pd
import pytest

from pipeline import entity_resolution as er


def build(tmp_path, monkeypatch, identifiers, cache_rows, *, source='bdc', reverse=False):
    cache=tmp_path/'names.csv'
    if cache_rows is not None:
        pd.DataFrame(cache_rows,columns=['bdc_investment_identifier','extracted_company_name']).to_csv(cache,index=False)
    monkeypatch.setattr(er,'IDENTIFIER_EXTRACTION_LOOKUP_FILE',cache)
    rows=[dict(issuer_name='Brand Acme Inc.',source=source,cusip='',lei='',
        bdc_investment_identifier=identifier) for identifier in identifiers]
    if reverse:rows.reverse()
    holdings=tmp_path/'holdings.csv'
    pd.DataFrame(rows).to_csv(holdings,index=False)
    return er._build_variant_table(holdings)


@pytest.mark.parametrize('reverse',[False,True])
def test_cached_name_survives_lexically_first_frequent_cache_miss(tmp_path,monkeypatch,reverse):
    variants=build(tmp_path,monkeypatch,['a-new-miss']*5+['z-cached'],
        [('z-cached','Acme Inc.')],reverse=reverse)
    assert variants.iloc[0].bdc_investment_identifier=='z-cached'
    assert variants.iloc[0].occurrence_count==6
    assert er._exact_dedup(variants).iloc[0].extracted_name=='Acme Inc.'


def test_frequency_and_stable_tie_break_ignore_cache_row_multiplicity(tmp_path,monkeypatch):
    variants=build(tmp_path,monkeypatch,['a-rare']+['b-supported']*3+['c-supported']*3,
        [('a-rare','Other name')]*10+[('b-supported','Acme Inc.'),('c-supported','Acme Inc.')])
    assert variants.iloc[0].bdc_investment_identifier=='b-supported'
    assert variants.iloc[0].occurrence_count==7


def test_blank_cached_name_does_not_displace_populated_evidence(tmp_path,monkeypatch):
    variants=build(tmp_path,monkeypatch,['a-blank']*5+['z-cached'],
        [('a-blank','   '),('z-cached','Acme Inc.')])
    assert variants.iloc[0].bdc_investment_identifier=='z-cached'


def test_unrelated_cache_identifier_cannot_supply_this_issuer(tmp_path,monkeypatch):
    variants=build(tmp_path,monkeypatch,['b-common']*3+['a-rare'],
        [('not-in-this-issuer','Unrelated Inc.')])
    assert variants.iloc[0].bdc_investment_identifier=='b-common'
    assert er._exact_dedup(variants).iloc[0].extracted_name=='Brand Acme Inc.'


def test_absent_cache_keeps_all_observations_and_deterministic_choice(tmp_path,monkeypatch):
    variants=build(tmp_path,monkeypatch,['b-id','a-id','',None],None)
    assert variants.iloc[0].bdc_investment_identifier=='a-id'
    assert variants.iloc[0].occurrence_count==4


def test_bdc_cache_does_not_control_nport_representative(tmp_path,monkeypatch):
    variants=build(tmp_path,monkeypatch,['a-common']*3+['z-cached'],
        [('z-cached','Another entity')],source='nport')
    assert variants.iloc[0].bdc_investment_identifier=='a-common'
