"""Detect protected artifact changes independently of candidate output writers."""
from __future__ import annotations

import os
from pathlib import Path

from pipeline.programme.core import ContractError, read_json, sha


ROOTS = ('data/output', 'frontend/public/data', 'data/snapshots/baseline')


def inventory(repo):
    repo = Path(repo)
    records, unreadable, roots = {}, [], {}
    for relative in ROOTS:
        root = repo / relative
        roots[relative] = root.is_dir()
        if not roots[relative]:
            continue

        def onerror(error):
            unreadable.append(str(error.filename))

        for directory, _, names in os.walk(root, onerror=onerror):
            for name in names:
                path = Path(directory) / name
                key = path.relative_to(repo).as_posix()
                try:
                    info = path.stat()
                    records[key] = [info.st_size, info.st_mtime_ns]
                except OSError:
                    unreadable.append(key)
    return dict(records=records, unreadable=sorted(unreadable), roots=roots)


def compare(before, after):
    changed = sorted(path for path in set(before['records']) | set(after['records'])
                     if before['records'].get(path) != after['records'].get(path))
    roots_changed = before['roots'] != after['roots']
    unreadable = sorted(set(before['unreadable']) | set(after['unreadable']))
    return dict(unchanged=not (changed or roots_changed or unreadable),
                changed_paths=changed, roots_changed=roots_changed, unreadable_paths=unreadable,
                files_before=len(before['records']), files_after=len(after['records']),
                method='size and nanosecond mtime; does not claim byte-level equivalence')


def verify(attempt):
    attempt = Path(attempt)
    process = read_json(attempt / 'process_result.json')
    path = attempt / 'protected_result.json'
    if (not path.is_file() or process.get('protected_outputs_unchanged') is not True
            or process.get('protected_result_sha256') != sha(path)):
        raise ContractError('Protected output proof is missing, changed or failed')
    result = read_json(path)
    before = read_json(attempt / 'protected_before.json')
    after = read_json(attempt / 'protected_after.json')
    if (result.get('before_sha256') != sha(attempt / 'protected_before.json')
            or result.get('after_sha256') != sha(attempt / 'protected_after.json')
            or compare(before, after) != {key: value for key, value in result.items()
                                         if key not in ('before_sha256', 'after_sha256')}
            or result.get('unchanged') is not True):
        raise ContractError('Protected output inventory proof is invalid')
    return result
