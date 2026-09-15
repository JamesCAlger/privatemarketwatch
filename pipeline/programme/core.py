"""Content identities and controller-owned, manifest-last stage completion."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat


class ContractError(ValueError):
    """The candidate cannot be consumed under its declared contract."""


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.pending-' + str(os.getpid()))
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def contained(root, relative, *, existing=True):
    """Reject ambiguous paths, aliases, junctions, symlinks and hard-linked files."""
    root = Path(root).absolute()
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ContractError('Expected a portable relative path')
    rel = PurePosixPath(relative)
    if rel.is_absolute() or any(part in ('', '.', '..') for part in relative.split('/')):
        raise ContractError('Unsafe relative path: ' + relative)
    # Include root ancestors: a candidate itself must not be reached through a junction.
    target = root.joinpath(*rel.parts)
    for path in [*reversed(target.parents), target]:
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ContractError('Reparse/symlink path: ' + str(path))
            if path.is_file() and info.st_nlink != 1:
                raise ContractError('Hard-linked file: ' + str(path))
    if existing and not target.is_file():
        raise ContractError('Missing regular file: ' + str(target))
    if not target.resolve().is_relative_to(root.resolve()):
        raise ContractError('Path escaped root')
    return target


def record(root, relative):
    path = contained(root, relative)
    before = path.stat()
    result = {'path': relative, 'bytes': before.st_size, 'sha256': sha(path)}
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ContractError('File changed while hashing: ' + relative)
    return result


def verify_records(root, records, *, exact=False, ignored_prefixes=()):
    names = [item['path'] for item in records]
    if len(names) != len(set(name.casefold() for name in names)):
        raise ContractError('Duplicate artifact paths')
    if exact:
        actual = {p.relative_to(root).as_posix() for p in Path(root).rglob('*') if p.is_file()}
        actual = {name for name in actual if not name.startswith(ignored_prefixes)}
        if actual != set(names):
            raise ContractError('Undeclared or missing input files: ' + repr(sorted(actual ^ set(names))[:20]))
    for expected in records:
        if set(expected) != {'path', 'bytes', 'sha256'} or record(root, expected['path']) != expected:
            raise ContractError('Artifact identity mismatch: ' + expected['path'])


def identity(stage, snapshot, runtime, contract, parents, controls):
    body = dict(format_version=1, stage=stage, snapshot=snapshot, runtime=runtime,
                artifact_contract=contract, parents=parents, controls=controls)
    if not all((snapshot, runtime, contract)):
        raise ContractError('Incomplete stage dependencies')
    return dict(body, fingerprint=digest(body))


def seal(attempt, expected_identity, required, *, artifacts_metadata=None):
    """Only the controller calls this after the native worker has exited successfully."""
    attempt = Path(attempt)
    if (attempt / 'complete.json').exists():
        raise ContractError('Completion is immutable')
    process = read_json(attempt / 'process_result.json')
    if process.get('exit_code') != 0 or process.get('worker_stopped') is not True:
        raise ContractError('Worker success and termination must be established')
    if process.get('input_fingerprint') != expected_identity['fingerprint']:
        raise ContractError('Worker result belongs to another dependency identity')
    if expected_identity.get('controls', {}).get('protected_outputs') == 'size-mtime-v1':
        from pipeline.programme.protection import verify
        verify(attempt)
    body = {k: v for k, v in expected_identity.items() if k != 'fingerprint'}
    if digest(body) != expected_identity['fingerprint']:
        raise ContractError('Malformed dependency identity')
    bundle = attempt / 'bundle'
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    if actual != set(required):
        raise ContractError('Artifact inventory mismatch: ' + repr(actual ^ set(required)))
    artifacts = [record(bundle, name) for name in sorted(required)]
    for name in required:
        with (bundle / name).open('r+b') as stream:
            os.fsync(stream.fileno())
    result = dict(format_version=1, identity=expected_identity, execution='complete',
                  quality='not_evaluated', artifacts=artifacts,
                  artifacts_metadata=artifacts_metadata or {}, created_utc=now(),
                  process_result_sha256=sha(attempt / 'process_result.json'),
                  adoption='not_adopted')
    atomic_json(attempt / 'result.json', result)
    verify_records(bundle, artifacts)
    atomic_json(attempt / 'complete.json', dict(format_version=1,
                result_sha256=sha(attempt / 'result.json'), fingerprint=expected_identity['fingerprint']))
    return result


def read_stage(attempt, expected_identity, required):
    attempt = Path(attempt)
    marker = read_json(attempt / 'complete.json')
    result = read_json(attempt / 'result.json')
    if marker != dict(format_version=1, result_sha256=sha(attempt / 'result.json'),
                      fingerprint=expected_identity['fingerprint']):
        raise ContractError('Stale or changed stage completion')
    if result['identity'] != expected_identity or result['execution'] != 'complete':
        raise ContractError('Mixed stage dependencies')
    if result['process_result_sha256'] != sha(attempt / 'process_result.json'):
        raise ContractError('Process record changed')
    if expected_identity.get('controls', {}).get('protected_outputs') == 'size-mtime-v1':
        from pipeline.programme.protection import verify
        verify(attempt)
    actual = {p.relative_to(attempt / 'bundle').as_posix()
              for p in (attempt / 'bundle').rglob('*') if p.is_file()}
    if actual != set(required) or {r['path'] for r in result['artifacts']} != set(required):
        raise ContractError('Required stage inventory changed')
    verify_records(attempt / 'bundle', result['artifacts'])
    return result
