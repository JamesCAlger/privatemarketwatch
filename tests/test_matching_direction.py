"""A middle observation can close one quarter and open the next."""
import duckdb
import pytest
from pipeline.position_matching import _match_entity_fingerprint

def run_tier_e(claims, changes=None, tier_a=(), extra_scope=None):
    records = [dict(uid=i, quarter=q, date=d, scope='100|parent',
                    entity='entity-1', maturity='2028-01-12', subtype='TERM_LOAN',
                    fv=100.0, pa=1000000.0) for i, q, d in
               [(1, '2025q2', '2025-06-30'), (2, '2025q3', '2025-09-30'),
                (3, '2025q4', '2025-12-31')]]
    for uid, fields in (changes or {}).items():
        records[uid - 1].update(fields)
    if extra_scope is not None:
        records.extend([dict(r, uid=r['uid']+3, scope=extra_scope, pa=r['pa']+10000000)
                        for r in records[:3]])
    with duckdb.connect(config={'threads': 1, 'memory_limit': '256MB'}) as con:
        con.execute('''CREATE TABLE unified_base(_row_id BIGINT, cik VARCHAR,
            source VARCHAR,entity_name VARCHAR,issuer_name VARCHAR,quarter VARCHAR,
            report_date DATE,entity_id VARCHAR,index_classification VARCHAR,
            _accounting_scope VARCHAR,_inst_subtype VARCHAR,_mat_low DATE,_mat_high DATE,
            fv DOUBLE,pa DOUBLE,cost_val DOUBLE,ir DOUBLE,bs DOUBLE,sh DOUBLE)''')
        con.executemany('INSERT INTO unified_base VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', [
            (r['uid'], '100', 'bdc', 'Fund', 'Name-' + str(r['uid']), r['quarter'], r['date'],
             r['entity'], 'DIRECT_LENDING', r['scope'], r['subtype'], r['maturity'], r['maturity'],
             r['fv'], r['pa'], 100, None, 1, None) for r in records])
        for table in ('tier_b', 'tier_c', 'tier_d'):
            con.execute('CREATE TABLE ' + table + '(_begin_row_id BIGINT,_end_row_id BIGINT)')
        if claims:
            con.executemany('INSERT INTO tier_b VALUES (?,?)', claims)
        con.execute('CREATE TABLE tier_a_unified_ids(_row_id BIGINT)')
        if tier_a:
            con.executemany('INSERT INTO tier_a_unified_ids VALUES (?)', [(i,) for i in tier_a])
        _match_entity_fingerprint(con)
        return set(con.execute('SELECT _begin_row_id,_end_row_id FROM tier_e').fetchall())


@pytest.mark.parametrize('claims,tier_a,expected', [
    ([], (), {(1, 2), (2, 3)}),
    ([(2, 3)], (), {(1, 2)}),
    ([(1, 2)], (), {(2, 3)}),
    ([(1, 2), (2, 3)], (), set()),
    ([], (2,), {(2, 3)}),
])
def test_incoming_and_outgoing_continuity_are_independent_slots(claims, tier_a, expected):
    assert run_tier_e(claims, tier_a=tier_a) == expected


@pytest.mark.parametrize('changed', [
    {'scope': '100|child'}, {'entity': 'entity-2'},
    {'maturity': '2031-01-12'}, {'subtype': 'REVOLVER'},
])
def test_restored_incoming_slot_still_requires_compatible_position(changed):
    assert run_tier_e([(2, 3)], {1: changed}) == set()


@pytest.mark.parametrize('extra_scope,expected', [
    ('100|child', {(1, 2), (2, 3), (4, 5), (5, 6)}),
    ('100|parent', set()),
])
def test_other_accounting_scopes_do_not_change_within_scope_position_counts(extra_scope, expected):
    # Each scope has one position per quarter. Principal changes outside the
    # bucket tolerance still permit the single-position tier. Two positions in the SAME
    # scope remain ambiguous and must retain the multi-position bucket test.
    assert run_tier_e([], {2: {'pa': 2000000}}, extra_scope=extra_scope) == expected


from pipeline.position_matching import _slot_availability_ctes


def test_slot_helper_claims_tier_a_on_end_side_only():
    with duckdb.connect() as con:
        con.execute('CREATE TABLE tier_a_unified_ids(_row_id BIGINT)')
        con.execute('INSERT INTO tier_a_unified_ids VALUES (7)')
        con.execute('CREATE TABLE tier_b(_begin_row_id BIGINT,_end_row_id BIGINT)')
        con.execute('INSERT INTO tier_b VALUES (1,2)')
        con.execute('CREATE TABLE tier_c(_begin_row_id BIGINT,_end_row_id BIGINT)')
        con.execute('INSERT INTO tier_c VALUES (3,4)')
        sql = 'WITH ' + _slot_availability_ctes(('tier_b', 'tier_c'))
        begins = {r[0] for r in con.execute(sql + ' SELECT _row_id FROM used_begin').fetchall()}
        ends = {r[0] for r in con.execute(sql + ' SELECT _row_id FROM used_end').fetchall()}
    assert begins == {1, 3}
    assert ends == {2, 4, 7}


def test_slot_helper_with_no_prior_tiers_only_claims_tier_a_ends():
    with duckdb.connect() as con:
        con.execute('CREATE TABLE tier_a_unified_ids(_row_id BIGINT)')
        con.execute('INSERT INTO tier_a_unified_ids VALUES (9)')
        sql = 'WITH ' + _slot_availability_ctes(())
        assert con.execute(sql + ' SELECT count(*) FROM used_begin').fetchone()[0] == 0
        assert con.execute(sql + ' SELECT _row_id FROM used_end').fetchall() == [(9,)]
