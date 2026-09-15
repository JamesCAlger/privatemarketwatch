"""Exercise explicit cancellation, completed-stage reuse and verified local restore."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import time

from pipeline.programme.core import ContractError, atomic_json, read_json, record, sha
from pipeline.programme.runner import candidate_path, canary, heavy_lock, restore, run

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'docs/production_stack/programme_tranche_evidence_2026-09-10'


def inventory(candidate):
    return {path.relative_to(candidate).as_posix(): sha(path)
            for path in sorted((candidate / 'attempts').glob('*/result.json'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--name', default='recovery-v1')
    args = parser.parse_args()
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.name):
        raise ContractError('Invalid proof name')
    output = OUTPUT / args.name
    output.mkdir(parents=True, exist_ok=False)
    
    candidate = candidate_path(args.candidate)
    started = time.monotonic()
    original = inventory(candidate)
    attempts_before = sorted(path.name for path in (candidate / 'attempts').glob('evidence-*'))
    atomic_json(output / 'started.json', dict(candidate=args.candidate, completed_results=original,
        seconds_limit=None, controller_pid=os.getpid(), code=record(ROOT,Path(__file__).relative_to(ROOT).as_posix())))
    tick = time.monotonic()
    reused = run(candidate, 'evidence')
    attempts_after = sorted(path.name for path in (candidate / 'attempts').glob('evidence-*'))
    if attempts_before != attempts_after or original != inventory(candidate):
        raise ContractError('Completed-stage reuse created a new attempt or changed a result')
    reuse = dict(attempt=reused.relative_to(ROOT).as_posix(), elapsed_seconds=time.monotonic()-tick,
        no_new_attempt=True, completed_results_unchanged=True, result_sha256=sha(reused/'result.json'))
    atomic_json(output / 'reuse.json', reuse)
    print('Completed evidence stage reused without a new worker', flush=True)
    tick = time.monotonic()
    with heavy_lock(candidate):
        restored = restore(candidate, 'identity')
    restoration = dict(path=restored.relative_to(ROOT).as_posix(), elapsed_seconds=time.monotonic()-tick,
        proof=record(ROOT,(restored/'restore_verified.json').relative_to(ROOT).as_posix()), adoption='not_adopted')
    atomic_json(output / 'restore.json', restoration)
    print('Identity bundle restored and verified locally', flush=True)
    tick = time.monotonic()
    before_canaries = set((candidate/'attempts').glob('canary-*'))
    with heavy_lock(candidate):
        canary(candidate, cancellation=True)
    added = set((candidate/'attempts').glob('canary-*'))-before_canaries
    if len(added) != 1:
        raise ContractError('Cancellation proof has an ambiguous attempt')
    attempt = added.pop()
    process = read_json(attempt/'process_result.json')
    proof = read_json(attempt/'canary_verified.json')
    if (process['exit_code'] == 0 or not process['worker_stopped'] or
        not (attempt/'telemetry/cancellation_ready.json').exists() or not proof['cancellation_test'] or
        not proof['protected_canaries_unchanged']):
        raise ContractError('Cancellation did not establish worker termination and preservation')
    cancellation = dict(attempt=attempt.relative_to(ROOT).as_posix(), elapsed_seconds=time.monotonic()-tick,
        exit_code=process['exit_code'], worker_stopped=True,
        protected_canaries_unchanged=True, completed_marker_absent=not (attempt/'complete.json').exists())
    if not cancellation['completed_marker_absent'] or inventory(candidate) != original:
        raise ContractError('Failed probe changed completed stage state')
    atomic_json(output/'cancellation.json',cancellation)
    atomic_json(output/'result.json',dict(status='pass',candidate=args.candidate,reuse=reuse,
        restore=restoration,cancellation=cancellation,elapsed_seconds=time.monotonic()-started,
        adoption='not_adopted',scope='Completed stage reuse, verified local identity restore and explicit native worker cancellation. Mid-statement resume and production adoption are not implemented.'))
    
    print('Recovery proof passed; no production adoption',flush=True)


if __name__ == '__main__':
    main()
