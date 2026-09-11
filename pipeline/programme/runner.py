"""Controller for frozen offline candidates. Completion never adopts production."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from pipeline.programme import artifacts, native
from pipeline.programme.core import (ContractError, atomic_json, contained, digest, identity,
                                     now, read_json, read_stage, record, seal, sha, verify_records)

ROOT = Path(__file__).resolve().parents[2]
LIMITS = {'unified': 5400, 'identity': 3600, 'evidence': 900}
PARENTS = {'unified': None, 'identity': 'unified', 'evidence': 'identity'}
LEGACY_DIRECTORIES = (
    'data/raw/sec_datasets/nport_quarterly', 'data/raw/filings/bdc_xbrl',
    'data/raw/filings/nport_xml', 'data/raw/filings/bdc_html',
    'data/raw/filings/ncsr_html', 'data/raw/filings/sc_toi_html',
    'data/raw/third_party', 'data/raw/n2_headers_cache',
    'data/raw/filing_templates', 'data/raw/companyfacts_cache',
    'data/raw/sec_reference', 'data/raw/listed_prices',
    'data/reference', 'data/overrides/fund_highlights_wrappers',
    'data/output/cache/sec_download_locks',
)


def controller_code():
    return {name: sha(ROOT / name) for name in (
        'pipeline/programme/runner.py', 'pipeline/programme/core.py',
        'pipeline/programme/native.py', 'pipeline/programme/artifacts.py',
        'pipeline/programme/runtime_content.py',
        'pipeline/output_schemas.py', 'pipeline/utils.py')}


def candidate_path(name):
    if not name or any(char not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for char in name):
        raise ContractError('Candidate name must contain lowercase letters, digits, dash or underscore')
    return contained(ROOT / 'data/programme/candidates', name, existing=False)


@contextmanager
def heavy_lock(candidate):
    import psutil
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
        if process.info['pid'] == os.getpid():
            continue
        command = ' '.join(process.info.get('cmdline') or [])
        if str(process.info['name']).lower().startswith('python') and any(
            word in command for word in ('pytest', 'rebuild_outputs.py', 'pipeline.programme.bootstrap')):
            raise ContractError('Another heavy job is active: pid ' + str(process.pid))
    path = ROOT / 'data/programme/heavy.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        prior = read_json(path)
        pid = prior['controller_pid']
        try:
            process = psutil.Process(pid)
            if process.create_time() == prior['controller_created']:
                raise ContractError('Active programme controller owns the heavy-job lock')
        except psutil.NoSuchProcess:
            pass
        # Never infer an interrupted child is dead from its controller's absence.
        prior_candidate = Path(prior['candidate']).resolve()
        if not prior_candidate.is_relative_to((ROOT / 'data/programme/candidates').resolve()):
            raise ContractError('Invalid candidate in heavy-job lock')
        for telemetry in prior_candidate.glob('attempts/*/telemetry/worker.json'):
            worker = read_json(telemetry)
            if psutil.pid_exists(worker['pid']):
                raise ContractError('Interrupted worker PID still exists; inspect before retry')
        path.rename(path.with_name('heavy.stale-' + str(time.time_ns()) + '.json'))
    with path.open('x', encoding='utf-8') as stream:
        import json
        json.dump(dict(controller_pid=os.getpid(), controller_created=psutil.Process().create_time(),
                       candidate=str(candidate), acquired_utc=now()), stream)
    try:
        yield
    finally:
        if path.exists() and read_json(path).get('controller_pid') == os.getpid():
            path.unlink()


def snapshot(candidate, base):
    if candidate.exists():
        raise ContractError('Snapshot already exists; choose a new immutable candidate')
    if shutil.disk_usage(ROOT).free < 100 * 1024**3:
        raise ContractError('Less than 100 GiB free disk')
    legacy = read_json(base / 'snapshot.json')
    if sha(base / 'snapshot.json') != read_json(base / 'snapshot_complete.json')['manifest_sha256']:
        raise ContractError('Starting snapshot manifest changed')
    print('Verify the frozen starting inputs', flush=True)
    verify_records(base / 'frozen', legacy['artifacts'])
    candidate.mkdir(parents=True)
    frozen = candidate / 'frozen'
    frozen.mkdir()
    # Copy exactly the recorded input universe, not arbitrary later additions.
    for index, item in enumerate(legacy['artifacts']):
        source = contained(base / 'frozen', item['path'])
        destination = contained(frozen, item['path'], existing=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if index % 200 == 0:
            print('Frozen inputs copied: ' + str(index + 1), flush=True)
    for source in (ROOT / 'pipeline/programme').rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts and source.suffix in ('.py', '.json'):
            relative = source.relative_to(ROOT).as_posix()
            destination = contained(frozen, relative, existing=False)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    shutil.copy2(ROOT / 'requirements-programme-windows.txt', frozen / 'requirements-programme-windows.txt')
    records = [record(frozen, p.relative_to(frozen).as_posix()) for p in sorted(frozen.rglob('*')) if p.is_file()]
    if sum(item['bytes'] for item in records) > 12 * 1024**3:
        raise ContractError('Snapshot exceeds 12 GiB')
    runtime = native.runtime_identity()
    atomic_json(candidate / 'runtime.json', runtime)
    manifest = dict(format_version=1, created_utc=now(), artifacts=records,
                    input_fingerprint=digest(records), starting_snapshot=legacy['input_fingerprint'],
                    existing_absent_controls=legacy.get('existing_absent_controls', []),
                    runtime_fingerprint=digest(runtime), role='frozen legacy inputs plus supported runner; no financial rule changes')
    atomic_json(candidate / 'snapshot.json', manifest)
    atomic_json(candidate / 'snapshot_complete.json', dict(manifest_sha256=sha(candidate / 'snapshot.json')))
    print('Snapshot sealed: ' + manifest['input_fingerprint'], flush=True)


def verify_snapshot(candidate):
    manifest = read_json(candidate / 'snapshot.json')
    if sha(candidate / 'snapshot.json') != read_json(candidate / 'snapshot_complete.json')['manifest_sha256']:
        raise ContractError('Snapshot manifest is stale')
    if digest(manifest['artifacts']) != manifest['input_fingerprint']:
        raise ContractError('Snapshot content identity is malformed')
    verify_records(candidate / 'frozen', manifest['artifacts'], exact=True)
    if digest(native.runtime_identity()) != manifest['runtime_fingerprint']:
        raise ContractError('Runtime changed since snapshot')
    return manifest


def stage_identity(candidate, stage, manifest, parent=None):
    parents = {} if parent is None else {PARENTS[stage]: {
        'attempt': parent.name, 'result_sha256': sha(parent / 'result.json'),
        'holdings_sha256': sha(parent / 'bundle/private_markets_holdings.csv')}}
    return identity(stage, manifest['input_fingerprint'], manifest['runtime_fingerprint'],
                    artifacts.contract_identity(stage), parents,
                    dict(cash_leg_unchanged=True, contested_assignment=True, use_registry=False,
                         dotenv='empty candidate-local file; no ambient dotenv values',
                         controller_code=controller_code(),
                         network=False, memory_limit_bytes=12 * 1024**3))


def latest(candidate, stage, manifest):
    parent = latest(candidate, PARENTS[stage], manifest) if PARENTS[stage] else None
    expected = stage_identity(candidate, stage, manifest, parent)
    attempts = sorted((candidate / 'attempts').glob(stage + '-*'), reverse=True)
    for attempt in attempts:
        if (attempt / 'complete.json').exists():
            # Corrupt/stale completed material is an error, not a reason to quietly skip it.
            read_stage(attempt, expected, artifacts.required(stage))
            verify_runtime_reads(attempt)
            return attempt
    raise ContractError('No verified completed parent for ' + stage)


def prepare_attempt(candidate, name, *, minimal=False):
    attempt = contained(candidate, 'attempts/' + name, existing=False)
    attempt.mkdir(parents=True, exist_ok=False)
    for relative in ('workspace', 'bundle', 'temp', 'telemetry', 'workspace/data/output'):
        (attempt / relative).mkdir(parents=True, exist_ok=True)
    # Set output directory label before populating it: children inherit low.
    for relative in ('bundle', 'temp', 'telemetry', 'workspace/data/output'):
        native.label_writable(attempt / relative, attempt)
    if minimal:
        shutil.copytree(candidate / 'frozen/pipeline', attempt / 'workspace/pipeline')
    else:
        shutil.copytree(candidate / 'frozen', attempt / 'workspace', dirs_exist_ok=True)
    # Create config's empty directory skeleton before lowering integrity.
    # Workers still cannot create, remove or modify readonly cache directories.
    for relative in LEGACY_DIRECTORIES:
        (attempt / 'workspace' / relative).mkdir(parents=True, exist_ok=True)
    # Installed python-dotenv predates PYTHON_DOTENV_DISABLED. An explicit
    # empty local file stops its upward search without reading ambient secrets.
    # The exact zero-byte file is included in the controller input contract.
    (attempt / 'workspace/.env').write_bytes(b'')
    shutil.copy2(candidate / 'runtime.json', attempt / 'runtime.json')
    atomic_json(attempt / 'runtime_complete.json', dict(sha256=sha(attempt / 'runtime.json')))
    return attempt


def launch(attempt, seconds, fingerprint, *, probe=False):
    import psutil
    command = native.command(attempt, seconds, probe=probe)
    started = time.monotonic()
    with (attempt / 'process.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=attempt / 'workspace', env=native.environment(attempt),
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        atomic_json(attempt / 'process.json', dict(controller_pid=os.getpid(), launcher_pid=process.pid,
                    command=command, started_utc=now(), seconds=seconds, input_fingerprint=fingerprint))
        last = 0
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > seconds + 30:
                    process.kill()
                    process.wait(timeout=15)
                    raise TimeoutError('Native worker exceeded its shutdown allowance')
                if elapsed - last >= 30:
                    last = elapsed
                    telemetry = attempt / 'telemetry/resources.json'
                    stats = read_json(telemetry) if telemetry.exists() else {}
                    print(attempt.name + ': ' + str(round(elapsed)) + 's; private GiB=' +
                          str(round(stats.get('private_bytes', 0) / 1024**3, 2)), flush=True)
                time.sleep(1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)
            telemetry = attempt / 'telemetry/worker.json'
            worker = read_json(telemetry) if telemetry.exists() else {}
            stopped = not worker or not psutil.pid_exists(worker['pid'])
            atomic_json(attempt / 'process_result.json', dict(exit_code=process.returncode,
                elapsed_seconds=time.monotonic() - started, worker_stopped=stopped,
                input_fingerprint=fingerprint, worker_pid=worker.get('pid'),
                usage=dict(agent_tokens=None, reason='command-only process; agent telemetry unavailable')))
    if process.returncode or not stopped:
        print((attempt / 'process.log').read_text(encoding='utf-8', errors='replace')[-5000:], flush=True)
        raise ContractError('Worker failed or termination not established; incomplete attempt retained')


def capture_runtime_reads(attempt):
    ledger = read_json(attempt / 'bundle/read_ledger.json')
    results = []
    frozen_runtime = read_json(attempt.parents[1] / 'runtime.json')
    runtime_roots = [Path(root).resolve() for root in frozen_runtime['content_roots']]
    declared = {item['path']: item for item in frozen_runtime['content']}
    for value in ledger['python_paths']:
        path = Path(value).resolve()
        if path.is_relative_to(attempt.resolve()) or not path.is_file():
            continue
        if not any(path.is_relative_to(root) for root in runtime_roots):
            raise ContractError('Undeclared external read: ' + str(path))
        item = dict(path=path.as_posix(), bytes=path.stat().st_size, sha256=sha(path))
        if declared.get(item['path']) != item:
            raise ContractError('Runtime read was not pinned before execution: ' + str(path))
        results.append(item)
    atomic_json(attempt / 'runtime_reads.json', dict(roots=[str(root) for root in runtime_roots], records=results))


def verify_runtime_reads(attempt):
    record_set = read_json(attempt / 'runtime_reads.json')
    result = read_json(attempt / 'process_result.json')
    if sha(attempt / 'runtime_reads.json') != result['runtime_reads_sha256']:
        raise ContractError('Runtime dependency ledger changed')
    runtime_roots = [Path(root).resolve() for root in record_set['roots']]
    for item in record_set['records']:
        path = Path(item['path']).resolve()
        if not any(path.is_relative_to(root) for root in runtime_roots) or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ContractError('A consumed runtime dependency changed: ' + item['path'])


def run(candidate, stage, seconds, *, deadline=None):
    if seconds <= 0 or seconds > LIMITS[stage]:
        raise ContractError('Invalid stage time allowance')
    if deadline and (datetime.fromisoformat(deadline) - datetime.now(timezone.utc)).total_seconds() < seconds + 60:
        raise ContractError('Stage cannot fit before the tranche deadline')
    with heavy_lock(candidate):
        manifest = verify_snapshot(candidate)
        canaries = list((candidate / 'attempts').glob('canary-*/canary_verified.json'))
        proofs = [read_json(path) for path in canaries]
        if not any(proof.get('snapshot_fingerprint') == manifest['input_fingerprint'] and
                   proof.get('runtime_fingerprint') == manifest['runtime_fingerprint'] and
                   proof.get('controller_code') == controller_code() and
                   proof.get('timeout_test') is False for proof in proofs):
            raise ContractError('This exact candidate/runtime needs a successful native canary first')
        verify_preflight(candidate, manifest)
        parent = latest(candidate, PARENTS[stage], manifest) if PARENTS[stage] else None
        expected = stage_identity(candidate, stage, manifest, parent)
        existing = sorted((candidate / 'attempts').glob(stage + '-*'))
        for previous in existing:
            if (previous / 'complete.json').exists():
                read_stage(previous, expected, artifacts.required(stage))
                verify_runtime_reads(previous)
                print('Reused complete verified stage: ' + str(previous), flush=True)
                return previous
        if len(existing) >= 2:
            raise ContractError('Initial attempt and one diagnosed retry already consumed')
        attempt = prepare_attempt(candidate, stage + '-' + str(len(existing) + 1).zfill(2))
        if parent:
            shutil.copy2(parent / 'bundle/private_markets_holdings.csv', attempt / 'workspace/data/output/private_markets_holdings.csv')
            shutil.copy2(parent / 'bundle/private_markets_holdings.parquet', attempt / 'workspace/data/output/private_markets_holdings.parquet')
        atomic_json(attempt / 'inputs.json', dict(stage=stage, identity=expected))
        launch(attempt, seconds, expected['fingerprint'])
        if controller_code() != expected['controls']['controller_code']:
            raise ContractError('Controller code changed during execution; cannot seal')
        summary = read_json(attempt / 'bundle/summary.json')
        if summary['input_fingerprint'] != expected['fingerprint'] or summary['parents'] != expected['parents']:
            raise ContractError('Worker summary belongs to another candidate')
        # Prove the frozen source/reference/rule universe remained unchanged.
        verify_records(candidate / 'frozen', manifest['artifacts'], exact=True)
        readonly = [r for r in manifest['artifacts'] if not r['path'].startswith('data/output/')]
        readonly.append(dict(path='.env', bytes=0, sha256=digest_empty_file()))
        verify_records(attempt / 'workspace', readonly, exact=True, ignored_prefixes=('data/output/',))
        capture_runtime_reads(attempt)
        verify_runtime_identity(candidate, manifest)
        process = read_json(attempt / 'process_result.json')
        process['runtime_reads_sha256'] = sha(attempt / 'runtime_reads.json')
        atomic_json(attempt / 'process_result.json', process)
        import duckdb
        with duckdb.connect() as connection:
            connection.execute('SET threads=2')
            connection.execute("SET memory_limit='4GB'")
            connection.execute("SET temp_directory='" + (attempt / 'temp').as_posix().replace("'", "''") + "'")
            metadata = {name: artifacts.verify_pair(attempt / 'bundle' / name, connection)
                        for name in artifacts.STAGE_CSVS[stage]}
            if stage == 'unified':
                artifacts.verify_audit(attempt / 'bundle/agent_fix_application_audit.csv', connection)
        seal(attempt, expected, artifacts.required(stage), artifacts_metadata=metadata)
        print('Controller sealed stage: ' + str(attempt), flush=True)
        return attempt


def verify_runtime_identity(candidate, manifest):
    if digest(native.runtime_identity()) != manifest['runtime_fingerprint']:
        raise ContractError('Complete runtime identity changed during execution')
    if digest(read_json(candidate / 'runtime.json')) != manifest['runtime_fingerprint']:
        raise ContractError('Recorded runtime inventory changed')


def verify_preflight(candidate, manifest):
    proofs = sorted((candidate / 'attempts').glob('preflight-*/preflight_verified.json'), reverse=True)
    for path in proofs:
        proof = read_json(path)
        if (proof['snapshot_fingerprint'] == manifest['input_fingerprint'] and
            proof['runtime_fingerprint'] == manifest['runtime_fingerprint'] and
            proof['controller_code'] == controller_code()):
            verify_records(path.parent / 'bundle', proof['artifacts'], exact=True)
            verify_runtime_reads(path.parent)
            return proof
    raise ContractError('This exact candidate needs a verified three-stage representative preflight')


def preflight(candidate):
    with heavy_lock(candidate):
        code = controller_code()
        manifest = verify_snapshot(candidate)
        attempt = prepare_attempt(candidate, 'preflight-' + str(time.time_ns()))
        atomic_json(attempt / 'inputs.json', dict(stage='preflight',
            identity=dict(fingerprint=manifest['input_fingerprint'], parents={})))
        launch(attempt, 600, manifest['input_fingerprint'])
        if controller_code() != code:
            raise ContractError('Controller changed during preflight')
        verify_records(candidate / 'frozen', manifest['artifacts'], exact=True)
        readonly = [r for r in manifest['artifacts'] if not r['path'].startswith('data/output/')]
        readonly.append(dict(path='.env', bytes=0, sha256=digest_empty_file()))
        verify_records(attempt / 'workspace', readonly, exact=True, ignored_prefixes=('data/output/',))
        capture_runtime_reads(attempt)
        verify_runtime_identity(candidate, manifest)
        process = read_json(attempt / 'process_result.json')
        process['runtime_reads_sha256'] = sha(attempt / 'runtime_reads.json')
        atomic_json(attempt / 'process_result.json', process)
        summary = read_json(attempt / 'bundle/preflight_summary.json')
        if set(summary['stages']) != set(LIMITS):
            raise ContractError('Representative preflight omitted a required stage')
        import duckdb
        with duckdb.connect() as connection:
            connection.execute('SET threads=2')
            for stage, result in summary['stages'].items():
                for name in result['artifacts_metadata']:
                    artifacts.verify_pair(attempt / 'bundle' / stage / name, connection)
        records = [record(attempt / 'bundle', p.relative_to(attempt / 'bundle').as_posix())
                   for p in sorted((attempt / 'bundle').rglob('*')) if p.is_file()]
        atomic_json(attempt / 'preflight_verified.json', dict(verified_utc=now(), controller_code=code,
            snapshot_fingerprint=manifest['input_fingerprint'], runtime_fingerprint=manifest['runtime_fingerprint'],
            artifacts=records, role='preflight only; not a candidate completion marker'))
        print('Three-stage representative preflight verified: ' + str(attempt), flush=True)


def digest_empty_file():
    import hashlib
    return hashlib.sha256(b'').hexdigest()


def canary(candidate, *, timeout=False):
    code = controller_code()
    manifest = verify_snapshot(candidate)
    attempt = prepare_attempt(candidate, 'canary-' + str(time.time_ns()), minimal=True)
    names = ['protected-' + name for name in ('python', 'duckdb', 'arrow', 'delete', 'rename')]
    for name in names:
        (attempt / name).write_bytes(b'preserve me')
    if timeout:
        (attempt / 'timeout_probe').touch()
    try:
        launch(attempt, 30 if timeout else 60, manifest['input_fingerprint'], probe=True)
    except ContractError:
        result = read_json(attempt / 'process_result.json')
        if not timeout or result['exit_code'] == 0 or result['worker_stopped'] is not True:
            raise
    if not all((attempt / name).read_bytes() == b'preserve me' for name in names):
        raise ContractError('Canary protection failed: original content changed')
    if not (attempt / 'telemetry/canary.json').is_file():
        raise ContractError('Canary did not reach native checks')
    if not (attempt / 'telemetry/config_smoke.json').is_file():
        raise ContractError('Canary did not complete configuration smoke checks')
    if controller_code() != code:
        raise ContractError('Controller code changed during canary')
    atomic_json(attempt / 'canary_verified.json', dict(verified_utc=now(), timeout_test=timeout,
                controller_code=code,
                snapshot_fingerprint=manifest['input_fingerprint'], runtime_fingerprint=manifest['runtime_fingerprint'],
                protected_canaries_unchanged=True, native_results=read_json(attempt / 'telemetry/canary.json'),
                worker_stopped=read_json(attempt / 'process_result.json')['worker_stopped']))
    print('Native canary passed: ' + str(attempt), flush=True)


def restore(candidate, stage):
    """Verify and copy a complete stage locally; never change a published pointer."""
    manifest = verify_snapshot(candidate)
    source = latest(candidate, stage, manifest)
    target = contained(candidate, 'restores/' + stage + '-' + str(time.time_ns()), existing=False)
    target.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / 'bundle', target / 'bundle')
    for name in ('complete.json', 'result.json', 'process_result.json', 'runtime_reads.json'):
        shutil.copy2(source / name, target / name)
    expected = read_json(source / 'result.json')['identity']
    read_stage(target, expected, artifacts.required(stage))
    verify_runtime_reads(target)
    atomic_json(target / 'restore_verified.json', dict(source=str(source), restored_utc=now(),
                result_sha256=sha(source / 'result.json'), adoption='not_adopted',
                dependency_snapshot_sha256=sha(candidate / 'snapshot.json')))
    print('Verified local restore: ' + str(target), flush=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'canary', 'preflight', 'run', 'verify', 'restore'])
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--base', default='spec-close-20260909-v2')
    parser.add_argument('--stage', choices=list(LIMITS), default='unified')
    parser.add_argument('--seconds', type=int)
    parser.add_argument('--deadline')
    parser.add_argument('--timeout-probe', action='store_true')
    args = parser.parse_args()
    candidate = candidate_path(args.candidate)
    if args.action == 'snapshot':
        snapshot(candidate, candidate_path(args.base))
    elif args.action == 'canary':
        canary(candidate, timeout=args.timeout_probe)
    elif args.action == 'preflight':
        preflight(candidate)
    elif args.action == 'run':
        run(candidate, args.stage, args.seconds or LIMITS[args.stage], deadline=args.deadline)
    elif args.action == 'restore':
        restore(candidate, args.stage)
    else:
        print(latest(candidate, args.stage, verify_snapshot(candidate)), flush=True)


if __name__ == '__main__':
    main()
