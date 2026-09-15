"""Preserve a bounded, read-only diagnosis of the full-suite output violation."""
import gzip
import os
from pathlib import Path
import shutil
import threading

import duckdb
from pipeline.programme.core import ContractError, atomic_json, read_json, record, sha
from pipeline.programme.artifacts import literal

ROOT = Path(__file__).resolve().parents[2]
JOB = ROOT / 'scratch/2026-09-10_programme_tranche/verification/full-suite-v1'
OUT = ROOT / 'docs/production_stack/programme_tranche_evidence_2026-09-10/test-boundary-failure-v1'


def main():
    
    print('Read-only boundary diagnosis: two inventories and at most six small cache files', flush=True)
    result = read_json(JOB / 'result.json')
    if not result['worker_stopped'] or result['protected_unreadable_paths_changed']:
        raise ContractError('Worker or unreadable-path status unresolved')
    before = read_json(JOB / 'protected_before.json')['records']
    after = read_json(JOB / 'protected_after.json')['records']
    changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    if changed != result['protected_changes'] or len(changed) != 6:
        raise ContractError('Unexpected protected-file change set')
    if any(not p.startswith(('data/output/agent_investigate/_qcache/666/',
                              'data/output/agent_investigate/_qcache/999/')) for p in changed):
        raise ContractError('Change outside the diagnosed test-cache paths')
    OUT.mkdir(parents=True, exist_ok=False)
    con = duckdb.connect(); con.execute('SET threads=1'); con.execute("SET memory_limit='-1'")
    changes = []
    for relative in changed:
        path = ROOT / relative
        if not path.exists() or path.stat().st_size > 1_000_000:
            raise ContractError('Missing or oversized cache artifact')
        info = path.stat()
        if [info.st_size, info.st_mtime_ns] != after[relative]:
            raise ContractError('Cache changed after verification')
        saved = OUT / 'cache_files' / path.parent.name / path.name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        rows = con.execute('SELECT count(*) FROM read_parquet(' + literal(path.as_posix()) + ')').fetchone()[0]
        changes.append(dict(path=relative, before=before.get(relative), after=after[relative],
            kind='created' if relative not in before else 'changed', rows=rows,
            sha256=sha(path), saved=record(OUT, saved.relative_to(OUT).as_posix())))
    con.close()
    for name in ('protected_before.json', 'protected_after.json'):
        with (JOB / name).open('rb') as source, (OUT / (name + '.gz')).open('wb') as target:
            with gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0) as compressed:
                shutil.copyfileobj(source, compressed, length=1024*1024)
    for name in ('result.json', 'process.json', 'process.log', 'resources.json'):
        shutil.copy2(JOB / name, OUT / name)
    atomic_json(OUT / 'diagnosis.json', dict(status='tranche_stopped_protected_output_write',
        test_worker_stopped=True, tests_timed_out=result['timed_out'], changes=changes,
        unchanged_existing_files=sum(p in after and before[p] == after[p] for p in before),
        deleted_files=sorted(before.keys()-after.keys()),
        scope='All reported changes are these cache files; no other protected file size/mtime changed. This is not a content-hash proof of every production file.',
        mechanism='agent_data_query._ensure_cik_cache uses DuckDB COPY TO before locking external access. Its module-level cache root was not isolated by pytest.',
        pipeline_candidate='Three stages remain sealed; no integrated measurement or recovery claim',
        cleanup='Not performed by this read-only diagnostic',
        source_files=[record(ROOT, p) for p in ('pipeline/agent_data_query.py', 'tests/conftest.py',
            'scripts/programme_tranche/run_verification.py')]))
    atomic_json(OUT / 'complete.json', dict(status='forensic_record_complete',
        files=[record(OUT,p.relative_to(OUT).as_posix()) for p in sorted(OUT.rglob('*')) if p.is_file()]))
    
    print('Preserved six cache artifacts; created=' + str(sum(c['kind']=='created' for c in changes))
          + '; total rows=' + str(sum(c['rows'] for c in changes)), flush=True)


if __name__ == '__main__':
    main()
