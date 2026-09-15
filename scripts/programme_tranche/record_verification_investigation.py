"""Retain bounded investigation evidence without changing earlier sealed records."""
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import pstats
import shutil
import threading

from pipeline.programme.core import atomic_json, now, read_json, record, sha

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'scratch/2026-09-10_verification_investigation'
OUT = ROOT/'docs/production_stack/programme_tranche_evidence_2026-09-10/verification-investigation-v1'


def reports(job):
    return [json.loads(line) for line in (BASE/job/'telemetry/reports.jsonl').read_text(encoding='utf-8').splitlines()]


def main():
    
    assert not OUT.exists(), 'Preserve previous evidence'
    job_names = ('collect-v1', 'collect-v2', 'reproduce-v1', 'repaired-v1', 'repaired-v2', 'repaired-v3', 'semantic-after-v1')
    jobs = {name: read_json(BASE/name/'result.json') for name in job_names}
    for name, result in jobs.items():
        assert result['worker_stopped'] and not result['protected_changes'], name
        assert result['canaries_preserved'] and not result['unreadable_changed'], name
    assert jobs['collect-v2']['exit_code'] == 0
    # Preserve the original launcher-only result and disclose its false zero.
    assert read_json(BASE/'reproduce-v1/telemetry/finished.json')['exit_code'] == 1
    jobs['reproduce-v1']['worker_exit_code_from_durable_record'] = 1
    jobs['reproduce-v1']['launcher_status_was_insufficient'] = True
    assert jobs['repaired-v1']['exit_code'] == 3
    assert jobs['repaired-v2']['exit_code'] != 0 and (BASE/'repaired-v2/manual_stop.json').exists()
    assert jobs['repaired-v3']['exit_code'] == jobs['repaired-v3']['worker_exit_code'] == 1
    assert jobs['repaired-v3']['junit_outcomes']['failures'] == 1
    assert jobs['repaired-v3']['junit_outcomes']['errors'] == 0
    assert jobs['semantic-after-v1']['exit_code'] == 0
    before, after = reports('reproduce-v1'), reports('repaired-v3')
    failed = [item for item in before if item['outcome'] == 'failed']
    assert len(failed) == 4
    after_failures = [item for item in after if item['outcome'] == 'failed']
    assert len(after_failures) == 1
    assert after_failures[0]['nodeid'] == 'tests/test_bdc_xbrl_wrapper_oracle.py::test_coherence_passes_all_existing_wrappers'
    before_calls = {item['nodeid']: item for item in before if item['when'] == 'call'}
    after_calls = {item['nodeid']: item for item in after if item['when'] == 'call'}
    performance = []
    for node, item in before_calls.items():
        if '::TestPrepareBdc::' not in node:
            continue
        updated = after_calls[node]
        assert item['outcome'] == updated['outcome'] == 'passed'
        performance.append(dict(nodeid=node, before_seconds=item['duration'], after_seconds=updated['duration'],
                                ratio=item['duration']/updated['duration'], instrumentation='cProfile in both runs; diagnostic timings, not an unprofiled full-suite benchmark'))
    profiles = {}
    for name in ('reproduce-v1', 'repaired-v3'):
        stats = pstats.Stats(str(BASE/name/'bundle/profile.prof'))
        rows = [dict(file=key[0], line=key[1], function=key[2], primitive_calls=value[0],
                     calls=value[1], own_seconds=value[2], cumulative_seconds=value[3])
                for key, value in stats.stats.items() if key[2] in (
                    '_prepare_bdc', 'apply_ixbrl_field_status_overlay', '_norm_text', '_raw_id_lower',
                    'read_csv', '_expand_placeholders', '_load_staging_configs', 'inventory')]
        profiles[name] = sorted(rows, key=lambda item:item['cumulative_seconds'], reverse=True)
    result = dict(recorded_utc=now(), scope='Bounded owner-requested investigation after the expired tranche; no resumption or adoption',
        original_failure_markers=4, reproduced_failures=failed,
        before_outcomes=dict(Counter(item['outcome'] for item in before if item['when']=='call')),
        repaired_outcomes=dict(Counter(item['outcome'] for item in after if item['when']=='call')),
        cache_query_tests_passed=sum(item['outcome']=='passed' and item['when']=='call' and
            item['nodeid'].split('::')[0] in ('tests/test_agent_data_query.py','tests/test_investigation_orchestration.py') for item in after),
        slow_test_comparison=performance, profile_functions=profiles, jobs=jobs,
        staging_phase_logs={node:item.get('stage_logs',[]) for node,item in after_calls.items()
                            if 'tests/test_unified_holdings.py' in node},
        broader_run_completed_outcomes=dict(Counter(item['outcome'] for item in reports('repaired-v2') if item['when']=='call')),
        broader_staging_class='Not completed: measured case durations did not fit the diagnostic budget; attempt stopped and retained, then narrowed to four representative cases.',
        production_validator='Unchanged. Fix must preserve staging preprocessing and use DuckDB for staging regexes, Python for dispatch regexes.',
        full_suite='Not rerun; original suite remains incomplete',
        semantic_scope='The bounded full byte+semantic attempt is reported separately. Completion of the five-artifact semantic comparator is not a full baseline pass.',
        full_byte_attempt=read_json(BASE/'semantic-after-v1/bundle/full_byte_attempt.json'),
        financial_measurement='Not run; all 50 programme metrics remain unmeasured',
        preservation=read_json(ROOT/'docs/production_stack/programme_tranche_evidence_2026-09-10/investigation-preservation-v1/result.json'),
        owner_comments_sha256=sha(ROOT/'docs/production_stack/programme_review_comments.md'),
        original_log_sha256=sha(ROOT/'docs/production_stack/programme_tranche_evidence_2026-09-10/test-boundary-failure-v1/process.log'))
    incident = read_json(ROOT/'docs/production_stack/programme_tranche_evidence_2026-09-10/test-boundary-failure-v1/diagnosis.json')
    result['original_cache_files'] = [record(ROOT, item['path']) for item in incident['changes']]
    assert len(result['original_cache_files']) == 6
    for item, original in zip(result['original_cache_files'], incident['changes']):
        assert item['sha256'] == original['sha256']
    assert result['owner_comments_sha256'] == '9a431d8d5b0aa8870ca031a0498665df2dc071107f0696fd85a3e8ea5ea6b267'
    assert result['original_log_sha256'] == 'a33962c7113d6504c2aed3c23ed39201fab0b04f70b9f6e1833d0262abc48cb5'
    assert result['preservation']['status'] == 'pass'
    assert not result['preservation']['semantic_changes_since_preparation']
    OUT.mkdir()
    for name in job_names:
        print('Retaining diagnostic evidence: '+name, flush=True)
        for relative in ('result.json', 'request.json', 'process.json', 'process.log', 'telemetry/canary.json',
                         'telemetry/worker.json', 'telemetry/finished.json', 'telemetry/collection.json',
                         'telemetry/reports.jsonl', 'telemetry/starts.jsonl', 'telemetry/inner-scan-1.json', 'telemetry/inner-scan-2.json',
                         'diagnose_tests.executed.py', 'manual_stop.json',
                         'bundle/full_byte_attempt.json', 'bundle/full_byte_process.log', 'bundle/full_byte_semantic_report.json',
                         'bundle/junit.xml', 'bundle/profile.txt', 'bundle/profile.prof', 'bundle/semantic_diff_report.json'):
            source = BASE/name/relative
            if source.exists():
                target = OUT/name/relative; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        for relative in ('protected_before.json', 'protected_after.json'):
            source = BASE/name/relative
            with source.open('rb') as reader, gzip.open(OUT/name/(relative+'.gz'), 'wb') as writer:
                shutil.copyfileobj(reader, writer, 1024*1024)
    for name in ('failure_mapping.json', 'wrapper_coherence.json', 'regex_dialects.json', 'regex_dialects_raw_v1.json'):
        shutil.copyfile(BASE/name, OUT/name)
    shutil.copytree(BASE/'sources-before', OUT/'sources-before')
    for relative in ('tests/conftest.py','tests/test_agent_data_query.py','tests/test_investigation_orchestration.py',
                     'tests/test_bdc_xbrl_wrapper.py','tests/test_unified_holdings.py',
                     'scripts/programme_tranche/diagnose_tests.py','scripts/programme_tranche/probe_regex_dialects.py',
                     'scripts/programme_tranche/map_test_failures.py','scripts/programme_tranche/audit_wrapper_coherence.py',
                     'scripts/programme_tranche/semantic_backstop_child.py',
                     'scripts/programme_tranche/record_verification_investigation.py'):
        target = OUT/'sources-after'/relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/relative, target)
    atomic_json(OUT/'result.json', result)
    atomic_json(OUT/'complete.json', dict(recorded_utc=now(), artifacts=[record(OUT,path.relative_to(OUT).as_posix())
        for path in sorted(OUT.rglob('*')) if path.is_file()]))
    print(json.dumps({key:result[key] for key in ('original_failure_markers','before_outcomes','repaired_outcomes',
         'cache_query_tests_passed','slow_test_comparison')}), flush=True)
    


if __name__ == '__main__':
    main()
