"""Regression fixtures for reviewed cash and reporting-portfolio encodings."""
import json

import duckdb
import pandas as pd
import pytest

from pipeline import source_encodings
from pipeline.accounting_scope import annotate, scope_expression

CASH = 'Dreyfus Government Cash Management - Institutional Shares | Emerald JV LP'
ENCODINGS = {'0001803498': {
    'cash_identifiers': [CASH],
    'reporting_entity_suffixes': ['Emerald JV LP', 'Verdelite JV LP'],
    'reporting_entity_identifier_suffixes': ['Emerald JV LP', 'Verdelite JV LP'],
}}


@pytest.mark.parametrize('cik,name,expected', [
    ('0001803498', CASH, True),
    ('1803498', '  ' + CASH.upper() + '  ', True),
    ('0001772704', CASH, False),
    ('0001803498', 'Total ' + CASH, False),
    ('0001803498', CASH + ' - Term Loan', False),
    ('0001803498', 'Acme Corp - Cash + PIK Interest Rate 5%', False),
    ('0001803498', None, False),
])
def test_cash_identity_requires_exact_disclosed_instrument_and_filer(cik, name, expected):
    expression = source_encodings.cash_identifier_expression('cik', 'identifier', ENCODINGS)
    with duckdb.connect() as con:
        assert con.execute('SELECT ' + expression + ' FROM (SELECT ? AS cik, ? AS identifier)',
                           [cik, name]).fetchone()[0] is expected


@pytest.mark.parametrize('dimensions,expected', [
    ('investmentidentifieraxis=Acme LLC | Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Acme LLC | Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=BCRED Emerald JV LP', 'parent'),
    ('investmentidentifieraxis=Emerald JV LP Services LLC', 'parent'),
    ('investmentidentifieraxis=Acme LLC | industryaxis=Emerald JV LP', 'parent'),
    ('investmentidentifieraxis=Acme LLC | Emerald JV LP Holdings', 'parent'),
    ('investmentidentifieraxis=MH Sub I, LLC 1 Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=MH Sub I, LLC, Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=ADCS Clinics, LLC, Emerald JV LP 3', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Acme LLC and Verdelite JV LP', 'parent'),
    ('investmentidentifieraxis=Acme IncEmerald JV LP', 'parent'),
    # Reviewed 2026-09-17 (V12 review): prefix form, unlisted legal suffixes, ordinal-space form.
    ('investmentidentifieraxis=Emerald JV LP, 2U, Inc.', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Freeport LNG Investments, LLLP, Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=AlixPartners, LLP, Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=Monk Holding Co., Emerald JV LP 1', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Auris Luxembourg III S.a r.l., Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Tangerine Bidco S.p.A, Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Confine Visual Bidco, Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Symphony Technology Group 1 Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=Air Canada, Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=TRC Companies, Inc (fka Bolt Infrastructure Merger Sub, Inc.), Emerald JV LP', 'reporting_entity=emerald jv lp'),
    # Still parent: bare label, fund's own interest, joint "and", label inside a longer name.
    # BCRED Emerald JV LP / BCRED Verdelite JV LP 2 (own-interest) and
    # Acme LLC and Verdelite JV LP / Acme LLC and Emerald JV LP 1 (trailing
    # joint) are re-asserted below as guard-load-bearing: reviewed 2026-09-17
    # round 2 admits a bare-space terminal form (borrower + single space +
    # label, no comma/digit before it), and without the own-interest or
    # trailing-joint guard each of these four would incorrectly match that
    # bare-space alternative and flip to underlying. They are not dead checks.
    ('investmentidentifieraxis=Emerald JV LP', 'parent'),
    ('investmentidentifieraxis=BCRED Verdelite JV LP 2', 'parent'),
    ('investmentidentifieraxis=Emerald JV LP, and Acme LLC', 'parent'),
    ('investmentidentifieraxis=Acme LLC and Emerald JV LP 1', 'parent'),
    ('investmentidentifieraxis=Emerald JV LP Holdings, Acme LLC', 'parent'),
    # Reviewed 2026-09-17 round 2 (bare-space form, 2023-09-30 through
    # 2024-03-31 only): borrower + single space + label, no comma/digit/space
    # immediately before the label. Source: 0001803498-23-000021 c-3367 and
    # 0001803498-24-000007 c-3689/c-4713/c-3813/c-4730/c-3831/c-3801/c-3928/
    # c-3923/c-3924.
    ('investmentidentifieraxis=Polyphase Elevator Holding Co. Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Auris Luxembourg III Sarl Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=Confine Visual Bidco Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Corporation Service Company Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Freeport LNG Investments, LLLP Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Alterra Mountain Company  Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
])
def test_reporting_suffix_does_not_turn_borrower_names_into_subsidiaries(monkeypatch, dimensions, expected):
    monkeypatch.setattr(source_encodings, 'load_encodings', lambda: ENCODINGS)
    expression = scope_expression('cik', 'dimensions', 'false', "'row'")
    with duckdb.connect() as con:
        actual = con.execute('SELECT ' + expression + " FROM (SELECT '0001803498' AS cik, ? AS dimensions)",
                             [dimensions]).fetchone()[0]
    assert actual == '0001803498|' + expected


def test_annotation_keeps_parent_and_two_portfolios_separate_without_changing_money(monkeypatch):
    monkeypatch.setattr(source_encodings, 'load_encodings', lambda: ENCODINGS)
    frame = pd.DataFrame([
        dict(cik='0001803498', row_id='parent', is_subsidiary=0, fair_value=100,
             bdc_dimensions_raw='investmentidentifieraxis=BCRED Emerald JV LP'),
        dict(cik='0001803498', row_id='emerald', is_subsidiary=0, fair_value=100,
             bdc_dimensions_raw='investmentidentifieraxis=Acme LLC | Emerald JV LP'),
        dict(cik='0001803498', row_id='verdelite', is_subsidiary=0, fair_value=-5,
             bdc_dimensions_raw='investmentidentifieraxis=Acme LLC | Verdelite JV LP'),
    ])
    result = annotate(frame)
    assert result.row_id.tolist() == frame.row_id.tolist()
    assert result.fair_value.tolist() == [100, 100, -5]
    assert result.is_subsidiary.tolist() == [0, 1, 1]
    assert result.accounting_scope_id.nunique() == 3
    assert result.accounting_record_class.tolist() == ['parent_schedule', 'underlying_schedule', 'underlying_schedule']
    pd.testing.assert_frame_equal(annotate(result), result)
    assert frame.is_subsidiary.tolist() == [0, 0, 0]


@pytest.mark.parametrize('encoding', [
    {'reporting_entity_suffixes': ['Emerald JV LP', ' emerald jv lp ']},
    {'reporting_entity_suffixes': ['axis=Emerald JV LP']},
    {'reporting_entity_suffixes': ['Emerald JV LP|Other']},
    {'cash_identifiers': ['']},
    {'cash_identifiers': CASH},
    {'unknown_rule': ['anything']},
])
def test_malformed_encoding_fails_instead_of_silently_changing_scope(tmp_path, encoding):
    (tmp_path / '0001803498.json').write_text(json.dumps({
        'schema_version': 'bdc-xbrl-wrapper.v3', 'cik': '0001803498', 'source_encodings': encoding,
    }), encoding='utf-8')
    with pytest.raises(ValueError):
        source_encodings.load_encodings(tmp_path)


def test_unconfigured_wrapper_preserves_old_scope_and_empty_annotation(tmp_path):
    (tmp_path / 'reference.json').write_text(json.dumps({'entries': []}), encoding='utf-8')
    assert source_encodings.load_encodings(tmp_path) == {}
    assert source_encodings.cash_identifier_expression('cik', 'identifier', {}) == 'false'
    result = annotate(pd.DataFrame(columns=['cik', 'row_id']))
    assert list(result.columns) == ['cik', 'row_id', 'accounting_scope_id', 'accounting_record_class']
