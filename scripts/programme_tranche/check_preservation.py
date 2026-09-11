"""Verify original inputs/references and compare the two semantic backstops."""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import threading
import time

from pipeline.programme.core import ContractError, atomic_json, read_json, record, sha, verify_records
from scripts.diff_outputs import _is_material_delta, _numeric_delta

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / 'docs/production_stack/programme_closeout_evidence_2026-09-09'
OUTPUT = ROOT / 'docs/production_stack/programme_tranche_evidence_2026-09-10'


def equivalent(left, right, path='', differences=None, roundoff=None):
    """Use the existing semantic backstop's numeric-noise rule, not a new gate."""
    differences = [] if differences is None else differences
    roundoff = [] if roundoff is None else roundoff
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            differences.append(path + ': keys changed')
        for key in set(left) & set(right):
            base = key[:-6] if key.endswith('_delta') else None
            source_keys = (base + '_current', base + '_baseline') if base else ()
            if source_keys and all(k in left and k in right for k in source_keys):
                # Validate the recorded subtraction before comparing propagated
                # noise at the scale of its source sums, never the small delta.
                valid = all(row[key] == _numeric_delta(row[source_keys[0]], row[source_keys[1]])
                            for row in (left, right))
                stable = all(not _is_material_delta(base, _numeric_delta(right[k], left[k]), right[k], left[k])
                             for k in source_keys)
                if not valid or not stable:
                    differences.append(path + '/' + key + ': changed source sums or invalid subtraction')
                elif left[key] != right[key]:
                    roundoff.append(dict(path=path + '/' + key, old_delta=left[key], new_delta=right[key],
                        change=right[key]-left[key], source_totals_within_existing_noise_rule=True))
            else:
                equivalent(left[key], right[key], path + '/' + key, differences, roundoff)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            differences.append(path + ': row count changed')
        for index, (a, b) in enumerate(zip(left, right)):
            equivalent(a, b, path + '/' + str(index), differences, roundoff)
    elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if 'count' in path:
            same = left == right
        elif math.isnan(left) and math.isnan(right):
            same = True
        else:
            same = math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-6)
        if not same:
            differences.append(path + ': numeric result changed')
    elif left != right:
        differences.append(path + ': value changed')
    return differences


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--semantic-report', type=Path, required=True)
    parser.add_argument('--name', default='preservation-v1')
    args = parser.parse_args()
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.name):
        raise ContractError('Invalid result name')
    out = OUTPUT / args.name
    if out.exists():
        raise ContractError('Preserve previous verification results')
    timer = threading.Timer(600, lambda: os._exit(124)); timer.daemon = True; timer.start()
    start = time.monotonic()
    base = ROOT / 'data/programme/candidates/spec-close-20260909-v2'
    manifest = read_json(base / 'snapshot.json')
    if sha(base / 'snapshot.json') != read_json(base / 'snapshot_complete.json')['manifest_sha256']:
        raise ContractError('Starting manifest changed')
    original = [item for item in manifest['artifacts']
                if item['path'].startswith(('pipeline/', 'data/')) or item['path'] == 'AGENTS.md']
    print('Checking original pipeline/data inputs: ' + str(len(original)), flush=True)
    verify_records(ROOT, original)
    references = read_json(OLD / 'identity/input_manifest.json')['reference_files']
    changed = []
    for item in references:
        if sha(ROOT / item['path'].replace('\\', '/')) != item['sha256']:
            changed.append(item['path'])
    if changed:
        raise ContractError('Original match references changed: ' + repr(changed[:10]))
    gold = record(ROOT, 'data/gold/labels/position_labels.jsonl')
    if gold['sha256'] != read_json(OLD / 'original_input_preservation.json')['original_position_labels_sha256']:
        raise ContractError('Original gold labels changed')
    for directory, manifest_name, key in (
        (OUTPUT / 'references-v1', 'freeze_manifest.json', 'files'),
        (OUTPUT / 'source-review-v1', 'complete.json', 'artifacts')):
        verify_records(directory, read_json(directory / manifest_name)[key], exact=True,
                       ignored_prefixes=(manifest_name,))
    previous_report = OLD / 'verification/semantic_diff_report.json'
    previous, current = read_json(previous_report), read_json(args.semantic_report)
    roundoff = []
    differences = equivalent(previous['artifacts'], current['artifacts'], roundoff=roundoff)
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out / 'result.json', dict(status='pass' if not differences else 'unexplained_difference',
        original_input_files=len(original), original_match_reference_files=len(references), original_gold=gold,
        semantic_report=record(ROOT, args.semantic_report.resolve().relative_to(ROOT).as_posix()),
        previous_report=record(ROOT, previous_report.relative_to(ROOT).as_posix()),
        semantic_changes_since_preparation=differences,
        derived_delta_roundoff=roundoff,
        numeric_rule='Unchanged scripts.diff_outputs source-scale numeric-noise rule; each derived delta must equal its recorded subtraction',
        baseline_divergence_groups={kind: sum(len(rows) for rows in groups.values())
                                    for kind, groups in current['artifacts'].items()},
        current_baseline_manifest=record(ROOT, 'docs/refactoring/baseline_manifest.json'),
        source_reference_freezes_unchanged=True, elapsed_seconds=time.monotonic()-start,
        scope='Frozen original pipeline/data/controls and used match references/gold; compare five semantic artifacts to the active official baseline. Other historical files are covered only to the extent the separate full byte backstop completes.',
        code=record(ROOT, Path(__file__).relative_to(ROOT).as_posix())))
    timer.cancel()
    if differences:
        raise ContractError('Semantic backstop changed since preparation: ' + repr(differences[:10]))
    print('Original inputs/references preserved; existing semantic baseline differences unchanged', flush=True)


if __name__ == '__main__':
    main()
