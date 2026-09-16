"""A named empty quarter requires verified cash-only primary-source evidence."""
from copy import deepcopy
import json

import duckdb
import pytest

from pipeline import public_cash_status
from pipeline.context_inventory import CASH_ONLY_PUBLIC_WORDING
from pipeline.delivery_coverage import load_history
from pipeline.holdings_finalizer import project_artifact
from pipeline.holdings_history import export_history
from pipeline.programme.core import ContractError, sha
from tests.test_holdings_finalizer import holdings


CIK = '0001930087'
QUARTER = '2023-06-30'
ACCESSION = '0001930087-23-000010'


def source_result(digest):
    return dict(cik=CIK, quarter=QUARTER, sha256=digest, source_complete=True,
                target_instant_contexts=14, document_period_ends=[QUARTER],
                counts=dict(confirmed_position=0, unresolved=0, aggregate=2),
                cash_only_contexts=True, cash_equivalent_status='reported',
                cash_equivalent_total='650323000')


@pytest.mark.parametrize('change', [
    {'source_complete': False}, {'target_instant_contexts': 0},
    {'document_period_ends': ['2023-09-30']},
    {'counts': {'confirmed_position': 1, 'unresolved': 0}},
    {'counts': {'confirmed_position': 0, 'unresolved': 1}},
    {'cash_only_contexts': False}, {'cash_equivalent_status': 'unknown'},
    {'cash_equivalent_total': '0'}, {'cash_equivalent_total': 'NaN'},
    {'cash_equivalent_total': '-1'}, {'sha256': 'b' * 64},
])
def test_incomplete_or_conflicting_source_cannot_be_called_cash_only(change):
    observed = {**source_result('a' * 64), **change}
    with pytest.raises(ValueError):
        public_cash_status.verify_cash_only(observed, cik=CIK, quarter=QUARTER, source_sha256='a' * 64)


@pytest.fixture
def source_package(tmp_path, monkeypatch):
    cache = tmp_path / 'xbrl'
    source = cache / str(int(CIK)) / (ACCESSION.replace('-', '') + '.xml')
    source.parent.mkdir(parents=True)
    source.write_text('<fixture/>', encoding='utf-8')
    digest = sha(source)
    reference = tmp_path / 'cash_only_quarters.json'
    reference.write_text(json.dumps(dict(schema_version='cash-only-quarter-exceptions.v1', records=[
        dict(cik=CIK, quarter=QUARTER, accession=ACCESSION, source_sha256=digest,
             decision='D11 source-backed fixture')
    ])), encoding='utf-8')
    monkeypatch.setattr(public_cash_status, 'scan_instance',
                        lambda path, cik, quarter: source_result(digest))
    return cache, source, reference


def export(tmp_path, source_package, rows=None):
    cache, _, reference = source_package
    path = tmp_path / 'holdings.csv'
    project_artifact(holdings(rows), 'private_markets_holdings.csv').to_csv(path, index=False)
    history = tmp_path / 'history'
    with duckdb.connect() as con:
        manifest = export_history(con, path, history, cohort={CIK, '0000000123'}, release_id='R',
                                  cash_status_reference=reference, xbrl_cache=cache)
    return history, manifest


def test_verified_cash_only_quarter_is_accessible_without_a_fabricated_position(tmp_path, source_package):
    history, manifest = export(tmp_path, source_package)
    payload = json.loads((history / CIK / (QUARTER + '.json')).read_text())
    assert payload['rows'] == []
    assert payload['source_status']['message'] == CASH_ONLY_PUBLIC_WORDING
    assert manifest['rows'] == 1 and manifest['accessible_holdings_difference'] == 0
    with duckdb.connect() as con:
        load_history(con, history)
        assert con.execute('SELECT count(*) FROM delivery_rows').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM delivery_quarters').fetchone()[0] == 2


def test_changed_source_cannot_establish_the_exception(tmp_path, source_package):
    _, source, _ = source_package
    source.write_text('<changed/>', encoding='utf-8')
    with pytest.raises(ValueError, match='source changed'):
        export(tmp_path, source_package)


def test_real_positions_suppress_the_empty_quarter_exception(tmp_path, source_package, monkeypatch):
    def should_not_scan(*args):
        raise AssertionError('Existing positions must not be labelled as a source exception')
    monkeypatch.setattr(public_cash_status, 'scan_instance', should_not_scan)
    history, manifest = export(tmp_path, source_package, [dict(cik=CIK, report_date=QUARTER)])
    assert manifest['source_statuses'] == []
    payload = json.loads((history / CIK / (QUARTER + '.json')).read_text())
    assert len(payload['rows']) == 1 and 'source_status' not in payload


@pytest.mark.parametrize('field,value', [
    ('cik', '0000000123'), ('release_id', 'other'), ('quarter', '2023-09-30'),
    ('source_status', None),
])
def test_empty_payload_identity_is_checked_even_when_its_hash_is_updated(
        tmp_path, source_package, field, value):
    history, _ = export(tmp_path, source_package)
    path = history / CIK / (QUARTER + '.json')
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload), encoding='utf-8')
    index_path = path.parent / 'index.json'
    index = json.loads(index_path.read_text())
    index['quarters'][0]['sha256'] = sha(path)
    index_path.write_text(json.dumps(index), encoding='utf-8')
    with duckdb.connect() as con, pytest.raises(ContractError):
        load_history(con, history)
