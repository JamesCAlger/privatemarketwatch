"""Candidate safety contracts: stale results must never become successful stages."""
from pathlib import Path
import json
import os

import duckdb
import pytest

from pipeline.programme.artifacts import finalize_pair, verify_pair, verify_audit
from pipeline.programme.core import (ContractError, atomic_json, contained, identity,
                                     read_stage, seal, sha, record, verify_records)


def stage(tmp_path):
    (tmp_path / 'bundle').mkdir()
    (tmp_path / 'bundle/required.csv').write_text('x\n1\n')
    expected = identity('fixture', 'source', 'runtime', 'schema', {}, {'network': False})
    atomic_json(tmp_path / 'process_result.json', dict(exit_code=0, worker_stopped=True,
                input_fingerprint=expected['fingerprint']))
    return expected


def test_completed_stage_reuses_only_same_dependencies(tmp_path):
    expected = stage(tmp_path)
    seal(tmp_path, expected, ['required.csv'])
    assert read_stage(tmp_path, expected, ['required.csv'])['execution'] == 'complete'
    for field in ('snapshot', 'runtime', 'artifact_contract', 'parents', 'controls'):
        changed = dict(expected, **{field: 'changed'})
        with pytest.raises(ContractError):
            read_stage(tmp_path, changed, ['required.csv'])


@pytest.mark.parametrize('exit_code,stopped', [(1, True), (0, False), (None, True)])
def test_failed_or_live_worker_cannot_seal(tmp_path, exit_code, stopped):
    expected = stage(tmp_path)
    atomic_json(tmp_path / 'process_result.json', dict(exit_code=exit_code, worker_stopped=stopped,
                input_fingerprint=expected['fingerprint']))
    with pytest.raises(ContractError):
        seal(tmp_path, expected, ['required.csv'])
    assert not (tmp_path / 'complete.json').exists()


def test_partial_companion_and_unexpected_artifact_block_completion(tmp_path):
    expected = stage(tmp_path)
    with pytest.raises(ContractError):
        seal(tmp_path, expected, ['required.csv', 'required.parquet'])
    (tmp_path / 'bundle/surprise.json').write_text('{}')
    with pytest.raises(ContractError):
        seal(tmp_path, expected, ['required.csv'])


def test_changed_result_or_content_cannot_resume(tmp_path):
    expected = stage(tmp_path)
    seal(tmp_path, expected, ['required.csv'])
    (tmp_path / 'bundle/required.csv').write_text('x\n2\n')
    with pytest.raises(ContractError):
        read_stage(tmp_path, expected, ['required.csv'])
    with pytest.raises(ContractError):
        seal(tmp_path, expected, ['required.csv'])


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'C:/absolute', 'a/../b', 'a//b', './file', 'a\\b'])
def test_unportable_or_escaping_paths_rejected(tmp_path, path):
    with pytest.raises(ContractError):
        contained(tmp_path, path, existing=False)


def test_hardlink_cannot_alias_a_protected_file(tmp_path):
    original = tmp_path / 'original'
    original.write_text('keep')
    os.link(original, tmp_path / 'alias')
    with pytest.raises(ContractError):
        contained(tmp_path, 'alias')


def test_empty_required_artifact_gets_complete_typed_companion(tmp_path):
    path = tmp_path / 'entity_lookup.csv'
    path.write_text('entity_id,canonical_name,normalized_name,issuer_name_variant,source,occurrence_count,cluster_method,cusip,lei\n')
    with duckdb.connect() as connection:
        assert finalize_pair(path, connection)['rows'] == 0
        schema = connection.execute('DESCRIBE SELECT * FROM read_parquet(?)', [str(path.with_suffix('.parquet'))]).fetchall()
        assert schema[5][:2] == ('occurrence_count', 'BIGINT')


def test_auxiliary_bad_numeric_value_fails_instead_of_becoming_null(tmp_path):
    path = tmp_path / 'entity_lookup.csv'
    path.write_text('entity_id,canonical_name,normalized_name,issuer_name_variant,source,occurrence_count,cluster_method,cusip,lei\nE1,A,A,A,bdc,not-a-count,exact,,\n')
    with duckdb.connect() as connection, pytest.raises(duckdb.Error):
        finalize_pair(path, connection)


def test_parquet_duplicate_multiplicity_is_validated(tmp_path):
    path = tmp_path / 'entity_lookup.csv'
    path.write_text('entity_id,canonical_name,normalized_name,issuer_name_variant,source,occurrence_count,cluster_method,cusip,lei\nE1,A,A,A,bdc,1,exact,,\nE1,A,A,A,bdc,1,exact,,\n')
    with duckdb.connect() as connection:
        finalize_pair(path, connection)
        connection.execute('CREATE TABLE altered AS SELECT DISTINCT * FROM read_parquet(?)', [str(path.with_suffix('.parquet'))])
        connection.execute("COPY altered TO '" + path.with_suffix('.parquet').as_posix() + "' (FORMAT PARQUET)")
        with pytest.raises(ContractError):
            verify_pair(path, connection)


@pytest.mark.parametrize('layer', ['raw_bdc_staging', 'layer_c', 'agent_b2'])
def test_any_admitted_rule_execution_error_blocks_seal(tmp_path, layer):
    path = tmp_path / 'agent_fix_application_audit.csv'
    header = 'layer,cik,rule_id,rule_type,status,rows_changed,fv_affected,authoring_rows,authoring_fv,drift,message\n'
    path.write_text(header + layer + ',123,rule,fixture,error,0,0,,,,failed\n')
    with duckdb.connect() as connection, pytest.raises(ContractError):
        verify_audit(path, connection)


def test_no_match_rule_is_not_an_execution_error(tmp_path):
    path = tmp_path / 'agent_fix_application_audit.csv'
    path.write_text('layer,cik,rule_id,rule_type,status,rows_changed,fv_affected,authoring_rows,authoring_fv,drift,message\nlayer,123,rule,fixture,no_rows,0,0,,,,\n')
    with duckdb.connect() as connection:
        verify_audit(path, connection)


def test_no_unknown_artifact_inference(tmp_path):
    path = tmp_path / 'unknown.csv'
    path.write_text('x\n1\n')
    with duckdb.connect() as connection, pytest.raises(ContractError):
        finalize_pair(path, connection)


def test_new_undeclared_input_cannot_reuse_a_frozen_snapshot(tmp_path):
    (tmp_path / 'input.csv').write_text('x\n1\n')
    records = [record(tmp_path, 'input.csv')]
    verify_records(tmp_path, records, exact=True)
    (tmp_path / 'override.json').write_text('{"new": true}')
    with pytest.raises(ContractError):
        verify_records(tmp_path, records, exact=True)


def test_output_writes_do_not_hide_new_readonly_inputs(tmp_path):
    (tmp_path / 'code.py').write_text('pass')
    records = [record(tmp_path, 'code.py')]
    (tmp_path / 'data/output').mkdir(parents=True)
    (tmp_path / 'data/output/result.csv').write_text('result')
    verify_records(tmp_path, records, exact=True, ignored_prefixes=('data/output/',))
    (tmp_path / 'extra.py').write_text('pass')
    with pytest.raises(ContractError):
        verify_records(tmp_path, records, exact=True, ignored_prefixes=('data/output/',))
