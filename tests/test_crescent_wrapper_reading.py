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


def _hierarchy(identifier):
    """Condition, issuer and instrument as staging_bdc evaluates them (DuckDB RE2), for one member text."""
    import duckdb
    stg = wrapper()['staging']
    clean = ("replace(replace(regexp_replace(replace(CAST(_raw_id AS VARCHAR), ' ', ' '), '\\s+', ' ', 'g'), "
             "'Investment Type', ' Investment Type'), 'Security Type', ' Security Type')")
    cond = stg['hierarchy_condition_extra'].replace('_clean', clean)
    sql = (f"SELECT {cond}, trim(regexp_extract({clean}, '{stg['hierarchy_issuer_re']}', 1)), "
           f"trim(regexp_extract({clean}, '{stg['hierarchy_instrument_re']}', 1)) FROM (SELECT ? AS _raw_id)")
    return duckdb.connect().execute(sql, [identifier]).fetchone()


def test_typed_member_variants_reach_the_hierarchy_reader():
    # Printed 2025-12-31 / 2025-06-30 / 2023-09-30 / 2023-06-30 / 2026-03-31 member shapes (2026-10-17)
    cases = [
        ('Investments United States Debt Investments Pharmaceuticals, Biotechnology & Life Sciences Teal Acquisition Co., Inc '
         'Unitranche First Lien Term Loan Interest Term S + 625 (100 Floor) Interest Rate 10.02% Maturity/Dissolution Date 09/2028',
         'Teal Acquisition Co., Inc', 'Unitranche First Lien Term Loan'),
        ('Investments United States Debt Investments Diversified Financials Essential Services Holding Corporation Investment '
         'Unitranche First Lien Revolver Interest Term S + 500 (75 Floor) Interest Rate 8.87% Maturity / Dissolution Date 06/2031',
         'Essential Services Holding Corporation', 'Unitranche First Lien Revolver'),
        ('Investments United States Debt Investments Capital Goods Oliver Packaging LLC InvestmenType Senior Secured First Lien '
         'Term Loan Interest Term S + 500 (100 Floor) Interest Rate 10.45% Maturity/ Dissolution Date 07/2028',
         'Oliver Packaging LLC', 'First Lien Term Loan'),
        ('nvestments United States Debt Investments Capital Goods Eshipping Investment Type Senior Secured First Lien Delayed Draw '
         'Term Loan Interest Term S + 500 (100 Floor) Interest Rate 10.43% Maturity/Dissolution Date 11/2027',
         'Eshipping', 'First Lien Delayed Draw Term Loan'),
        ('3 Investments United States Debt Investments Software & Services Park Place Technologies, LLC Investment Type Unsecured '
         'Debt Interest Term 1250 PIK Interest Rate 12.50% Maturity/Dissolution Date 05/2029', 'Park Place Technologies, LLC', 'Unsecured Debt'),
        ('Investments United States Debt Investments Retailing 1959 Holdings, LLC Senior Secured First Lien Term Loan Interest Term '
         'S + 650 (100 Floor) Interest Rate 10.37% Maturity/Dissolution Date 07/2030', '1959 Holdings, LLC', 'First Lien Term Loan'),
        ('Investments United States Debt Investments Capital Goods Painters Supply & Equipment Company Maturity/ Dissolution Date 08/2027',
         'Painters Supply & Equipment Company', ''),
    ]
    for identifier, issuer, instrument in cases:
        assert _hierarchy(identifier) == (True, issuer, instrument), identifier


def test_duplicate_member_tree_and_totals_stay_out():
    # 2025-03-31 repeats rows under this member with the published values: admitting it would double count
    dup = ('Investments in Non-Control, Non-Affiliate Portfolio Companies Pharmaceuticals, Biotechnology & Life Sciences '
           'Teal Acquisition Co., Inc Unitranche First Lien Term Loan Interest Term S + 625 (100 Floor)')
    assert _hierarchy(dup)[0] is False
    assert _hierarchy('Investments United States Debt Investments Software & Services')[0] is False
    assert _hierarchy('Investments United States Debt Investments Total 12345')[0] is False


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


