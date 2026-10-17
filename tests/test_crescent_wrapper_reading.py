"""Crescent settings: names and benchmarks follow its printed schedule."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def wrapper():
    return json.loads((ROOT / 'data/overrides/bdc_xbrl_wrappers/0001633336.json').read_text())


def test_missing_industries_and_company_word_boundary():
    pattern = re.compile(wrapper()['staging']['hierarchy_issuer_re'])
    for industry, name in [('Insurance', 'Newcleus, LLC'), ('Automobiles & Components', 'Sun Acquirer Corp.'),
                           ('Commercial & Professional Services', 'Service Logic Acquisition, Inc.')]:
        label = f'Investments United States Debt Investments {industry} {name} Investment Type Unitranche First Lien Term Loan'
        assert pattern.search(label).group(1) == name
    assert pattern.search('Investments United States Debt Investments Total 12345') is None
    assert pattern.search('Investments United States Debt Investments Health Care Equipment & Services, BVI Medical Inc. Investment Type Unitranche First Lien Term Loan').group(1) == 'BVI Medical Inc.'
    assert pattern.search('Investments United States Debt Investments Pharmaceuticals, Biotechnology & Life SciencesTeal Acquisition Co., Inc Investment Type Unitranche First Lien Term Loan').group(1) == 'Teal Acquisition Co., Inc'


def test_printed_column_and_fund_scope():
    from pipeline.source_encodings import reference_rate_reading
    from pipeline.bdc_xbrl_html_bridge import _named_header
    encodings = {'0001633336': wrapper()['source_encodings']}
    reading = reference_rate_reading('0001633336', encodings)
    assert _named_header('InterestTerm *') in reading['columns']
    assert reading['codes']['B'] == 'BBSY'
    assert reading['codes']['SN'] == 'SONIA'
    assert reference_rate_reading('0001633337', encodings) is None


def test_wrapper_schema():
    import jsonschema
    schema = json.loads((ROOT / 'schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json').read_text())
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors(wrapper()))


def test_equal_value_term_loans_keep_spread_identity_only():
    from pipeline.staging_bdc import distinct_member_suffix_sql
    import duckdb
    w = wrapper()
    expression = distinct_member_suffix_sql({w['cik']:w}, 'identifier')
    con = duckdb.connect()
    names = [f'MHS Acquisition Holdings, LLC Investment Type Senior Secured First Lien Term Loan Interest Term S + {spread} (100 Floor) Interest Rate {rate}%' for spread,rate in [(625,10),(650,10.25),(625,9.75)]]
    result = [con.execute(f'SELECT {expression} FROM (SELECT ? cik, ? identifier)', [w['cik'],name]).fetchone()[0] for name in names]
    assert result[0] != result[1]
    assert result[0] == result[2]  # changing coupon on a comparative does not create another position
    assert con.execute(f'SELECT {expression} FROM (SELECT ? cik, ? identifier)', ['0001633337',names[0]]).fetchone()[0] == ''
    assert con.execute(f'SELECT {expression} FROM (SELECT ? cik, ? identifier)', [w['cik'],names[0].replace('MHS Acquisition','Other Acquisition')]).fetchone()[0] == ''


