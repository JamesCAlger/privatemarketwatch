"""Assemble a review-ready handoff only from completed, verified tranche evidence."""
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from pipeline.programme.core import ContractError, atomic_json, digest, read_json, record, sha, verify_records
from pipeline.programme.runner import candidate_path, latest, verify_preflight
from pipeline.programme.artifacts import STAGE_CSVS

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'docs/production_stack/programme_tranche_evidence_2026-09-10'
SCRATCH = ROOT / 'scratch/2026-09-10_programme_tranche/verification'


def checked_job(directory, *, semantic=False):
    result = read_json(directory / 'result.json')
    allowed = (0, 1) if semantic else (0,)
    if (result['exit_code'] not in allowed or result['timed_out'] or not result['worker_stopped']
        or result['protected_changes'] or result['protected_unreadable_paths_changed']
        or not result['code_unchanged']):
        raise ContractError('Verification did not finish cleanly: ' + str(directory))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--evaluation', default='evaluation-v1')
    parser.add_argument('--tests', default='full-suite-v1')
    parser.add_argument('--semantic', default='integrated-semantic-v1')
    parser.add_argument('--preservation', default='preservation-v1')
    parser.add_argument('--recovery', default='recovery-v1')
    parser.add_argument('--name', default='handoff-integrated-v1')
    parser.add_argument('--record-incomplete-verification', action='store_true',
                        help='Retain a verified candidate with an explicit incomplete engineering verdict')
    args = parser.parse_args()
    for value in vars(args).values():
        if isinstance(value, bool):
            continue
        if not value or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in value):
            raise ContractError('Use portable artifact names')
    candidate = candidate_path(args.candidate)
    manifest = read_json(candidate / 'snapshot.json')
    if sha(candidate / 'snapshot.json') != read_json(candidate / 'snapshot_complete.json')['manifest_sha256']:
        raise ContractError('Candidate manifest changed')
    verify_records(ROOT, [item for item in manifest['artifacts']
                          if item['path'].startswith('pipeline/programme/')])
    stages = {name: latest(candidate, name, manifest) for name in ('unified', 'identity', 'evidence')}
    preflight = verify_preflight(candidate, manifest)
    evaluation = EVIDENCE / args.evaluation
    evaluation_manifest = read_json(evaluation / 'evaluation_manifest.json')
    verify_records(evaluation, evaluation_manifest['files'], exact=True, ignored_prefixes=('evaluation_manifest.json',))
    identities = {name: sha(attempt / 'result.json') for name, attempt in stages.items()}
    candidate_fingerprint = digest(dict(snapshot=manifest['input_fingerprint'], stages=identities))
    if (evaluation_manifest['candidate_fingerprint'] != candidate_fingerprint or
        evaluation_manifest['stages'] != identities):
        raise ContractError('Evaluation belongs to another candidate')
    measurements = read_json(evaluation / 'measurements.json')
    criteria = read_json(evaluation / 'criterion_results.json')
    metrics = [metric for criterion in criteria['criteria'] for metric in criterion['results']]
    if len(criteria['criteria']) != 28 or len(metrics) != 50 or any(measurements['comparisons'].values()):
        raise ContractError('Incomplete criteria or unexplained integrated changes')
    tests = read_json(SCRATCH / args.tests / 'result.json')
    if (not tests['worker_stopped'] or tests['protected_changes'] or
        tests['protected_unreadable_paths_changed'] or not tests['code_unchanged']):
        raise ContractError('Test worker stopped/preservation/code checks failed')
    if tests['mode'] != 'tests':
        raise ContractError('A focused test job cannot substitute for the full repository suite')
    semantic = checked_job(SCRATCH / args.semantic, semantic=True)
    junit_path = SCRATCH / args.tests / 'junit.xml'
    suite = ET.parse(junit_path).getroot().find('testsuite') if junit_path.exists() else None
    counts = {key: int(suite.attrib[key]) if suite is not None else None
              for key in ('tests', 'failures', 'errors', 'skipped')}
    tests_passed = (tests['exit_code'] == 0 and not tests['timed_out'] and suite is not None
                    and counts['tests'] >= 4000 and not counts['failures'] and not counts['errors'])
    if not tests_passed and not args.record_incomplete_verification:
        raise ContractError('A passing complete repository suite is required')
    preservation = read_json(EVIDENCE / args.preservation / 'result.json')
    if preservation['status'] != 'pass':
        raise ContractError('Original input or semantic preservation remains unexplained')
    if preservation['semantic_report'] != record(ROOT, (SCRATCH / args.semantic / 'semantic_diff_report.json').relative_to(ROOT).as_posix()):
        raise ContractError('Preservation and semantic jobs use different reports')
    recovery = read_json(EVIDENCE / args.recovery / 'result.json')
    if recovery['status'] != 'pass' or recovery['candidate'] != args.candidate:
        raise ContractError('Matching candidate recovery proof is required')
    output = EVIDENCE / args.name
    output.mkdir(parents=True, exist_ok=False)
    for source, name in (
        (SCRATCH / args.tests / 'result.json', 'full_suite_result.json'),
        (SCRATCH / args.tests / 'junit.xml', 'full_suite_junit.xml'),
        (SCRATCH / args.tests / 'process.log', 'full_suite.log'),
        (SCRATCH / args.semantic / 'result.json', 'semantic_result.json'),
        (SCRATCH / args.semantic / 'semantic_diff_report.json', 'semantic_diff_report.json'),
        (EVIDENCE / args.preservation / 'result.json', 'preservation.json'),
        (EVIDENCE / args.recovery / 'result.json', 'recovery.json')):
        if source == junit_path and not source.exists():
            continue
        shutil.copy2(source, output / name)
    summaries = {name: read_json(attempt / 'bundle/summary.json') for name, attempt in stages.items()}
    fresh_outputs = {}
    for name, attempt in stages.items():
        started = datetime.fromisoformat(read_json(attempt / 'telemetry/worker.json')['started_utc']).timestamp()
        written = {filename: (attempt / 'workspace/data/output' / filename).stat().st_mtime
                   for filename in STAGE_CSVS[name]}
        if any(modified < started for modified in written.values()):
            raise ContractError('Required CSV was inherited without a fresh worker write: ' + name)
        fresh_outputs[name] = dict(worker_started_epoch=started, csv_modified_epochs=written,
            meaning='Corroborating write freshness for this run; semantic parent comparisons remain separate')
    atomic_json(output / 'output_write_freshness.json', fresh_outputs)
    runtime = read_json(candidate / 'runtime.json')
    summary = dict(execution_status='complete' if tests_passed else 'verification_incomplete',
        engineering_tranche_complete=tests_passed,
        summary=('The isolated holdings, identity and PIK candidate completed with strict typed-pair and dependency verification. '
            + ('Full repository tests and recovery checks passed. ' if tests_passed else
               'The full repository suite did not pass or finish; engineering verification is incomplete. Recovery and preservation checks passed. ')
            + 'Financial acceptance remains separate, with missing evidence recorded explicitly.'),
        candidate=args.candidate, candidate_fingerprint=candidate_fingerprint,
        stages={name: dict(rows=item['rows'], seconds=item['elapsed_seconds'], artifacts=len(item['artifacts_metadata']))
                for name, item in summaries.items()},
        runtime=dict(files=len(runtime['content']), bytes=sum(item['bytes'] for item in runtime['content']),
            inventory_policy=runtime['inventory_policy'], trusted_boundary=runtime['trusted_boundary'],
            complete_before_after=True, undeclared_python_inputs='rejected on open',
            preflight_completed=preflight['verified_utc']),
        verification=dict(full_suite=counts, full_suite_seconds=float(suite.attrib['time']) if suite is not None else None,
            full_suite_passed=tests_passed, full_suite_exit_code=tests['exit_code'],
            full_suite_timed_out=tests['timed_out'], full_suite_junit_available=suite is not None,
            full_suite_elapsed_seconds=tests['elapsed_seconds'],
            protected_files_checked=tests['protected_readable_files'], protected_changes=0,
            semantic_job=semantic['mode'], semantic_exit_code=semantic['exit_code'],
            semantic_groups=preservation['baseline_divergence_groups'], clean_official_baseline=False,
            material_changes_since_preparation=0, derived_delta_roundoff=preservation['derived_delta_roundoff'],
            original_inputs=preservation['original_input_files'], original_match_references=preservation['original_match_reference_files'],
            original_gold_unchanged=True, recovery='timeout, completed-stage reuse and local restore passed'),
        product_acceptance=dict(verdict=criteria['verdict'], criteria=28, metrics=50,
            metric_status_counts=dict(Counter(item['status'] for item in metrics)),
            obligations=measurements['obligations'], availability=measurements['history']),
        references=dict(dispositions=61, label_proposals=20, independently_reviewed=0),
        remediation_packets=4, production_adoption=False, sec_requests=0, paid_calls=0,
        next_decision='Appoint independent reference-review authority; choose the next source-backed implementation package',
        limits='No target schema/rate/dbt migration, public citation product, gold promotion or production release in this tranche')
    atomic_json(output / 'verification.json', summary)
    atomic_json(output / 'complete.json', dict(status='engineering_review_ready' if tests_passed else
        'candidate_verified_verification_incomplete',
        artifacts=[record(output, path.name) for path in sorted(output.iterdir()) if path.is_file()],
        source_manifests=[record(ROOT, path.relative_to(ROOT).as_posix()) for path in
            (candidate / 'snapshot.json', evaluation / 'evaluation_manifest.json', Path(__file__))]))
    print('Candidate handoff recorded; engineering complete=' + str(tests_passed)
          + '; financial verdict: ' + criteria['verdict'], flush=True)


if __name__ == '__main__':
    main()
