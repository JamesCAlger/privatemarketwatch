"""Bounded offline test diagnosis with native write isolation and durable reports."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from pipeline.programme.core import ContractError, atomic_json, now, read_json, record, sha
from pipeline.programme import native
from pipeline.programme.runner import candidate_path, heavy_lock

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'scratch/2026-09-10_verification_investigation'


def inventory():
    """DirEntry.stat reuses Windows enumeration metadata; retain all file paths."""
    records, unreadable, links = {}, [], []
    started = time.monotonic()
    for relative in ('data/output', 'frontend/public/data'):
        stack = [str(ROOT / relative)]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        # The traversal starts at ROOT and rejects reparse paths;
                        # avoid two GetFullPathName calls per file via relpath.
                        rel = entry.path[len(str(ROOT))+1:].replace('\\', '/')
                        try:
                            if entry.is_symlink() or entry.is_junction():
                                links.append(rel)
                                # Fail explicitly; do not silently omit a reparse subtree.
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            else:
                                info = entry.stat(follow_symlinks=False)
                                records[rel] = [info.st_size, info.st_mtime_ns]
                        except OSError:
                            unreadable.append(rel)
            except OSError:
                unreadable.append(os.path.relpath(directory, ROOT).replace('\\', '/'))
    if links:
        raise ContractError('Protected reparse paths require explicit review: ' + repr(links[:10]))
    return dict(records=records, unreadable=sorted(unreadable), elapsed_seconds=time.monotonic()-started)


def canary(job):
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq
    results = {}
    for engine in ('python', 'duckdb', 'arrow'):
        for zone, path in (('allowed', job/'bundle'/engine), ('protected', job/('protected-'+engine)),
                           ('new_outside', job/('new-'+engine))):
            try:
                if engine == 'python':
                    path.write_bytes(b'changed')
                elif engine == 'duckdb':
                    with duckdb.connect() as con:
                        con.execute("COPY (SELECT 1 AS x) TO '"+path.as_posix().replace("'", "''")+"' (FORMAT PARQUET)")
                else:
                    pq.write_table(pa.table({'x': [1]}), path)
                outcome = 'allowed'
            except (OSError, duckdb.Error):
                outcome = 'denied'
            results[engine+'_'+zone] = outcome
    delete = ctypes.WinDLL('kernel32', use_last_error=True).DeleteFileW
    delete.argtypes = [ctypes.c_wchar_p]; delete.restype = ctypes.c_int
    results['native_delete'] = 'allowed' if delete(str(job/'protected-delete')) else 'denied'
    try:
        os.replace(job/'protected-rename', job/'bundle/stolen')
        results['rename'] = 'allowed'
    except OSError:
        results['rename'] = 'denied'
    atomic_json(job/'telemetry/canary.json', results)
    if any(value != ('allowed' if key.endswith('_allowed') else 'denied') for key, value in results.items()):
        raise ContractError('Native diagnostic write boundary failed')


class Reports:
    def __init__(self, job):
        self.job = job
        self.scan_count = 0
        self.initial_unreadable = None

    def pytest_configure(self, config):
        # Preserve pytest's existing native-IO backstop, with equivalent cached
        # enumeration metadata rather than a separate stat syscall per file.
        for plugin in config.pluginmanager.get_plugins():
            if getattr(plugin, '__file__', None) == str(ROOT/'tests/conftest.py'):
                def walk():
                    result = inventory()
                    self.scan_count += 1
                    atomic_json(self.job/'telemetry'/('inner-scan-'+str(self.scan_count)+'.json'),
                        dict(unreadable=result['unreadable'], readable_files=len(result['records']),
                             elapsed_seconds=result['elapsed_seconds']))
                    if self.initial_unreadable is None:
                        self.initial_unreadable = result['unreadable']
                    elif result['unreadable'] != self.initial_unreadable:
                        raise ContractError('Protected readability changed inside sandbox')
                    # Existing pytest guard skips unreadable historical files.
                    # Preserve that behavior, disclose them, require stable
                    # readability, and retain the outer full-privilege inventory.
                    return {str(ROOT/key): (value[1], value[0]) for key, value in result['records'].items()}
                plugin._walk_protected = walk
                atomic_json(self.job/'telemetry/backstop.json', dict(native_prevention=True, metadata_backstop=True,
                    inventory='DirEntry cached metadata; reparse paths rejected; unreadable historical paths disclosed and checked outside sandbox'))

    def pytest_collection_finish(self, session):
        atomic_json(self.job/'telemetry/collection.json', [item.nodeid for item in session.items])

    def pytest_runtest_logstart(self, nodeid, location):
        atomic_json(self.job/'telemetry/current_test.json', dict(nodeid=nodeid, started_utc=now()))

    def pytest_runtest_logreport(self, report):
        item = dict(nodeid=report.nodeid, when=report.when, outcome=report.outcome,
                    duration=report.duration, recorded_utc=now())
        if report.failed:
            item['traceback'] = str(report.longrepr)
        with (self.job/'telemetry/reports.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(item, ensure_ascii=True)+'\n'); handle.flush(); os.fsync(handle.fileno())


def worker(job, seconds):
    native.lower_integrity()
    import win32api
    import win32job
    job_handle = win32job.CreateJobObject(None, '')
    limits = win32job.QueryInformationJobObject(job_handle, win32job.JobObjectExtendedLimitInformation)
    limits['BasicLimitInformation']['LimitFlags'] = (win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
        win32job.JOB_OBJECT_LIMIT_JOB_MEMORY | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
    limits['BasicLimitInformation']['ActiveProcessLimit'] = 8
    limits['JobMemoryLimit'] = 12 * 1024**3
    win32job.SetInformationJobObject(job_handle, win32job.JobObjectExtendedLimitInformation, limits)
    win32job.AssignProcessToJobObject(job_handle, win32api.GetCurrentProcess())
    timer = threading.Timer(seconds, lambda: os._exit(124)); timer.daemon = True; timer.start()
    atomic_json(job/'telemetry/worker.json', dict(pid=os.getpid(), started_utc=now(), integrity='low'))
    sys.stdout.reconfigure(encoding='ascii', errors='backslashreplace')
    sys.stderr.reconfigure(encoding='ascii', errors='backslashreplace')
    canary(job)
    request = read_json(job/'request.json')
    import dotenv
    os.environ['OPENAI_API_KEY'] = 'ci-dummy-key-tests-mock-all-calls'
    with patch.object(dotenv, 'load_dotenv', lambda *a, **kw: False):
        if request['mode'] == 'semantic':
            from scripts import diff_outputs
            diff_outputs.SEMANTIC_REPORT_FILE = job/'bundle/semantic_diff_report.json'
            code = diff_outputs.semantic_diff(read_json(diff_outputs.MANIFEST_FILE))
        else:
            import pytest
            arguments = ['-q', '-p', 'no:cacheprovider', '--basetemp='+str(job/'temp/pytest'),
                         '--junitxml='+str(job/'bundle/junit.xml'), '--durations=30', '--durations-min=0.1']
            if request['mode'] == 'collect':
                arguments += ['--collect-only']
            arguments += request['nodes']
            if request['mode'] == 'profile':
                import cProfile
                import pstats
                profiler = cProfile.Profile(); profiler.enable()
                code = pytest.main(arguments, plugins=[Reports(job)])
                profiler.disable(); profiler.dump_stats(str(job/'bundle/profile.prof'))
                with (job/'bundle/profile.txt').open('w', encoding='ascii', errors='backslashreplace') as stream:
                    pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(65)
            else:
                code = pytest.main(arguments, plugins=[Reports(job)])
    atomic_json(job/'telemetry/finished.json', dict(exit_code=int(code), finished_utc=now()))
    timer.cancel()
    return int(code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['collect', 'tests', 'profile', 'semantic'])
    parser.add_argument('--name', required=True)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('nodes', nargs='*')
    args = parser.parse_intermixed_args()
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.name):
        raise ContractError('Portable unique job name required')
    if not 1 <= args.seconds <= 900:
        raise ContractError('Diagnostic worker cap is 900 seconds')
    job = BASE/args.name
    if args.worker:
        return worker(job, args.seconds)
    if args.mode in ('tests', 'profile') and not args.nodes:
        raise ContractError('Diagnosis requires explicit test selection; no full-suite fallback')
    with heavy_lock(candidate_path('t1-runtime-20260910-v5')):
        job.mkdir(parents=True, exist_ok=False)
        for relative in ('bundle', 'temp', 'telemetry', 'workspace/data/output'):
            directory = job/relative; directory.mkdir(parents=True)
            native.label_writable(directory, job)
        for engine in ('python', 'duckdb', 'arrow', 'delete', 'rename'):
            (job/('protected-'+engine)).write_bytes(b'unchanged')
        before = inventory(); atomic_json(job/'protected_before.json', before)
        atomic_json(job/'request.json', dict(mode=args.mode, nodes=args.nodes,
            code=record(ROOT, Path(__file__).relative_to(ROOT).as_posix()),
            authority='Owner requested investigation after the stopped tranche; bounded diagnostics only'))
        fs = {':minimal':'read', str(ROOT):'read', str(Path(sys.executable).parent):'read',
              str(Path(__import__('site').getusersitepackages())):'read', ':tmpdir':'deny', ':slash_tmp':'deny'}
        for relative in ('bundle', 'temp', 'telemetry', 'workspace/data/output'):
            fs[str(job/relative)] = 'write'
        profile = '{'+', '.join(json.dumps(k)+'='+json.dumps(v) for k,v in fs.items())+'}'
        profile_name = 'test_diagnosis'
        command = [str(native.codex_executable()), 'sandbox', '-C', str(ROOT), '-P', profile_name,
            '-c', 'permissions.'+profile_name+'.filesystem='+profile,
            '-c', 'permissions.'+profile_name+'.network.enabled=false',
            '-c', 'windows.sandbox="elevated"', '-c', 'project_root_markers=[]',
            sys.executable, '-B', '-m', 'scripts.programme_tranche.diagnose_tests', args.mode,
            '--name', args.name, '--seconds', str(args.seconds), '--worker']
        started = time.monotonic()
        with (job/'process.log').open('w', encoding='ascii', errors='backslashreplace') as log:
            process = subprocess.Popen(command, cwd=ROOT, env=native.environment(job), stdout=log,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            atomic_json(job/'process.json', dict(controller_pid=os.getpid(), launcher_pid=process.pid,
                started_utc=now(), seconds=args.seconds, command=command))
            while process.poll() is None and time.monotonic()-started < args.seconds+30:
                time.sleep(1)
            if process.poll() is None:
                process.kill(); process.wait(timeout=15)
        import psutil
        telemetry = job/'telemetry/worker.json'
        stopped = not telemetry.exists() or not psutil.pid_exists(read_json(telemetry)['pid'])
        after = inventory(); atomic_json(job/'protected_after.json', after)
        changed = sorted(k for k in before['records'].keys()|after['records'].keys()
                         if before['records'].get(k) != after['records'].get(k))
        canaries = all((job/('protected-'+engine)).read_bytes() == b'unchanged'
                       for engine in ('python', 'duckdb', 'arrow', 'delete', 'rename'))
        result = dict(exit_code=process.returncode, worker_stopped=stopped, elapsed_seconds=time.monotonic()-started,
            protected_files=len(before['records']), protected_changes=changed,
            unreadable_changed=before['unreadable'] != after['unreadable'], canaries_preserved=canaries,
            native_canary=read_json(job/'telemetry/canary.json') if (job/'telemetry/canary.json').exists() else None,
            before_scan_seconds=before['elapsed_seconds'], after_scan_seconds=after['elapsed_seconds'])
        atomic_json(job/'result.json', result)
        print(json.dumps(result), flush=True)
        if not stopped or changed or not canaries or result['unreadable_changed'] or not result['native_canary']:
            raise ContractError('Diagnostic protection check failed')
        return process.returncode


if __name__ == '__main__':
    raise SystemExit(main())
