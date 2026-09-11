"""Trusted bootstrap: lower token before importing any pipeline worker code."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import site
import threading
import time

from pipeline.programme.core import ContractError, atomic_json, read_json, now, sha
from pipeline.programme.native import lower_integrity


def read_guard(attempt, runtime):
    """Construct a testable read policy; existing unlisted runtime files fail early."""
    attempt = Path(attempt).resolve()
    roots = [Path(root).resolve() for root in runtime['content_roots']]
    declared = {os.path.normcase(str(Path(item['path']))) for item in runtime['content']}

    def check_read(path):
        resolved = Path(os.fsdecode(path)).resolve()
        if resolved.is_relative_to(attempt):
            return resolved
        if not any(resolved.is_relative_to(root) for root in roots):
            raise PermissionError('Undeclared Python input: ' + str(resolved))
        # A failed optional open of a nonexistent path does not consume an input.
        if os.path.normcase(str(resolved)) not in declared and resolved.exists():
            raise PermissionError('Unrecorded runtime input: ' + str(resolved))
        return resolved
    return check_read


def guard(attempt):
    attempt = Path(attempt).resolve()
    if sha(attempt / 'runtime.json') != read_json(attempt / 'runtime_complete.json')['sha256']:
        raise ContractError('Attempt runtime inventory changed')
    check_read = read_guard(attempt, read_json(attempt / 'runtime.json'))
    writable = [attempt / p for p in ('bundle', 'temp', 'workspace/data/output', 'telemetry')]
    reads = set()

    def check(path):
        if isinstance(path, (str, bytes, os.PathLike)):
            resolved = Path(os.fsdecode(path)).resolve()
            if not any(resolved.is_relative_to(p) for p in writable):
                raise PermissionError('Candidate write outside declared outputs: ' + str(resolved))

    def hook(event, args):
        if event == 'open':
            path, mode, flags = args
            if ((isinstance(mode, str) and any(c in mode for c in 'wax+')) or
                (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
                check(path)
            elif isinstance(path, (str, bytes, os.PathLike)):
                resolved = check_read(path)
                reads.add(str(resolved))
        elif event == 'os.mkdir' and Path(os.fsdecode(args[0])).is_dir():
            # Legacy config uses mkdir(exist_ok=True) on import. An existing
            # directory is a no-op; actual creation remains output-only.
            return
        elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.truncate', 'os.utime'):
            check(args[0])
        elif event in ('os.rename', 'os.link', 'os.symlink'):
            check(args[0]); check(args[1])
        elif event in ('socket.connect', 'socket.bind', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
            raise PermissionError('Offline candidate forbids operation: ' + event)
    sys.addaudithook(hook)
    return reads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    attempt = args.attempt.resolve()
    if Path(__file__).resolve().parents[2] != attempt / 'workspace':
        raise ContractError('Bootstrap is not in its frozen workspace')
    # The sandbox has already initialized its private Windows desktop.
    lower_integrity()
    import win32api
    import win32job
    import win32process
    job = win32job.CreateJobObject(None, '')
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    limits['BasicLimitInformation']['LimitFlags'] = (win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY |
        win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS | win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    limits['BasicLimitInformation']['ActiveProcessLimit'] = 1
    limits['ProcessMemoryLimit'] = 12 * 1024**3
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
    start = time.monotonic()
    done = threading.Event()

    def heartbeat():
        peak = 0
        while not done.is_set():
            elapsed = time.monotonic() - start
            counters = win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())
            memory = counters.get('PrivateUsage', counters['PagefileUsage'])
            peak = max(peak, memory)
            atomic_json(attempt / 'telemetry/resources.json', dict(pid=os.getpid(), elapsed_seconds=elapsed,
                        private_bytes=memory, peak_private_bytes=peak, limit_bytes=12 * 1024**3,
                        integrity='low', updated_utc=now()))
            if elapsed > args.seconds:
                os._exit(124)
            done.wait(min(5, max(.1, args.seconds - elapsed)))
    atomic_json(attempt / 'telemetry/worker.json', dict(pid=os.getpid(), started_utc=now(), integrity='low'))
    monitor = threading.Thread(target=heartbeat, daemon=True)
    monitor.start()
    try:
        if args.probe:
            from pipeline.programme.canary import run_canary
            run_canary(attempt)
        else:
            reads = guard(attempt)
            if read_json(attempt / 'inputs.json').get('stage') == 'preflight':
                from pipeline.programme.preflight import execute_preflight
                execute_preflight(attempt, reads)
            else:
                from pipeline.programme.stages import execute
                execute(attempt, reads)
    finally:
        done.set()
        monitor.join(timeout=10)
        # Do not close a kill-on-close job containing this current process before
        # Python has flushed normal output and communicated its exit code.
        limits['BasicLimitInformation']['LimitFlags'] &= ~win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        job.Close()


if __name__ == '__main__':
    main()
