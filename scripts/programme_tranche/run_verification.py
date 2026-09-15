"""Monitored full-suite/backstop jobs with durable logs; no execution caps."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from pipeline.programme.core import ContractError, atomic_json, now, read_json, record, sha
from pipeline.programme.runner import candidate_path, heavy_lock

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / 'scratch/2026-09-12_programme_e0/verification'


def protected_inventory():
    records, unreadable = {}, []
    for root in (ROOT / 'data/output', ROOT / 'frontend/public/data'):
        for directory, _, names in os.walk(root):
            for name in names:
                path = Path(directory) / name
                relative = path.relative_to(ROOT).as_posix()
                try:
                    info = path.stat()
                    records[relative] = [info.st_size, info.st_mtime_ns]
                except OSError:
                    unreadable.append(relative)
    return dict(records=records, unreadable=sorted(unreadable))


def worker(mode, output, selection=None):
    # These test jobs use the repository's production-open guard and native-IO
    # before/after backstop, not the candidate worker's low-integrity sandbox.
    # Prevent accidental external network use even if a test forgets its mock.
    def audit(event, args):
        if event in ('socket.connect', 'socket.sendto', 'socket.getaddrinfo'):
            address = args[0] if event == 'socket.getaddrinfo' else args[-1]
            host = address[0] if isinstance(address, tuple) else address
            if host not in ('127.0.0.1', '::1', 'localhost'):
                raise PermissionError('Verification forbids external network connections')
    sys.addaudithook(audit)
    import dotenv
    os.environ['OPENAI_API_KEY'] = 'ci-dummy-key-tests-mock-all-calls'
    with patch.object(dotenv, 'load_dotenv', lambda *args, **kwargs: False):
        if mode in ('tests', 'focused'):
            import pytest
            selection = selection or ([] if mode == 'tests' else ['tests/test_programme_runtime.py',
                'tests/test_programme_measurement.py','tests/test_programme_tranche.py',
                'tests/test_programme_runtime_metadata.py'])
            return pytest.main(['-q', '--durations=50', '--durations-min=0.5',
                                '--junitxml=' + str(output / 'junit.xml'), *selection])
        from scripts import diff_outputs
        diff_outputs.SEMANTIC_REPORT_FILE = output / 'semantic_diff_report.json'
        sys.argv = ['scripts/diff_outputs.py', '--semantic']
        if mode == 'semantic-only':
            return diff_outputs.semantic_diff(read_json(diff_outputs.MANIFEST_FILE))
        return diff_outputs.main()


def launch(mode, output, selection=None):
    import psutil
    import win32api
    import win32con
    import win32job
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-m', 'scripts.programme_tranche.run_verification', mode,
               '--worker', '--output', str(output)]
    for test in selection or []:
        command.extend(['--test', test])
    job = win32job.CreateJobObject(None, '')
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    started = time.monotonic()
    before = record(ROOT, Path(__file__).relative_to(ROOT).as_posix())
    protected_before = protected_inventory()
    atomic_json(output / 'protected_before.json', protected_before)
    process = None
    last_print = 0
    try:
        with (output / 'process.log').open('w', encoding='utf-8') as log:
            env = dict(os.environ, PYTHONUNBUFFERED='1', OPENAI_API_KEY='ci-dummy-key-tests-mock-all-calls')
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, process.pid)
            try:
                win32job.AssignProcessToJobObject(job, handle)
            finally:
                handle.Close()
            created = psutil.Process(process.pid).create_time()
            atomic_json(output / 'process.json', dict(controller_pid=os.getpid(), worker_pid=process.pid,
                worker_created=created, command=command, started_utc=now(), limit_seconds=None,
                limit_job_memory_bytes=None, code=before, network='external denied; loopback allowed'))
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed - last_print >= 30:
                    last_print = elapsed
                    try:
                        stats = psutil.Process(process.pid).memory_info()
                        private = getattr(stats, 'private', stats.rss)
                    except psutil.NoSuchProcess:
                        private = 0
                    atomic_json(output / 'resources.json', dict(elapsed_seconds=elapsed, private_bytes=private, updated_utc=now()))
                    print(mode + ': ' + str(round(elapsed)) + ' seconds; worker private GiB=' + str(round(private/1024**3,2)), flush=True)
                time.sleep(1)
    finally:
        if process and process.poll() is None:
            win32job.TerminateJobObject(job, 125)
            process.wait(timeout=30)
        # Closing the job also terminates any child a test forgot to clean up.
        job.Close()
    protected_after = protected_inventory()
    atomic_json(output / 'protected_after.json', protected_after)
    changed_paths = sorted(path for path in set(protected_before['records']) | set(protected_after['records'])
                           if protected_before['records'].get(path) != protected_after['records'].get(path))
    unreadable_changed = protected_before['unreadable'] != protected_after['unreadable']
    result = dict(mode=mode, started_code=before, code_unchanged=sha(Path(__file__)) == before['sha256'],
                  exit_code=process.returncode, timed_out=False,
                  worker_stopped=process.poll() is not None, elapsed_seconds=time.monotonic()-started,
                  protected_readable_files=len(protected_before['records']), protected_changes=changed_paths,
                  protected_unreadable_paths_changed=unreadable_changed,
                  consistently_unreadable_paths=protected_before['unreadable'] if not unreadable_changed else None,
                  log=record(ROOT,(output / 'process.log').relative_to(ROOT).as_posix()))
    atomic_json(output / 'result.json', result)
    print(mode + ': exit ' + str(process.returncode), flush=True)
    return process.returncode or (1 if changed_paths or unreadable_changed else 0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['tests','focused','semantic','semantic-only'])
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--name')
    parser.add_argument('--candidate',default='t1-runtime-20260910-v5')
    parser.add_argument('--test',action='append',dest='selection')
    args=parser.parse_args()
    if args.worker:
        if args.output is None or not args.output.resolve().is_relative_to(SCRATCH.resolve()):
            raise ContractError('Invalid verification output')
        raise SystemExit(worker(args.mode,args.output,args.selection))
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.name):
        raise ContractError('Use a new portable job name')
    with heavy_lock(candidate_path(args.candidate)):
        raise SystemExit(launch(args.mode,SCRATCH/args.name,args.selection))


if __name__=='__main__':
    main()
