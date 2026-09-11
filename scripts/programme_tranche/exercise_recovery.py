"""Exercise timeout, completed-stage reuse and verified local restore."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
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
    parser.add_argument('--deadline', default='2026-09-10T16:43:01+00:00')
    args = parser.parse_args()
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.name):
        raise ContractError('Invalid proof name')
    if (datetime.fromisoformat(args.deadline)-datetime.now(timezone.utc)).total_seconds() < 1260:
        raise ContractError('Recovery proof cannot fit before deadline')
    output = OUTPUT / args.name
    output.mkdir(parents=True, exist_ok=False)
    timer = threading.Timer(1200, lambda: os._exit(124)); timer.daemon = True; timer.start()
    candidate = candidate_path(args.candidate)
    started = time.monotonic()
    original = inventory(candidate)
    attempts_before = sorted(path.name for path in (candidate / 'attempts').glob('evidence-*'))
    atomic_json(output / 'started.json', dict(candidate=args.candidate, completed_results=original,
        seconds_limit=1200, controller_pid=os.getpid(), code=record(ROOT,Path(__file__).relative_to(ROOT).as_posix())))
    tick = time.monotonic()
    reused = run(candidate, 'evidence', 900, deadline=args.deadline)
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
        canary(candidate, timeout=True)
    added = set((candidate/'attempts').glob('canary-*'))-before_canaries
    if len(added) != 1:
        raise ContractError('Timeout proof has an ambiguous attempt')
    attempt = added.pop()
    process = read_json(attempt/'process_result.json')
    resources = read_json(attempt/'telemetry/resources.json')
    proof = read_json(attempt/'canary_verified.json')
    # The recorded exit and elapsed limit must demonstrate watchdog termination,
    # not merely an arbitrary nonzero exit after the native checks.
    if (process['exit_code'] != 124 or not process['worker_stopped'] or
        resources['elapsed_seconds'] < 30 or not proof['timeout_test'] or
        not proof['protected_canaries_unchanged']):
        raise ContractError('Timeout did not establish watchdog termination and preservation')
    timeout = dict(attempt=attempt.relative_to(ROOT).as_posix(), elapsed_seconds=time.monotonic()-tick,
        exit_code=process['exit_code'], worker_stopped=True, watchdog_seconds=resources['elapsed_seconds'],
        protected_canaries_unchanged=True, completed_marker_absent=not (attempt/'complete.json').exists())
    if not timeout['completed_marker_absent'] or inventory(candidate) != original:
        raise ContractError('Failed probe changed completed stage state')
    atomic_json(output/'timeout.json',timeout)
    atomic_json(output/'result.json',dict(status='pass',candidate=args.candidate,reuse=reuse,
        restore=restoration,timeout=timeout,elapsed_seconds=time.monotonic()-started,
        adoption='not_adopted',scope='Completed stage reuse, verified local identity restore and real native worker timeout. Mid-statement resume and production adoption are not implemented.'))
    timer.cancel()
    print('Recovery proof passed; no production adoption',flush=True)


if __name__ == '__main__':
    main()
