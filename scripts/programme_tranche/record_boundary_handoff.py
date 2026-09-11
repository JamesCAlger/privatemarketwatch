"""Preserve a stopped handoff; no pipeline, pytest, recovery or data measurement."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import difflib
import os
from pathlib import Path
import re
import shutil
import threading
import xml.etree.ElementTree as ET

from pipeline.programme.catalog import CRITERIA, METRIC_UNITS
from pipeline.programme.core import ContractError, atomic_json, digest, read_json, record, sha, verify_records
from pipeline.programme.measurement import CONTRACTS, evaluate

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'docs/production_stack/programme_tranche_evidence_2026-09-10'
SCRATCH = ROOT / 'scratch/2026-09-10_programme_tranche/verification'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--semantic', required=True)
    parser.add_argument('--preservation', required=True)
    args = parser.parse_args()
    for value in vars(args).values():
        if not value or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in value):
            raise ContractError('Use portable evidence names')
    timer = threading.Timer(180, lambda: os._exit(124)); timer.daemon = True; timer.start()
    candidate = ROOT / 'data/programme/candidates/t1-runtime-20260910-v5'
    manifest = read_json(candidate / 'snapshot.json')
    if sha(candidate / 'snapshot.json') != read_json(candidate / 'snapshot_complete.json')['manifest_sha256']:
        raise ContractError('Snapshot identity changed')
    verify_records(ROOT, [r for r in manifest['artifacts'] if r['path'].startswith('pipeline/programme/')])
    stages = {}
    for stage in ('unified', 'identity', 'evidence'):
        directory = candidate / 'attempts' / (stage + '-01')
        result, complete = read_json(directory / 'result.json'), read_json(directory / 'complete.json')
        if result['execution'] != 'complete' or complete['result_sha256'] != sha(directory / 'result.json'):
            raise ContractError('Invalid recorded stage completion: ' + stage)
        metadata = result['artifacts_metadata']
        if any(item['typed_multiset_difference'] for item in metadata.values()):
            raise ContractError('Recorded stage has a typed-pair difference')
        stages[stage] = dict(result=record(ROOT, (directory / 'result.json').relative_to(ROOT).as_posix()),
            completion=record(ROOT, (directory / 'complete.json').relative_to(ROOT).as_posix()),
            summary=read_json(directory / 'bundle/summary.json'), artifacts_metadata=metadata)
    for child, parent in (('identity', 'unified'), ('evidence', 'identity')):
        if stages[child]['summary']['parents'][parent]['result_sha256'] != stages[parent]['result']['sha256']:
            raise ContractError('Stage parent identity differs')
    identities = {name: item['result']['sha256'] for name, item in stages.items()}
    fingerprint = digest(dict(snapshot=manifest['input_fingerprint'], stages=identities))
    diagnosis_dir = EVIDENCE / 'test-boundary-failure-v1'
    verify_records(diagnosis_dir, read_json(diagnosis_dir / 'complete.json')['files'])
    diagnosis = read_json(diagnosis_dir / 'diagnosis.json')
    tests = read_json(SCRATCH / 'full-suite-v1/result.json')
    progress = ''.join(match.group(1) for line in (diagnosis_dir/'process.log').read_text(encoding='utf-8').splitlines()
                      if (match := re.fullmatch(r'([.FsxEX]+)(?:\s+\[\s*\d+%\])?', line)))
    failure_markers = progress.count('F')
    if not tests['worker_stopped'] or not tests['timed_out'] or len(tests['protected_changes']) != 6:
        raise ContractError('Unexpected full-suite stop evidence')
    focused_dir = SCRATCH / 'strengthened-preflight-tests-v2'
    focused = read_json(focused_dir / 'result.json')
    suite = ET.parse(focused_dir / 'junit.xml').getroot().find('testsuite')
    if (focused['exit_code'] or focused['timed_out'] or not focused['worker_stopped']
        or focused['protected_changes'] or int(suite.attrib['tests']) != 68
        or int(suite.attrib['errors']) or int(suite.attrib['failures'])):
        raise ContractError('Earlier focused verification is inconsistent')
    for item in diagnosis['changes']:
        if item['kind'] != 'created' or item['rows'] or sha(ROOT / item['path']) != item['sha256']:
            raise ContractError('Cache evidence changed; do not silently revise the incident')
    semantic_dir = SCRATCH / args.semantic
    semantic = read_json(semantic_dir / 'result.json')
    preservation_dir = EVIDENCE / args.preservation
    preservation = read_json(preservation_dir / 'result.json')
    if (not semantic['worker_stopped'] or semantic['timed_out'] or semantic['exit_code'] not in (0, 1)
        or semantic['protected_changes'] or semantic['protected_unreadable_paths_changed']
        or not semantic['code_unchanged'] or preservation['status'] != 'pass'):
        raise ContractError('Read-only preservation remains unresolved')
    if preservation['semantic_report'] != record(ROOT, (semantic_dir / 'semantic_diff_report.json').relative_to(ROOT).as_posix()):
        raise ContractError('Preservation report mismatch')
    output = EVIDENCE / 'handoff-boundary-v1'
    output.mkdir(parents=True, exist_ok=False)
    print('Recording completed stages and stopped verification; no data measurement', flush=True)
    for source, target in ((semantic_dir / 'result.json', 'semantic_result.json'),
        (semantic_dir / 'semantic_diff_report.json', 'semantic_diff_report.json'),
        (preservation_dir / 'result.json', 'preservation.json')):
        shutil.copy2(source, output / target)
    initial_semantic = SCRATCH / 'boundary-semantic-v1/result.json'
    if args.semantic != 'boundary-semantic-v1' and initial_semantic.exists():
        shutil.copy2(initial_semantic, output / 'full_byte_semantic_attempt.json')
    atomic_json(output / 'stage_records.json', stages)
    fix_dir = EVIDENCE / 'test-boundary-fix-v1'
    for before in read_json(fix_dir / 'before_sources.json'):
        if sha(fix_dir / before['saved']) != before['sha256']:
            raise ContractError('Original test-fix source copy changed')
        if before['path'].startswith(('pipeline/', 'scripts/')) and sha(ROOT / before['path']) != before['sha256']:
            raise ContractError('Production query source changed during test-only fix')
    fix_files = ['tests/conftest.py', 'tests/test_agent_data_query.py', 'tests/test_investigation_orchestration.py']
    patch = []
    for relative in fix_files:
        path = ROOT / relative
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=relative)
        old = (fix_dir / relative.replace('/', '__')).read_text(encoding='utf-8-sig')
        patch.extend(difflib.unified_diff(old.splitlines(keepends=True), path.read_text(encoding='utf-8-sig').splitlines(keepends=True),
                                        fromfile='before/' + relative, tofile='prepared/' + relative))
        shutil.copy2(path, fix_dir / ('prepared__' + relative.replace('/', '__')))
    (fix_dir / 'prepared.diff').write_text(''.join(patch), encoding='utf-8')
    atomic_json(fix_dir / 'status.json', dict(status='prepared_untested', syntax='AST parse only',
        files=[record(ROOT, name) for name in fix_files], new_tests=1, tests_executed_after_stop=0))
    atomic_json(fix_dir / 'complete.json', dict(status='untested_fix_review_record',
        artifacts=[record(fix_dir, path.name) for path in sorted(fix_dir.iterdir()) if path.is_file()]))
    evaluation_dir = EVIDENCE / 'evaluation-boundary-v1'
    evaluation_dir.mkdir(parents=True, exist_ok=False)
    reason = 'Not executed: protected test-cache writes stopped the tranche after the three candidate stages completed.'
    observations = {metric: dict(schema_version=1, metric_id=metric, metric_version=1,
        candidate_fingerprint=fingerprint, scope='cohort_70_required_history', quarter=None,
        design='unmeasured', denominator_known=False, eligible=0, assessed=0, missing_weight=0,
        value=None, unit=METRIC_UNITS[metric], formula='No candidate measurement executed',
        evidence=[], references=[], reason=reason)
        for _, metrics in CRITERIA.values() for metric in metrics}
    criteria = evaluate(read_json(CONTRACTS / 'working-v1.json'), observations, fingerprint, ROOT)
    metrics = [metric for criterion in criteria['criteria'] for metric in criterion['results']]
    if len(criteria['criteria']) != 28 or len(metrics) != 50 or any(m['status'] != 'UNMEASURED' for m in metrics):
        raise ContractError('Stopped inventory must contain all 50 unmeasured metrics')
    atomic_json(evaluation_dir / 'observations.json', observations)
    atomic_json(evaluation_dir / 'criterion_results.json', criteria)
    atomic_json(evaluation_dir / 'execution.json', dict(status='stopped_protected_output',
        complete_candidate_stages=True, engineering_tranche_complete=False, financial_measurement_executed=False,
        candidate_fingerprint=fingerprint, snapshot=manifest['input_fingerprint'], stages=identities,
        meaning='Status inventory only; no financial evaluation workload ran'))
    atomic_json(evaluation_dir / 'evaluation_manifest.json', dict(status='stopped_result_inventory_only',
        candidate_fingerprint=fingerprint, stages=identities,
        files=[record(evaluation_dir, path.name) for path in sorted(evaluation_dir.iterdir()) if path.is_file()]))
    summary = dict(execution_status='stopped_protected_output', engineering_tranche_complete=False,
        created_utc=datetime.now(timezone.utc).isoformat(), candidate=candidate.name, candidate_fingerprint=fingerprint,
        summary=f'All three isolated candidate stages completed. Full pytest timed out with {failure_markers} failure markers and six new empty protected query-cache files. The tranche is stopped. At this original handoff the test-isolation fix was prepared but untested; integrated measurement and recovery did not run.',
        stages=stages, stage_record_scope='Completion/result identities and recorded typed-pair checks; the large output bundles were verified when sealed, not rehashed by this handoff writer.',
        focused_tests=dict(passed=68, seconds=float(suite.attrib['time']),
            evidence=record(ROOT, (focused_dir / 'result.json').relative_to(ROOT).as_posix()),
            timing='Before the full suite; does not verify the later test-isolation fix'),
        full_suite=dict(exit_code=tests['exit_code'], timed_out=True, elapsed_seconds=tests['elapsed_seconds'],
            worker_stopped=True, observed_failure_markers=failure_markers, final_traceback_available=False, final_junit_available=False,
            progress='Approximately 79%; incomplete run, no final test counts'),
        incident=dict(created_empty_cache_files=6, bytes=9580, unchanged_existing_size_mtime_files=237621,
            all_protected_content_hashed=False, removed_files=0, cleanup='Automatic approval review rejected removal: blocked by policy; files remain',
            diagnosis=record(ROOT, (diagnosis_dir / 'complete.json').relative_to(ROOT).as_posix())),
        preservation=preservation, semantic_job=semantic, recovery='Not run', integrated_measurement='Not run',
        product_acceptance=dict(criteria=28, metrics=50, metric_status_counts=dict(Counter(m['status'] for m in metrics))),
        references=dict(dispositions=61, label_proposals=20, independently_reviewed=0), remediation_packets=4,
        production_adoption=False, sec_requests=0, paid_calls=0,
        fix=record(ROOT, (fix_dir / 'complete.json').relative_to(ROOT).as_posix()),
        next_work='Resolve the stop; verify test isolation and identify the earlier failure, finish full-suite verification, then measure/recover the existing sealed candidate after validating its identities.')
    atomic_json(output / 'verification.json', summary)
    atomic_json(output / 'complete.json', dict(status='stopped_handoff_recorded; engineering incomplete',
        artifacts=[record(output, path.name) for path in sorted(output.iterdir()) if path.is_file()],
        evaluation=record(ROOT, (evaluation_dir / 'evaluation_manifest.json').relative_to(ROOT).as_posix()),
        code=record(ROOT, Path(__file__).relative_to(ROOT).as_posix())))
    timer.cancel()
    print('Stopped handoff recorded; all 50 metrics remain unmeasured', flush=True)


if __name__ == '__main__':
    main()
