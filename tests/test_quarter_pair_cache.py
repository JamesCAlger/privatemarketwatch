"""A successful pair check can be reused only for the same verified bytes."""
import json

import duckdb
import pytest

from pipeline.output_schemas import OUTPUT_SCHEMAS
from pipeline.programme import artifacts
from pipeline.programme.core import ContractError, sha
from pipeline.quarter_evidence import Evidence, collect_pairs

NAME = 'position_id_edges.csv'


def package(tmp_path, label='first'):
    csv = tmp_path / NAME
    parquet = csv.with_suffix('.parquet')
    schema = OUTPUT_SCHEMAS[NAME]
    columns = ','.join(('CAST(' + ("'" + label + "'" if index == 0 else 'NULL') +
        ' AS ' + kind + ') AS "' + name + '"') for index, (name, kind) in enumerate(schema.items()))
    with duckdb.connect() as con:
        con.execute('CREATE TABLE fixture AS SELECT ' + columns)
        con.execute('COPY fixture TO ? (HEADER)', [str(csv)])
        con.execute('COPY fixture TO ? (FORMAT PARQUET)', [str(parquet)])
    holdings = tmp_path / 'holdings.csv'
    holdings.write_text('row_id\nr1\n', encoding='utf-8')
    manifest = tmp_path / 'evidence.json'
    manifest.write_text(json.dumps(dict(holdings_sha256=sha(holdings), files={p.name:
        dict(path=p.name, sha256=sha(p), holdings_sha256=sha(holdings)) for p in (csv, parquet)})), encoding='utf-8')
    return manifest, holdings


def test_success_is_reused_but_changed_bytes_require_an_actual_new_comparison(tmp_path, monkeypatch):
    manifest, holdings = package(tmp_path)
    calls, cache = [], set()
    original = artifacts.verify_pair

    def counted(path, con):
        calls.append(path)
        return original(path, con)

    monkeypatch.setattr(artifacts, 'verify_pair', counted)
    with duckdb.connect() as con:
        for _ in range(2):
            evidence = Evidence(manifest, holdings)
            result = {}
            collect_pairs(con, evidence, result, cache=cache)
            evidence.verify()
            assert result['companion_parity']['details']['verified'] == [NAME]
            assert not result['companion_parity']['assessable']  # The other ten remain missing.
        assert len(calls) == 1
        package(tmp_path, 'second')
        evidence = Evidence(manifest, holdings)
        collect_pairs(con, evidence, {}, cache=cache)
        evidence.verify()
        assert len(calls) == 2


def test_changed_source_cannot_reuse_old_manifest_hash(tmp_path):
    manifest, holdings = package(tmp_path)
    cache = set()
    with duckdb.connect() as con:
        collect_pairs(con, Evidence(manifest, holdings), {}, cache=cache)
        (tmp_path / NAME).write_text('altered', encoding='utf-8')
        with pytest.raises(ContractError, match='changed'):
            Evidence(manifest, holdings)


def test_failed_comparison_is_retried_and_not_cached(tmp_path, monkeypatch):
    manifest, holdings = package(tmp_path)
    cache = set()
    original = artifacts.verify_pair

    def fail(path, con):
        raise ContractError('Deliberate pair mismatch')

    with duckdb.connect() as con:
        monkeypatch.setattr(artifacts, 'verify_pair', fail)
        result = {}
        collect_pairs(con, Evidence(manifest, holdings), result, cache=cache)
        assert result['companion_parity']['actual'] == 1 and not cache
        monkeypatch.setattr(artifacts, 'verify_pair', original)
        result = {}
        collect_pairs(con, Evidence(manifest, holdings), result, cache=cache)
        assert result['companion_parity']['actual'] == 0 and len(cache) == 1
