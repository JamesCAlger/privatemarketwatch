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


# --- detached schedule blocks (HPS joint-venture schedules, 2026-10-05) ---------------

HPS = '0001838126'
JV = 'joint venture schedule'
DETACHED = {HPS: {'detached_schedule_labels': [JV]}}


def _raw(con, rows):
    """rows: (cik, accession, period, context, dimensions)."""
    con.execute('CREATE TABLE bdc_raw(cik VARCHAR, accession_number VARCHAR, period VARCHAR, '
                'src_context_id VARCHAR, dimensions_raw VARCHAR)')
    con.executemany('INSERT INTO bdc_raw VALUES (?,?,?,?,?)', rows)


def _dims(con):
    return dict(con.execute('SELECT src_context_id, dimensions_raw FROM bdc_raw '
                            'ORDER BY accession_number, period, src_context_id').fetchall())


def test_rows_after_a_large_jump_in_context_order_are_tagged_as_the_detached_schedule():
    rows = [('1838126', 'A1', '2026-03-31', f'c-{n}', f'investmentidentifieraxis=Main {n} | Non-Affiliated Issuer')
            for n in (10, 11, 13, 14)]
    rows += [('1838126', 'A1', '2026-03-31', 'c-12', 'investmentidentifieraxis=Untagged Main Row'),
             ('1838126', 'A1', '2026-03-31', 'c-3653', 'investmentidentifieraxis=Sentinel Buyer Corp. 1'),
             ('1838126', 'A1', '2026-03-31', 'c-3654', None)]
    with duckdb.connect() as con:
        _raw(con, rows)
        counts = source_encodings.tag_detached_schedules(con, encodings=DETACHED)
        dims = _dims(con)
    assert counts == {HPS: 2}
    assert dims['c-3653'] == 'investmentidentifieraxis=Sentinel Buyer Corp. 1 | ' + JV
    assert dims['c-3654'].endswith(' | ' + JV)
    # an untagged row INSIDE the main block is a filer omission, not a second schedule
    assert dims['c-12'] == 'investmentidentifieraxis=Untagged Main Row'
    assert dims['c-10'].endswith('Non-Affiliated Issuer')


def test_no_large_jump_means_no_detached_schedule():
    rows = [('1838126', 'A1', '2023-03-31', f'c-{n}', 'investmentidentifieraxis=Main') for n in (10, 12, 60, 209)]
    with duckdb.connect() as con:
        _raw(con, rows)
        assert source_encodings.tag_detached_schedules(con, encodings=DETACHED) == {HPS: 0}
        assert set(_dims(con).values()) == {'investmentidentifieraxis=Main'}


def test_a_fund_that_has_not_opted_in_is_never_tagged():
    rows = [('1803498', 'B1', '2026-03-31', 'c-10', 'investmentidentifieraxis=Main'),
            ('1803498', 'B1', '2026-03-31', 'c-9000', 'investmentidentifieraxis=Far Away')]
    with duckdb.connect() as con:
        _raw(con, rows)
        assert source_encodings.tag_detached_schedules(con, encodings=DETACHED) == {HPS: 0}
        assert _dims(con)['c-9000'] == 'investmentidentifieraxis=Far Away'


def test_blocks_are_found_per_filing_and_per_period():
    rows = [
        # current period: main block then a detached block
        ('1838126', 'A1', '2025-12-31', 'c-10', 'investmentidentifieraxis=Main'),
        ('1838126', 'A1', '2025-12-31', 'c-2400', 'investmentidentifieraxis=JV Now'),
        # comparative period of the same filing sits far from the current one in context
        # order; that distance must not make its whole main block "detached"
        ('1838126', 'A1', '2024-12-31', 'c-1200', 'investmentidentifieraxis=Main Prior'),
        ('1838126', 'A1', '2024-12-31', 'c-1201', 'investmentidentifieraxis=Main Prior 2'),
        ('1838126', 'A1', '2024-12-31', 'c-3100', 'investmentidentifieraxis=JV Prior'),
        # another filing whose numbering happens to start high
        ('1838126', 'A2', '2025-09-30', 'c-5000', 'investmentidentifieraxis=Other Filing Main'),
    ]
    with duckdb.connect() as con:
        _raw(con, rows)
        assert source_encodings.tag_detached_schedules(con, encodings=DETACHED) == {HPS: 2}
        dims = _dims(con)
    assert dims['c-2400'].endswith(JV) and dims['c-3100'].endswith(JV)
    for untouched in ('c-10', 'c-1200', 'c-1201', 'c-5000'):
        assert JV not in dims[untouched]


def test_tagging_twice_does_not_stack_labels_and_odd_context_ids_are_left_alone():
    rows = [('1838126', 'A1', '2026-03-31', 'c-10', 'investmentidentifieraxis=Main'),
            ('1838126', 'A1', '2026-03-31', 'c-900', 'investmentidentifieraxis=JV'),
            ('1838126', 'A1', '2026-03-31', 'ctx_abc', 'investmentidentifieraxis=No Number')]
    with duckdb.connect() as con:
        _raw(con, rows)
        source_encodings.tag_detached_schedules(con, encodings=DETACHED)
        assert source_encodings.tag_detached_schedules(con, encodings=DETACHED) == {HPS: 0}
        dims = _dims(con)
    assert dims['c-900'] == 'investmentidentifieraxis=JV | ' + JV
    assert dims['ctx_abc'] == 'investmentidentifieraxis=No Number'


def test_a_tagged_row_is_retained_as_an_underlying_schedule_row(monkeypatch):
    monkeypatch.setattr(source_encodings, 'load_encodings', lambda: DETACHED)
    frame = pd.DataFrame([
        dict(cik=HPS, row_id='main', is_subsidiary=0, fair_value=100,
             bdc_dimensions_raw='investmentidentifieraxis=Emerus Holdings, Inc. 1 | Non-Affiliated Issuer'),
        dict(cik=HPS, row_id='jv', is_subsidiary=0, fair_value=245,
             bdc_dimensions_raw='investmentidentifieraxis=Emerus Holdings, Inc. 1 | ' + JV),
        dict(cik=HPS, row_id='untagged-main', is_subsidiary=0, fair_value=2,
             bdc_dimensions_raw='investmentidentifieraxis=CCI Topco, Inc. - Preferred Stock'),
    ])
    result = annotate(frame)
    assert result.accounting_record_class.tolist() == [
        'parent_schedule', 'underlying_schedule', 'parent_schedule']
    assert result.is_subsidiary.tolist() == [0, 1, 0]
    assert result.fair_value.tolist() == [100, 245, 2]
    assert result.accounting_scope_id.tolist()[1] == HPS + '|reporting_entity=' + JV


@pytest.mark.parametrize('encoding', [
    {'detached_schedule_labels': ['one', 'two']},
    {'detached_schedule_labels': ['axis=joint venture']},
    {'detached_schedule_labels': ['']},
])
def test_malformed_detached_schedule_encoding_fails(tmp_path, encoding):
    (tmp_path / '0001838126.json').write_text(json.dumps({
        'schema_version': 'bdc-xbrl-wrapper.v3', 'cik': HPS, 'source_encodings': encoding,
    }), encoding='utf-8')
    with pytest.raises(ValueError):
        source_encodings.load_encodings(tmp_path)


def test_hps_wrapper_declares_its_joint_venture_schedules():
    encodings = source_encodings.load_encodings()
    assert encodings[HPS]['detached_schedule_labels'] == [JV]


def test_rows_without_source_contexts_are_skipped_not_guessed():
    with duckdb.connect() as con:
        con.execute("CREATE TABLE bdc_raw AS SELECT '1838126' AS cik, 'A1' AS accession_number, "
                    "'investmentidentifieraxis=Old HTML Row' AS dimensions_raw")
        assert source_encodings.tag_detached_schedules(con, encodings=DETACHED) == {HPS: 0}
        assert con.execute('SELECT dimensions_raw FROM bdc_raw').fetchone()[0].endswith('Old HTML Row')


# BCRED's 2022 filings name the joint venture with an explicit legal-entity axis member.
LEGAL = {"0001803498": {"reporting_entity_suffixes": ["Emerald JV LP"],
                        "legal_entity_members": ["legalentityaxis=BCREDEmeraldJVLPMember -> Emerald JV LP"]}}


def _suffix(dims, encodings=LEGAL, cik="0001803498"):
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT ? AS cik, ? AS dims", [cik, dims])
    return con.execute("SELECT " + source_encodings.reporting_suffix_expression("cik", "dims", encodings) + " FROM t").fetchone()[0]


def test_legal_entity_axis_member_resolves_to_the_reviewed_label():
    assert _suffix("investmentidentifieraxis=Smile Doctors, LLC|legalentityaxis=BCREDEmeraldJVLPMember") == "reporting_entity=emerald jv lp"
    # same entity whether named by the member or by the bare label
    assert _suffix("investmentidentifieraxis=Smile Doctors, LLC|Emerald JV LP") == "reporting_entity=emerald jv lp"


def test_other_legal_entity_members_and_other_funds_are_untouched():
    assert _suffix("investmentidentifieraxis=Smile Doctors, LLC|legalentityaxis=SomeOtherMember") == ""
    assert _suffix("investmentidentifieraxis=BCRED Emerald JV") == ""
    assert _suffix("investmentidentifieraxis=Smile Doctors, LLC|legalentityaxis=BCREDEmeraldJVLPMember", cik="0001838126") == ""


@pytest.mark.parametrize("value", ["legalentityaxis=BCREDEmeraldJVLPMember", "BCREDEmeraldJVLPMember -> Emerald JV LP",
                                   "legalentityaxis=A|b -> Emerald JV LP", "legalentityaxis=A -> x=y"])
def test_malformed_legal_entity_member_fails(tmp_path, value):
    (tmp_path / "0001803498.json").write_text(json.dumps(
        {"schema_version": "bdc-xbrl-wrapper.v3", "cik": "0001803498",
         "source_encodings": {"legal_entity_members": [value]}}), encoding="utf-8")
    with pytest.raises(ValueError):
        source_encodings.load_encodings(tmp_path)


# --- rate facts filed on a neighbouring context with no value (decision D-020) -------------------

ARES = "0001287750"
ADOPT = {ARES: {"rate_only_contexts": ["adopt_adjacent"]}}


def _rate_rows(*rows):
    base = {"cik": ARES, "accession_number": "0001287750-24-000011", "period": "2023-12-31", "report_date": "2023-12-31",
            "fair_value": "", "cost": "", "principal_amount": "", "interest_rate": "", "basis_spread": "", "pik_rate": "",
            "src_facts": "", "dedupe_filled_fields": ""}
    return pd.DataFrame([{**base, **row} for row in rows])


def _adopt(frame, encodings=ADOPT):
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute("CREATE TABLE bdc_raw AS SELECT * FROM frame")
    counts = source_encodings.adopt_rate_only_contexts(con, encodings=encodings)
    return counts, con.execute("SELECT * FROM bdc_raw ORDER BY src_context_id").fetchdf().set_index("src_context_id")


APEX_RATE = {"src_context_id": "c-1205", "investment_identifier": "Apex Service Partners, LLC, First lien senior secured loan 1",
             "interest_rate": "0.124", "basis_spread": "0.07", "pik_rate": "0.02",
             "src_facts": '{"basis_spread":{"r":0.07},"interest_rate":{"r":0.124},"pik_rate":{"r":0.02}}'}
APEX_VALUE = {"src_context_id": "c-1206",
              "investment_identifier": "Apex Service Partners, LLC and Apex Service Partners Holdings, First lien senior secured loan",
              "fair_value": "144800000", "cost": "148500000", "principal_amount": "148500000"}


def test_rate_only_context_is_joined_to_the_adjacent_value_row_of_the_same_issuer():
    # Ares 2023-12-31, Apex Service Partners: the loan's value is on c-1206 and its rate, spread and PIK on c-1205,
    # under a slightly different member name. Printed: "12.40 % (2.00 % PIK) SOFR (Q) 7.00 % ... 148.5 148.5 144.8".
    counts, out = _adopt(_rate_rows(APEX_RATE, APEX_VALUE))
    assert counts == {ARES: 1}
    row = out.loc["c-1206"]
    assert (row["interest_rate"], row["basis_spread"], row["pik_rate"]) == ("0.124", "0.07", "0.02")
    assert set(row["dedupe_filled_fields"].split(",")) == {"interest_rate", "basis_spread", "pik_rate"}
    assert '"interest_rate"' in row["src_facts"]
    assert "c-1205" not in out.index          # the rate-only context is consumed, not left to match something else


def test_rate_only_context_is_left_alone_without_one_clear_partner():
    other_issuer = dict(APEX_VALUE, investment_identifier="Zeta Holdings, LLC, First lien senior secured loan")
    far_away = dict(APEX_VALUE, src_context_id="c-1290")
    has_rate = dict(APEX_VALUE, interest_rate="0.11")
    no_principal = dict(APEX_VALUE, principal_amount="")
    two_targets = [APEX_VALUE, dict(APEX_VALUE, src_context_id="c-1204")]
    for rows in ([APEX_RATE, other_issuer], [APEX_RATE, far_away], [APEX_RATE, has_rate], [APEX_RATE, no_principal],
                 [APEX_RATE, *two_targets]):
        counts, out = _adopt(_rate_rows(*rows))
        assert counts == {ARES: 0}, rows
        assert "c-1205" in out.index
    # a fund without the setting is never touched
    counts, out = _adopt(_rate_rows(APEX_RATE, APEX_VALUE), encodings={})
    assert counts == {} and out.loc["c-1206", "interest_rate"] == ""


@pytest.mark.parametrize('dimensions,expected', [
    # Misspelled JV labels after a comma (decision D-023). Each row's fair value is absent from the fund's printed
    # schedule and the rows sum to the fund's excess over its filed total: 2023-09-30 9,506K, 2023-12-31 10,573K,
    # 2024-12-31 43,002K. Sources: 0001803498-23-000021 c-4497 to c-4499; 0001803498-24-000007 c-4756 to c-4758;
    # 0001803498-25-000021 c-4488, c-4489, c-4497, c-4507.
    ('investmentidentifieraxis=Anticimex, Inc. , Emerald JV LP2', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Anticimex, Inc. , Emerald JV LP1', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Java Buyer, Inc, Emerald JV LP. 2', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Groundworks, LLC , Emerald JV LP1', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Howden Group Holdings Limited, Verdelite JV 2LP 1', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=Howden Group Holdings Limited, Verdelite JV 1LP 1', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=NFP Corp, Verdelite JV 2LP', 'reporting_entity=verdelite jv lp'),
    # Still the fund's own rows: its JV interest, a joint name, and a longer name that only starts like the label.
    ('investmentidentifieraxis=BCRED Emerald JV LP2', 'parent'),
    ('investmentidentifieraxis=BCRED Emerald JV LP - LP Interest', 'parent'),
    ('investmentidentifieraxis=Acme LLC and, Emerald JV LP2', 'parent'),
    ('investmentidentifieraxis=Acme LLC, Emerald JV LPX Holdings', 'parent'),
])
def test_misspelled_jv_labels_after_a_comma_are_still_the_jv_schedule(dimensions, expected):
    expression = source_encodings.reporting_suffix_expression('cik', 'dims', ENCODINGS)
    with duckdb.connect() as con:
        got = con.execute('SELECT ' + expression + ' FROM (SELECT ? AS cik, ? AS dims)', ['0001803498', dimensions]).fetchone()[0]
    assert (got or 'parent') == expected
