"""Controller for frozen offline candidates. Completion never adopts production."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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
STAGES = ('unified', 'identity', 'evidence','returns','frontend')
PARENTS = {'unified': None, 'identity': 'unified', 'evidence': 'identity','returns':'identity','frontend':'returns'}
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
        'pipeline/programme/protection.py',
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


def snapshot(candidate, base, *, current_code=False, sector_decisions=None,identity_registry=None,rule_inputs=(),retired_rules=()):
    if candidate.exists():
        raise ContractError('Snapshot already exists; choose a new immutable candidate')
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
    roots=('pipeline','schemas','scripts') if current_code else ('pipeline/programme',)
    overlay=[]
    for directory in roots:
        if current_code:
            # Remove only stale code copies inside this newly created candidate;
            # cached data and the original frozen snapshot remain untouched.
            for prior in (frozen/directory).rglob('*'):
                if prior.is_file() and prior.suffix in ('.py','.json'):
                    resolved=prior.resolve()
                    if not resolved.is_relative_to(frozen.resolve()):
                        raise ContractError('Frozen code path escaped candidate')
                    if not (ROOT/prior.relative_to(frozen)).is_file():
                        prior.unlink()
        for source in (ROOT / directory).rglob('*'):
            if source.is_file() and '__pycache__' not in source.parts and source.suffix in ('.py', '.json'):
                relative = source.relative_to(ROOT).as_posix()
                destination = contained(frozen, relative, existing=False)
                destination.parent.mkdir(parents=True, exist_ok=True)
                before=sha(source)
                shutil.copy2(source, destination)
                if sha(destination)!=before or sha(source)!=before:
                    raise ContractError('Source changed during current-code snapshot: '+relative)
                overlay.append(dict(path=relative,sha256=before))
    if current_code:
        relative='data/reference/quarter_acceptance_programme_thresholds.json'
        (frozen/relative).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/relative,frozen/relative)
        overlay.append(dict(path=relative,sha256=sha(ROOT/relative)))
        from pipeline.programme.source_snapshot import include_sources
        source_inventory=include_sources(ROOT,frozen)
        atomic_json(frozen/'data/reference/programme_source_inventory.json',source_inventory)
    for review in retired_rules:
        if not current_code: raise ContractError('Reviewed retirement requires current-code mode')
        from pipeline.programme.rule_snapshot import include_retirement
        overlay.append(include_retirement(ROOT,frozen,review))
    for value in rule_inputs:
        if not current_code: raise ContractError('Reviewed rule overlay requires current-code mode')
        source=Path(value).resolve()
        allowed=(ROOT/'data/overrides/agent_investigate_rules').resolve()
        if not source.is_relative_to(allowed) or source.suffix!='.json':
            raise ContractError('Rule overlay must name an existing investigate-rule JSON')
        from pipeline.agent_rule import validate_rule
        errors=validate_rule(read_json(source))
        if errors: raise ContractError('Invalid reviewed rule overlay: '+repr(errors))
        relative=source.relative_to(ROOT).as_posix()
        destination=contained(frozen,relative)
        prior=sha(destination);before=sha(source)
        shutil.copy2(source,destination)
        if sha(source)!=before or sha(destination)!=before: raise ContractError('Reviewed rule input changed during snapshot')
        overlay.append(dict(path=relative,sha256=before,prior_sha256=prior,role='reviewed rule amendment; admission evaluated separately'))
    if sector_decisions is not None:
        if not current_code:
            raise ContractError('Decision overlay requires current-code mode')
        from pipeline.sector_enrichment import load_decisions
        decision_path=Path(sector_decisions).resolve()
        decision_bundle,membership=load_decisions(decision_path,frozen/'data/reference/gics_sub_industries.json')
        for source,relative in ((decision_path,'data/reference/sector_enrichment/sector_decisions.json'),
                                (membership,'data/reference/sector_enrichment/'+decision_bundle['membership']['path'])):
            before=sha(source)
            destination=contained(frozen,relative,existing=False)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,destination)
            if sha(source)!=before or sha(destination)!=before:
                raise ContractError('Sector decision input changed during snapshot')
            overlay.append(dict(path=relative,sha256=before))
    if identity_registry is not None:
        if not current_code: raise ContractError('Registry input requires current-code mode')
        from pipeline.durable_identity import VERSION
        import duckdb
        source=Path(identity_registry).resolve()
        before=sha(source)
        with duckdb.connect(str(source),read_only=True) as con:
            if con.execute('SELECT version FROM registry_meta').fetchall()!=[(VERSION,)]:
                raise ContractError('Unsupported pinned identity registry')
        relative='data/reference/identity_registry.duckdb'
        destination=contained(frozen,relative,existing=False)
        shutil.copy2(source,destination)
        if sha(source)!=before or sha(destination)!=before:
            raise ContractError('Registry input changed during snapshot')
        overlay.append(dict(path=relative,sha256=before))
    shutil.copy2(ROOT / 'requirements-programme-windows.txt', frozen / 'requirements-programme-windows.txt')
    records = [record(frozen, p.relative_to(frozen).as_posix()) for p in sorted(frozen.rglob('*')) if p.is_file()]
    runtime = native.runtime_identity()
    atomic_json(candidate / 'runtime.json', runtime)
    manifest = dict(format_version=1, created_utc=now(), artifacts=records,
                    input_fingerprint=digest(records), starting_snapshot=legacy['input_fingerprint'],
                    existing_absent_controls=legacy.get('existing_absent_controls', []),
                    runtime_fingerprint=digest(runtime), current_code=current_code,code_overlay=overlay,
                    role='frozen data plus current governed code; candidate only' if current_code
                    else 'frozen legacy inputs plus supported runner; no financial rule changes')
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
    runtime = read_json(candidate / 'runtime.json')
    if digest(runtime) != manifest['runtime_fingerprint']:
        raise ContractError('Recorded runtime identity changed')
    if digest(native.runtime_for_record(runtime)) != manifest['runtime_fingerprint']:
        raise ContractError('Runtime changed since snapshot')
    return manifest


def stage_identity(candidate, stage, manifest, parent=None):
    parents = {} if parent is None else {PARENTS[stage]: {
        'attempt': parent.name, 'result_sha256': sha(parent / 'result.json'),
        'holdings_sha256': sha(parent / 'bundle/private_markets_holdings.csv')}}
    if stage == 'frontend':
        evidence=latest(candidate,'evidence',manifest)
        parents['evidence']={'attempt':evidence.name,'result_sha256':sha(evidence/'result.json')}
    return identity(stage, manifest['input_fingerprint'], manifest['runtime_fingerprint'],
                    artifacts.contract_identity(stage), parents,
                    dict(financial_contract='financial-contract.v2', contested_assignment=True, use_registry=True,
                         dotenv='empty candidate-local file; no ambient dotenv values',
                         controller_code=controller_code(),
                         protected_outputs='size-mtime-v1',
                         network=False, memory_limit_bytes=None, time_limit_seconds=None))


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


def stop_owned_worker(attempt):
    """Wait for the identified worker, including explicit controller cancellation.

    Killing the sandbox launcher alone does not prove its worker exited. PID
    creation time prevents cleanup from terminating a later unrelated process.
    """
    import psutil
    telemetry=Path(attempt)/'telemetry/worker.json'
    if not telemetry.is_file(): return True
    worker=read_json(telemetry)
    try:
        process=psutil.Process(worker['pid'])
        if process.create_time()!=worker.get('process_created'):
            if 'process_created' not in worker:
                raise ContractError('Worker creation identity is missing; termination cannot be certified')
            return True
        process.kill()
        process.wait()
    except psutil.NoSuchProcess:
        pass
    return True


def launch(attempt, fingerprint, *, probe=False, cancellation_probe=False):
    import psutil
    from pipeline.programme.protection import inventory, compare
    command = native.command(attempt, probe=probe)
    protected_before = inventory(ROOT)
    atomic_json(attempt / 'protected_before.json', protected_before)
    started = time.monotonic()
    with (attempt / 'process.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=attempt / 'workspace', env=native.environment(attempt),
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        atomic_json(attempt / 'process.json', dict(controller_pid=os.getpid(), launcher_pid=process.pid,
                    command=command, started_utc=now(), seconds=None, input_fingerprint=fingerprint))
        last = 0
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if cancellation_probe and (attempt / 'telemetry/cancellation_ready.json').exists():
                    stop_owned_worker(attempt)
                    process.kill()
                    process.wait()
                    break
                if elapsed - last >= 30:
                    last = elapsed
                    telemetry = attempt / 'telemetry/resources.json'
                    stats = read_json(telemetry) if telemetry.exists() else {}
                    print(attempt.name + ': ' + str(round(elapsed)) + 's; private GiB=' +
                          str(round(stats.get('private_bytes', 0) / 1024**3, 2)), flush=True)
                time.sleep(1)
        finally:
            cleanup_error=None
            try:
                stopped=stop_owned_worker(attempt)
            except Exception as error:
                stopped=False
                cleanup_error=str(error)
            if process.poll() is None:
                process.kill()
                process.wait()
            telemetry = attempt / 'telemetry/worker.json'
            worker = read_json(telemetry) if telemetry.exists() else {}
            protected_after = inventory(ROOT)
            atomic_json(attempt / 'protected_after.json', protected_after)
            protected_result = compare(protected_before, protected_after)
            protected_result.update(before_sha256=sha(attempt / 'protected_before.json'),
                                    after_sha256=sha(attempt / 'protected_after.json'))
            atomic_json(attempt / 'protected_result.json', protected_result)
            atomic_json(attempt / 'process_result.json', dict(exit_code=process.returncode,
                elapsed_seconds=time.monotonic() - started, worker_stopped=stopped,
                input_fingerprint=fingerprint, worker_pid=worker.get('pid'),
                cleanup_error=cleanup_error,
                protected_result_sha256=sha(attempt / 'protected_result.json'),
                protected_outputs_unchanged=protected_result['unchanged'],
                usage=dict(agent_tokens=None, reason='command-only process; agent telemetry unavailable')))
    if not protected_result['unchanged']:
        raise ContractError('Protected output inventory changed; attempt cannot complete')
    if process.returncode or not stopped:
        print((attempt / 'process.log').read_text(encoding='utf-8', errors='replace')[-5000:], flush=True)
        raise ContractError('Worker failed or termination not established; incomplete attempt retained')


def capture_runtime_reads(attempt):
    ledger = read_json(attempt / 'bundle/read_ledger.json')
    results = []
    frozen_runtime = read_json(attempt.parents[1] / 'runtime.json')
    runtime_roots = [Path(root).resolve() for root in frozen_runtime['content_roots']]
    declared = {item['path']: item for item in frozen_runtime['content']}
    policy = frozen_runtime.get('identity_policy', 'physical-content-v1')
    if policy not in ('package-metadata-v1', 'physical-content-v1'):
        raise ContractError('Unsupported runtime read ledger policy: ' + str(policy))
    for value in ledger['python_paths']:
        path = Path(value).resolve()
        if path.is_relative_to(attempt.resolve()) or not path.is_file():
            continue
        if not any(path.is_relative_to(root) for root in runtime_roots):
            raise ContractError('Undeclared external read: ' + str(path))
        item = dict(path=path.as_posix(), bytes=path.stat().st_size, sha256=sha(path))
        if ((policy == 'physical-content-v1' or item['path'] in declared)
                and declared.get(item['path']) != item):
            raise ContractError('Runtime read was not pinned before execution: ' + str(path))
        results.append(item)
    atomic_json(attempt / 'runtime_reads.json', dict(roots=[str(root) for root in runtime_roots], records=results,
        identity_policy=policy,
        role='observed Python reads captured after execution; installed package contents are trusted'
             if policy == 'package-metadata-v1' else 'observed Python reads verified against frozen physical inventory'))


def verify_runtime_reads(attempt):
    record_set = read_json(attempt / 'runtime_reads.json')
    result = read_json(attempt / 'process_result.json')
    if 'protected_result_sha256' in result:
        from pipeline.programme.protection import verify
        verify(attempt)
    if sha(attempt / 'runtime_reads.json') != result['runtime_reads_sha256']:
        raise ContractError('Runtime dependency ledger changed')
    runtime_roots = [Path(root).resolve() for root in record_set['roots']]
    for item in record_set['records']:
        path = Path(item['path']).resolve()
        if not any(path.is_relative_to(root) for root in runtime_roots) or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ContractError('A consumed runtime dependency changed: ' + item['path'])


def run(candidate, stage):
    with heavy_lock(candidate):
        manifest = verify_snapshot(candidate)
        canaries = list((candidate / 'attempts').glob('canary-*/canary_verified.json'))
        proofs = [read_json(path) for path in canaries]
        if not any(proof.get('snapshot_fingerprint') == manifest['input_fingerprint'] and
                   proof.get('runtime_fingerprint') == manifest['runtime_fingerprint'] and
                   proof.get('controller_code') == controller_code() and
                   proof.get('cancellation_test') is False for proof in proofs):
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
        attempt = prepare_attempt(candidate, stage + '-' + str(len(existing) + 1).zfill(2))
        if parent:
            for name in artifacts.required(PARENTS[stage]):
                if name not in ('summary.json','read_ledger.json'):
                    shutil.copy2(parent/'bundle'/name,attempt/'workspace/data/output'/name)
        if stage == 'frontend':
            evidence=latest(candidate,'evidence',manifest)
            for name in artifacts.required('evidence'):
                if name not in ('summary.json','read_ledger.json'):
                    shutil.copy2(evidence/'bundle'/name,attempt/'workspace/data/output'/name)
        atomic_json(attempt / 'inputs.json', dict(stage=stage, identity=expected))
        launch(attempt, expected['fingerprint'])
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
            connection.execute("SET memory_limit='-1'")
            connection.execute("SET temp_directory='" + (attempt / 'temp').as_posix().replace("'", "''") + "'")
            metadata = {name: artifacts.verify_pair(attempt / 'bundle' / name, connection)
                        for name in artifacts.STAGE_CSVS[stage]}
            if stage == 'unified':
                artifacts.verify_audit(attempt / 'bundle/agent_fix_application_audit.csv', connection)
        seal(attempt, expected, artifacts.required(stage), artifacts_metadata=metadata)
        print('Controller sealed stage: ' + str(attempt), flush=True)
        return attempt


def verify_runtime_identity(candidate, manifest):
    runtime = read_json(candidate / 'runtime.json')
    if digest(native.runtime_for_record(runtime)) != manifest['runtime_fingerprint']:
        raise ContractError('Runtime identity changed during execution')
    if digest(runtime) != manifest['runtime_fingerprint']:
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
    raise ContractError('This exact candidate needs a verified representative preflight')


def preflight(candidate):
    with heavy_lock(candidate):
        code = controller_code()
        manifest = verify_snapshot(candidate)
        attempt = prepare_attempt(candidate, 'preflight-' + str(time.time_ns()))
        atomic_json(attempt / 'inputs.json', dict(stage='preflight',
            identity=dict(fingerprint=manifest['input_fingerprint'], parents={})))
        launch(attempt, manifest['input_fingerprint'])
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
        if set(summary['stages']) != set(STAGES):
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
        print('Representative preflight verified: ' + str(attempt), flush=True)


def digest_empty_file():
    import hashlib
    return hashlib.sha256(b'').hexdigest()


def canary(candidate, *, cancellation=False):
    code = controller_code()
    manifest = verify_snapshot(candidate)
    attempt = prepare_attempt(candidate, 'canary-' + str(time.time_ns()), minimal=True)
    names = ['protected-' + name for name in ('python', 'duckdb', 'arrow', 'delete', 'rename')]
    for name in names:
        (attempt / name).write_bytes(b'preserve me')
    if cancellation:
        (attempt / 'cancellation_probe').touch()
    try:
        launch(attempt, manifest['input_fingerprint'], probe=True, cancellation_probe=cancellation)
    except ContractError:
        result = read_json(attempt / 'process_result.json')
        if (not cancellation or result['exit_code'] == 0 or result['worker_stopped'] is not True
                or result.get('protected_outputs_unchanged') is not True):
            raise
    if not all((attempt / name).read_bytes() == b'preserve me' for name in names):
        raise ContractError('Canary protection failed: original content changed')
    if not (attempt / 'telemetry/canary.json').is_file():
        raise ContractError('Canary did not reach native checks')
    if not (attempt / 'telemetry/config_smoke.json').is_file():
        raise ContractError('Canary did not complete configuration smoke checks')
    if controller_code() != code:
        raise ContractError('Controller code changed during canary')
    atomic_json(attempt / 'canary_verified.json', dict(verified_utc=now(), cancellation_test=cancellation,
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
    if read_json(source / 'process_result.json').get('protected_result_sha256'):
        for name in ('protected_before.json', 'protected_after.json', 'protected_result.json'):
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
    parser.add_argument('--stage', choices=STAGES, default='unified')
    parser.add_argument('--cancellation-probe', action='store_true')
    parser.add_argument('--current-code', action='store_true',help='Freeze current pipeline/scripts/schemas over the recorded cached data')
    parser.add_argument('--sector-decisions',type=Path,help='Pin an admitted P5 bundle and its observation membership')
    parser.add_argument('--identity-registry',type=Path,help='Pin an immutable prior durable registry snapshot')
    parser.add_argument('--rule-input',type=Path,action='append',default=[],help='Explicitly freeze a reviewed amendment to an existing investigate rule')
    parser.add_argument('--retired-rule',type=Path,action='append',default=[],help='Explicitly freeze a source-reviewed B2 retirement, retaining original bytes')
    args = parser.parse_args()
    candidate = candidate_path(args.candidate)
    if args.action == 'snapshot':
        snapshot(candidate, candidate_path(args.base),current_code=args.current_code,sector_decisions=args.sector_decisions,
            identity_registry=args.identity_registry,rule_inputs=args.rule_input,retired_rules=args.retired_rule)
    elif args.action == 'canary':
        canary(candidate, cancellation=args.cancellation_probe)
    elif args.action == 'preflight':
        preflight(candidate)
    elif args.action == 'run':
        run(candidate, args.stage)
    elif args.action == 'restore':
        restore(candidate, args.stage)
    else:
        print(latest(candidate, args.stage, verify_snapshot(candidate)), flush=True)


if __name__ == '__main__':
    main()
