"""Source meaning must be independent of candidate classifications."""
import duckdb
from lxml import etree
import pytest

from pipeline.categorical_field_assessment import comparison_sql, maturity_reference, read_facts


def document(facts='', dimensions=''):
    return etree.ElementTree(etree.fromstring(('''<x:xbrl
      xmlns:x="http://www.xbrl.org/2003/instance"
      xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:g="http://fasb.org/us-gaap/2025">
      <x:context id="p"><x:entity><x:segment>''' + dimensions + '''</x:segment></x:entity>
      <x:period><x:instant>2026-03-31</x:instant></x:period></x:context>'''
      + facts + '</x:xbrl>').encode()))


def collect(facts='', dimensions='', valid_entity=True):
    return read_facts(document(facts, dimensions),
                      {'p': dict(quarter='2026-03-31', valid_entity=valid_entity)})


@pytest.mark.parametrize('raw,value,precision,status', [
    ('2028-02-29', '2028-02-29', 'day', 'dated'),
    ('2028-02', '2028-02-29', 'month', 'partial'),
    ('2027-02', '2027-02-28', 'month', 'partial'),
    ('2028', '2028-12-31', 'year', 'partial'),
    ('Perpetual', None, 'unknown', 'perpetual'),
])
def test_exact_and_partial_dates_keep_disclosed_precision(raw, value, precision, status):
    assert maturity_reference(raw) == (dict(maturity_date=value,
        maturity_precision=precision, maturity_status=status), 'ready')


@pytest.mark.parametrize('raw', ['2027-02-29', '2028-13', '0000', '03/04/2029', 'March 2029', ''])
def test_invalid_or_unsupported_dates_are_not_guessed(raw):
    assert maturity_reference(raw) == ({}, 'unresolved_maturity_text')


def test_source_reader_records_maturity_and_rate_kind_without_production_values():
    facts = collect('<g:InvestmentMaturityDate contextRef="p">2028-02</g:InvestmentMaturityDate>'
        '<g:InvestmentInterestRatePaidInCash contextRef="p">.08</g:InvestmentInterestRatePaidInCash>')
    assert {f['field']: f['reference_value'] for f in facts} == dict(
        maturity_date='2028-02-29', maturity_precision='month', maturity_status='partial',
        interest_rate_kind='cash')


def test_generic_rate_cannot_certify_cash_and_floor_is_not_coupon_kind():
    facts = collect('<g:InvestmentInterestRate contextRef="p">.08</g:InvestmentInterestRate>'
        '<g:InvestmentInterestRateFloor contextRef="p">.01</g:InvestmentInterestRateFloor>')
    assert len(facts) == 1
    assert facts[0]['reason'] == 'unresolved_rate_kind'
    assert facts[0]['reference_value'] is None


def test_conflicting_cash_and_yield_evidence_remains_two_references():
    facts = collect('<g:InvestmentInterestRatePaidInCash contextRef="p">.08</g:InvestmentInterestRatePaidInCash>'
        '<g:InvestmentEffectiveYield contextRef="p">.10</g:InvestmentEffectiveYield>')
    assert {f['reference_value'] for f in facts} == {'cash', 'effective_yield'}


def test_source_classification_axes_are_interpreted_without_borrower_keywords():
    facts = collect(dimensions='''
      <d:explicitMember dimension="g:InvestmentInstrumentAxis">g:DelayedDrawTermLoanMember</d:explicitMember>
      <d:explicitMember dimension="g:LienPositionAxis">g:FirstLienMember</d:explicitMember>
      <d:explicitMember dimension="g:LegalEntityAxis">g:SecondLienMember</d:explicitMember>''')
    assert [(f['field'], f['reference_value']) for f in facts if f['reason']=='ready'] == [
        ('instrument_type', 'Delayed Draw Term Loan'), ('lien_position', 'First Lien')]
    assert all(f['reference_value'] != 'Second Lien' for f in facts)


def test_unsupported_disclosed_classification_stays_visible():
    facts = collect(dimensions='<d:explicitMember dimension="g:InvestmentTypeAxis">g:CustomHybridMember</d:explicitMember>')
    assert len(facts) == 2
    assert {f['reason'] for f in facts} == {'unsupported_classification_member'}


def test_wrong_entity_cannot_supply_valid_reference():
    facts = collect('<g:InvestmentMaturityDate contextRef="p">2028</g:InvestmentMaturityDate>', valid_entity=False)
    assert {f['reason'] for f in facts} == {'reporting_entity_mismatch'}


def compare(**changes):
    source = dict(cik='123', quarter='2026-03-31', accession='a', context_id='p', field='maturity_precision',
        source_complete=True, fact_count=1, variants=1, reason='ready', source_role='confirmed_position',
        correspondence_status='ready', reference_value='month')
    published = dict(cik='123', quarter='2026-03-31', accession='a', context_id='p', field='maturity_precision',
        candidate_rows=1, published='month')
    for key, value in changes.items():
        (published if key in ('candidate_rows', 'published') else source)[key] = value
    with duckdb.connect() as con:
        for name, row in (('other_source_fields', source), ('other_published', published)):
            con.execute('CREATE TABLE '+name+' AS SELECT '+','.join(
                ('CAST(? AS VARCHAR)' if k in ('published','reference_value') else '?')+' AS '+k
                for k in row), list(row.values()))
        return con.execute(comparison_sql()).fetchall()[0][-2:]


@pytest.mark.parametrize('changes,category', [
    ({}, 'correct'), ({'published':'day'}, 'incorrect'),
    ({'published':None}, 'missing_output'), ({'candidate_rows':0}, 'missing_output'),
    ({'candidate_rows':2}, 'disclosed_unassessable'), ({'variants':2}, 'disclosed_unassessable'),
    ({'reason':'unsupported_classification_member'}, 'disclosed_unassessable'),
    ({'fact_count':0}, 'not_disclosed'), ({'source_complete':False}, 'disclosed_unassessable'),
    ({'correspondence_status':'unresolved'}, 'disclosed_unassessable'),
    ({'reference_value':None, 'published':None}, 'correct'),
    ({'reference_value':None, 'published':'2030-01-01'}, 'incorrect'),
])
def test_categories_conserve_errors_missingness_and_uncertainty(changes, category):
    assert compare(**changes)[0] == category


def test_shared_source_parse_preserves_independent_categorical_evidence(tmp_path):
    from pipeline.field_assessment import read_field_document
    path = tmp_path/'source.xml'
    tree = document('<g:InvestmentMaturityDate contextRef="p">2028-02</g:InvestmentMaturityDate>')
    entity = tree.find('.//{http://www.xbrl.org/2003/instance}entity')
    identifier = etree.SubElement(entity, '{http://www.xbrl.org/2003/instance}identifier', scheme='sec')
    identifier.text = '123'
    tree.write(str(path))
    result = read_field_document(path, '0000000123')
    assert result['complete'] and result['sha256']
    assert len(result['other_facts'])==3
    assert {f['reason'] for f in result['other_facts']}=={'ready'}


def test_source_grid_join_retains_unknown_fields_and_missing_candidate_columns(tmp_path):
    import csv
    from pipeline.categorical_field_assessment import assemble_comparisons, FIELDS
    path = tmp_path/'facts.csv'
    facts = [dict(cik='123',accession='a',**f) for f in collect(
        '<g:InvestmentMaturityDate contextRef="p">2028-02</g:InvestmentMaturityDate>')]
    with path.open('w', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(facts[0])); writer.writeheader(); writer.writerows(facts)
    with duckdb.connect() as con:
        con.execute("""CREATE TABLE reference_contexts AS SELECT '123' AS cik,'a' AS accession,
          'p' AS context_id,'2026-03-31' AS quarter,'confirmed_position' AS source_role,
          'selected_source_roster' AS reference_origin,100 AS source_fv,'USD' AS currency,true AS source_complete""")
        con.execute("CREATE TABLE document_status AS SELECT '123' AS cik,'a' AS accession,true AS complete")
        con.execute("CREATE TABLE quarter_candidate_counts AS SELECT '123' AS cik,'2026-03-31' AS quarter,1 AS rows")
        con.execute("CREATE TABLE links AS SELECT cik,accession,context_id,quarter,'R1' AS row_id FROM reference_contexts")
        con.execute("CREATE TABLE candidate AS SELECT 'R1' AS row_id,DATE '2028-02-29' AS maturity_date,'day' AS maturity_precision")
        assemble_comparisons(con,path)
        results = dict(con.execute('SELECT field,category FROM other_assessments').fetchall())
    assert len(results)==len(FIELDS)
    assert results['maturity_date']=='correct'
    assert results['maturity_precision']=='incorrect'
    assert results['maturity_status']=='missing_output'
    assert results['instrument_type']=='not_disclosed'
