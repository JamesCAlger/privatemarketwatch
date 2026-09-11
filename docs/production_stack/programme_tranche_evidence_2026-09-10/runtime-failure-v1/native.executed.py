"""Windows candidate execution: Codex command sandbox plus low-integrity writes.

No model is started. No fallback to unrestricted execution is provided. The
extra integrity boundary is required: the installed sandbox's read-only profile
alone did not prevent Arrow's failed-write cleanup from deleting a canary.
"""
from __future__ import annotations

import json
import hashlib
import os
import platform
from pathlib import Path
import shutil
import site
import subprocess
import sys
import time

from pipeline.programme.core import ContractError, sha


def require_windows():
    if os.name != 'nt':
        raise ContractError('This execution backend requires Windows; no unsafe fallback')
    try:
        import win32security  # noqa: F401
    except ImportError as exc:
        raise ContractError('Install the explicit programme Windows requirements first') from exc


def codex_executable():
    require_windows()
    explicit = os.environ.get('PROGRAMME_CODEX_EXE')
    if explicit:
        path = Path(explicit).resolve(strict=True)
        if path.suffix.lower() != '.exe':
            raise ContractError('PROGRAMME_CODEX_EXE must name a native executable')
        return path
    package = Path(os.environ['APPDATA']) / 'npm/node_modules/@openai/codex'
    choices = sorted(package.glob('node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe'))
    if len(choices) != 1:
        raise ContractError('Set PROGRAMME_CODEX_EXE to one installed native Codex CLI')
    return choices[0].resolve()


def label_writable(path, attempt):
    """Only new candidate-local output directories may receive a low label."""
    require_windows()
    import win32security
    path, attempt = Path(path).resolve(), Path(attempt).resolve()
    permitted = {attempt / 'bundle', attempt / 'temp', attempt / 'workspace/data/output', attempt / 'telemetry'}
    if path not in permitted or not path.is_dir():
        raise ContractError('Refusing to relabel anything except candidate output directories')
    sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor('S:(ML;OICI;NW;;;LW)', 1)
    win32security.SetFileSecurity(str(path), win32security.LABEL_SECURITY_INFORMATION, sd)


def lower_integrity():
    require_windows()
    import win32api
    import win32con
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(),
                                           win32con.TOKEN_ADJUST_DEFAULT | win32con.TOKEN_QUERY)
    try:
        low = win32security.ConvertStringSidToSid('S-1-16-4096')
        win32security.SetTokenInformation(token, win32security.TokenIntegrityLevel, (low, 0x20))
        actual = win32security.GetTokenInformation(token, win32security.TokenIntegrityLevel)
        sid = actual[0] if isinstance(actual, tuple) else actual
        if win32security.ConvertSidToStringSid(sid) != 'S-1-16-4096':
            raise ContractError('Worker integrity was not lowered')
    finally:
        token.Close()


def command(attempt, seconds, *, probe=False):
    attempt = Path(attempt).resolve()
    workspace = attempt / 'workspace'
    executable = codex_executable()
    fs = {':minimal': 'read', str(attempt): 'read', str(Path(sys.executable).parent): 'read',
          ':tmpdir': 'deny', ':slash_tmp': 'deny'}
    fs[str(Path(site.getusersitepackages()).resolve())] = 'read'
    for rel in ('bundle', 'temp', 'workspace/data/output', 'telemetry'):
        fs[str(attempt / rel)] = 'write'
    profile = '{' + ', '.join(json.dumps(k) + '=' + json.dumps(v) for k, v in fs.items()) + '}'
    profile_name = 'programme_' + hashlib.sha256(str(attempt).encode()).hexdigest()[:16]
    args = [str(executable), 'sandbox', '-C', str(workspace), '-P', profile_name,
            '-c', 'permissions.' + profile_name + '.filesystem=' + profile,
            '-c', 'permissions.' + profile_name + '.network.enabled=false',
            '-c', 'windows.sandbox="elevated"', '-c', 'project_root_markers=[]',
            sys.executable, '-B', '-m', 'pipeline.programme.bootstrap',
            '--attempt', str(attempt), '--seconds', str(seconds)]
    if probe:
        args.append('--probe')
    return args


def environment(attempt):
    # Allowlist operating-system/interpreter variables; do not forward API keys.
    allowed = {'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATH', 'PATHEXT',
               'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES',
               'PROGRAMFILES(X86)', 'COMMONPROGRAMFILES', 'COMMONPROGRAMFILES(X86)',
               'USERNAME', 'USERDOMAIN', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE',
               'CODEX_HOME'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
               PYTHON_DOTENV_DISABLED='1',
               PYTHONPYCACHEPREFIX=str(Path(attempt) / 'temp/python-cache'),
               OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2',
               NUMEXPR_NUM_THREADS='2', TEMP=str(Path(attempt) / 'temp'), TMP=str(Path(attempt) / 'temp'))
    return env


def runtime_identity():
    """Pin runtime executable, installed distribution RECORDs and native binaries.

Actual Python/source reads are also inventoried by the bootstrap and rechecked
on completion/resume. RECORD metadata alone is not presented as file integrity.
"""
    import importlib.metadata
    records = []
    runtime_root = Path(sys.executable).resolve().parent
    runtime_roots = [runtime_root, Path(site.getusersitepackages()).resolve()]
    files = set()
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata['Name']
        entries = list(distribution.files or [])
        for entry in entries:
            # Normalize RECORD ../Scripts paths lexically. Reparse resolution
            # for every runtime file adds minutes to Windows startup; content
            # hashes still cover every declared file and consumed paths are
            # resolved again when the controller validates the read ledger.
            path = Path(os.path.abspath(distribution.locate_file(entry)))
            if any(path.is_relative_to(root) for root in runtime_roots) and '__pycache__' not in path.parts and path.is_file():
                files.add(path)
        manifest = [p for p in entries if p.name == 'RECORD' and '.dist-info' in str(p)]
        records.append(dict(name=name, version=distribution.version,
                            record_sha256=sha(distribution.locate_file(manifest[0])) if manifest else None))
    executable = Path(sys.executable).resolve()
    native = [executable, *codex_executable().parent.glob('*.exe'), *executable.parent.glob('python*.dll')]
    for directory in ('Lib', 'DLLs', 'Library/bin'):
        for path in (runtime_root / directory).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix.lower() in ('.py', '.pyd', '.dll', '.pth'):
                files.add(path)
    total = sum(path.stat().st_size for path in files)
    if total > 20 * 1024**3 or len(files) > 250000:
        raise ContractError('Runtime identity exceeds bounded inventory limit')
    started = time.monotonic()
    content = []
    for index, path in enumerate(sorted(files)):
        before = path.stat()
        content.append(dict(path=path.as_posix(), bytes=before.st_size, sha256=sha(path)))
        if (before.st_size, before.st_mtime_ns) != (path.stat().st_size, path.stat().st_mtime_ns):
            raise ContractError('Runtime changed while fingerprinting')
        if time.monotonic() - started > 600:
            raise ContractError('Runtime fingerprint exceeded ten minutes')
        if index and index % 20000 == 0:
            print('Runtime content verified: ' + str(index) + '/' + str(len(files)), flush=True)
    return dict(python=sys.version, platform=sys.platform, os_build=platform.version(),
                distributions=sorted(records, key=lambda x: (x['name'].lower(), x['version'])),
                binaries=[{'path': str(p), 'sha256': sha(p)} for p in native],
                content_roots=[str(root) for root in runtime_roots], content=content,
                environment_policy='os_allowlist; explicitly pinned environment and user-site packages; thread_limits=2; no network',
                backend='codex-elevated-command+windows-low-integrity-v1')
