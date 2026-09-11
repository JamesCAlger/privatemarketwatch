"""Bounded parallel content hashing; every physical input still gets a hash."""
from concurrent.futures import ThreadPoolExecutor
import time

from pipeline.programme.core import ContractError, sha


def hash_file(path):
    before = path.stat()
    result = dict(path=path.as_posix(), bytes=before.st_size, sha256=sha(path))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ContractError('Runtime changed while fingerprinting: ' + str(path))
    return result


def hash_files(files, started, *, seconds=600):
    ordered = sorted(files)
    content = []
    # A bounded batch avoids allocating 250,000 Future objects. Threads overlap
    # Windows file-open latency; memory is bounded independently of tree size.
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix='runtime-hash') as pool:
        for offset in range(0, len(ordered), 512):
            if time.monotonic() - started > seconds:
                raise ContractError('Runtime fingerprint exceeded ten minutes')
            content.extend(pool.map(hash_file, ordered[offset:offset+512]))
            if offset // 20000 != (offset + 512) // 20000:
                print('Runtime content verified: ' + str(len(content)) + '/' + str(len(files)), flush=True)
    if time.monotonic() - started > seconds:
        raise ContractError('Runtime fingerprint exceeded ten minutes')
    return content
