"""Native write/delete checks against disposable medium-integrity canaries only."""
from pathlib import Path
import ctypes
import os
import time

from pipeline.programme.core import ContractError, atomic_json


def run_canary(attempt):
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq
    attempt = Path(attempt)
    results = {}
    for engine in ('python', 'duckdb', 'arrow'):
        for zone, path in (('allowed', attempt / 'bundle' / (engine + '.out')),
                           ('protected', attempt / ('protected-' + engine)),
                           ('outside_new', attempt / ('new-' + engine))):
            try:
                if engine == 'python':
                    path.write_bytes(b'changed')
                elif engine == 'duckdb':
                    with duckdb.connect() as connection:
                        connection.execute("COPY (SELECT 1 AS x) TO '" + path.as_posix().replace("'", "''") + "' (HEADER)")
                else:
                    pq.write_table(pa.table({'x': [1]}), path)
                outcome = 'allowed'
            except (OSError, duckdb.Error) as exc:
                outcome = 'denied'
            results[engine + '_' + zone] = outcome
    # DeleteFile bypasses Python open hooks, as does Arrow cleanup above.
    delete = ctypes.WinDLL('kernel32', use_last_error=True).DeleteFileW
    delete.argtypes = [ctypes.c_wchar_p]
    delete.restype = ctypes.c_int
    results['native_delete_protected'] = 'allowed' if delete(str(attempt / 'protected-delete')) else 'denied'
    try:
        os.replace(attempt / 'protected-rename', attempt / 'bundle' / 'stolen')
        results['rename_protected'] = 'allowed'
    except OSError:
        results['rename_protected'] = 'denied'
    atomic_json(attempt / 'telemetry/canary.json', results)
    if any(value != ('allowed' if key.endswith('_allowed') else 'denied') for key, value in results.items()):
        raise ContractError('Native isolation canary failed')
    from pipeline.programme.bootstrap import guard
    guard(attempt)
    from pipeline import config, utils
    from pipeline.unified_holdings import build_unified_holdings
    if config.PROJECT_ROOT.resolve() != attempt / 'workspace':
        raise ContractError('Configuration smoke check escaped frozen workspace')
    config.RAW_DIR.mkdir(exist_ok=True)
    try:
        (config.RAW_DIR / 'forbidden-new-cache').mkdir()
    except PermissionError:
        pass
    else:
        raise ContractError('Guard allowed a new readonly cache directory')
    atomic_json(attempt / 'telemetry/config_smoke.json', dict(imports=True, existing_mkdir=True,
        new_readonly_mkdir_denied=True))
    if (attempt / 'cancellation_probe').exists():
        atomic_json(attempt / 'telemetry/cancellation_ready.json', dict(ready=True))
        while True:
            time.sleep(1)
