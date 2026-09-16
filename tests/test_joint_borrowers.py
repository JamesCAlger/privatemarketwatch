"""Co-listed legal borrowers cannot collapse to a cached single-name prefix."""
import duckdb
import pandas as pd
import pytest

from pipeline import entity_resolution
from pipeline.joint_borrowers import joint_label_sql


@pytest.mark.parametrize('name,expected', [
    ('Coupa Holdings, LLC and Coupa Software Incorporated, First lien loan',
     'Coupa Holdings, LLC and Coupa Software Incorporated'),
    ('Higginbotham Insurance Agency, Inc. and HIG Intermediate, Inc., Preferred shares',
     'Higginbotham Insurance Agency, Inc. and HIG Intermediate, Inc.'),
    ('Higginbotham Insurance Agency, Inc., HIG Operations Holdings, Inc., and HIG Intermediate, Inc., First lien loan',
     'Higginbotham Insurance Agency, Inc., HIG Operations Holdings, Inc., and HIG Intermediate, Inc.'),
    ('Smith and Sons LLC, Term Loan', None),
    ('Smith & Sons LLC', None),
    ('Acme Inc., cash and PIK interest', None),
    ('Acme Inc. and its subsidiaries', None),
    ('Acme Incidental and Beta LLC', None),
])
def test_only_complete_legal_name_lists_are_joint_borrowers(name, expected):
    with duckdb.connect() as con:
        actual = con.execute('SELECT ' + joint_label_sql('name_text') + ' FROM (SELECT ? AS name_text)',
                             [name]).fetchone()[0]
    assert actual == expected


def test_cached_truncation_and_shared_loan_id_cannot_merge_joint_and_single_borrowers(tmp_path, monkeypatch):
    joint = 'Coupa Holdings, LLC and Coupa Software Incorporated'
    identifier = joint + ', First lien senior secured loan'
    cache = tmp_path / 'cache.csv'
    pd.DataFrame([dict(bdc_investment_identifier=identifier,
                       extracted_company_name='Coupa Holdings, LLC')]).to_csv(cache, index=False)
    monkeypatch.setattr(entity_resolution, 'IDENTIFIER_EXTRACTION_LOOKUP_FILE', cache)
    variants = pd.DataFrame([
        dict(issuer_name=identifier, source='bdc', bdc_investment_identifier=identifier,
             occurrence_count=1, cusip='SHAREDLOAN', lei=None),
        dict(issuer_name='Coupa Holdings, LLC', source='bdc', bdc_investment_identifier='',
             occurrence_count=1, cusip=None, lei=None),
        dict(issuer_name='Coupa Holdings, LLC', source='nport', bdc_investment_identifier='',
             occurrence_count=1, cusip='SHAREDLOAN', lei=None),
        dict(issuer_name=joint, source='nport', bdc_investment_identifier='',
             occurrence_count=1, cusip=None, lei=None),
    ])
    result = entity_resolution._cross_source_link(
        entity_resolution._fuzzy_cluster(entity_resolution._exact_dedup(variants)))
    by_key = result.set_index(['issuer_name', 'source'])
    joint_row = by_key.loc[(identifier, 'bdc')]
    assert joint_row.extracted_name == joint
    assert joint_row.entity_num == by_key.loc[(joint, 'nport')].entity_num
    assert joint_row.entity_num != by_key.loc[('Coupa Holdings, LLC', 'bdc')].entity_num
    assert joint_row.entity_num != by_key.loc[('Coupa Holdings, LLC', 'nport')].entity_num


@pytest.mark.parametrize('dtype', ['Int64', 'string', 'object'])
def test_missing_structured_ids_neither_crash_nor_link_unrelated_borrowers(dtype):
    variants = pd.DataFrame([
        dict(entity_num=1, normalized_name='aster', canonical_name='Aster LLC',
             source='bdc', occurrence_count=1),
        dict(entity_num=2, normalized_name='zebra', canonical_name='Zebra LLC',
             source='nport', occurrence_count=1),
    ])
    for field in ('cusip', 'lei'):
        variants[field] = pd.Series([pd.NA, pd.NA], dtype=dtype)
    result = entity_resolution._cross_source_link(variants)
    assert result.entity_num.tolist() == [1, 2]


def test_missing_identifier_uses_the_disclosed_name(tmp_path, monkeypatch):
    monkeypatch.setattr(entity_resolution, 'IDENTIFIER_EXTRACTION_LOOKUP_FILE', tmp_path / 'absent.csv')
    variants = pd.DataFrame([
        dict(issuer_name='Acme LLC', source=source, bdc_investment_identifier=pd.NA,
             occurrence_count=1, cusip=None, lei=None)
        for source in ('bdc', 'nport')
    ])
    result = entity_resolution._exact_dedup(variants)
    assert result.extracted_name.tolist() == ['Acme LLC', 'Acme LLC']
    assert result.entity_num.nunique() == 1


@pytest.mark.parametrize('identifier_dtype', ['object', 'string'])
def test_joint_name_derivation_preserves_source_columns_and_row_alignment(
        tmp_path, monkeypatch, identifier_dtype):
    monkeypatch.setattr(entity_resolution, 'IDENTIFIER_EXTRACTION_LOOKUP_FILE', tmp_path / 'absent.csv')
    joint = 'Aster LLC and Beta Incorporated'
    variants = pd.DataFrame([
        dict(issuer_name=joint + ', First lien loan', source='bdc',
             bdc_investment_identifier='', occurrence_count=2, fair_value=0.0),
        dict(issuer_name='Zebra LLC', source='nport',
             bdc_investment_identifier='', occurrence_count=1, fair_value=-5.0),
    ])
    variants['cusip'] = pd.Series(['001234AB9', None], dtype=identifier_dtype)
    variants['lei'] = pd.Series([None, None], dtype=identifier_dtype)
    variants.index = [47, 5]
    original = variants.copy(deep=True)
    result = entity_resolution._exact_dedup(variants)
    pd.testing.assert_frame_equal(result[original.columns], original.reset_index(drop=True))
    pd.testing.assert_frame_equal(variants, original)
    assert result.extracted_name.tolist() == [joint, 'Zebra LLC']
    assert result.entity_num.nunique() == 2
