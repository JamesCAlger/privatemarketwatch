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
    # DLL/executable search must not inherit arbitrary unrelated tool directories.
    python_root = Path(sys.executable).resolve().parent
    windows = Path(os.environ.get('SYSTEMROOT', 'C:/Windows'))
    env['PATH'] = os.pathsep.join(str(path) for path in (
        python_root, python_root / 'DLLs', python_root / 'Library/bin',
        python_root / 'Scripts', windows / 'System32', windows / 'System32/WindowsPowerShell/v1.0',
        windows / 'System32/Wbem', windows, codex_executable().parent))
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
               PYTHON_DOTENV_DISABLED='1',
               PYTHONPYCACHEPREFIX=str(Path(attempt) / 'temp/python-cache'),
               OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2',
               NUMEXPR_NUM_THREADS='2', TEMP=str(Path(attempt) / 'temp'), TMP=str(Path(attempt) / 'temp'))
    return env


def package_metadata_files(package_roots):
    """Inventory actual installed metadata, including incomplete legacy manifests."""
    files = set()
    for root in package_roots:
        root = Path(root)
        for pattern in ('*.dist-info', '*.egg-info'):
            for metadata in root.glob(pattern):
                candidates = [metadata] if metadata.is_file() else metadata.rglob('*')
                for path in candidates:
                    if path.is_file() and '__pycache__' not in path.parts:
                        files.add(Path(os.path.abspath(path)))
    return files


def runtime_identity():
    """Hash the physical environment, including files omitted by package manifests.

    Windows system components remain an explicit trusted OS boundary. Existing
    bytecode caches are excluded because lookup is redirected into each attempt.
    """
    import importlib.metadata
    from pipeline.programme.runtime_content import hash_files
    started = time.monotonic()
    records = []
    runtime_root = Path(sys.executable).resolve().parent
    runtime_roots = [runtime_root, Path(site.getusersitepackages()).resolve()]
    files = physical_runtime_files(runtime_roots)
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata['Name']
        entries = list(distribution.files or [])
        manifest = [p for p in entries if p.name == 'RECORD' and '.dist-info' in str(p)]
        records.append(dict(name=name, version=distribution.version,
                            record_sha256=sha(distribution.locate_file(manifest[0])) if manifest else None))
    executable = Path(sys.executable).resolve()
    native = [executable, *codex_executable().parent.glob('*.exe'), *executable.parent.glob('python*.dll')]
    total = sum(path.stat().st_size for path in files)
    if total > 20 * 1024**3 or len(files) > 300000:
        raise ContractError('Runtime identity exceeds bounded inventory limit')
    content = hash_files(files, started)
    return dict(python=sys.version, platform=sys.platform, os_build=platform.version(),
                distributions=sorted(records, key=lambda x: (x['name'].lower(), x['version'])),
                binaries=[{'path': str(p), 'sha256': sha(p)} for p in native],
                content_roots=[str(root) for root in runtime_roots], content=content,
                inventory_policy='physical recursive tree; only __pycache__ excluded; reparse aliases forbidden',
                trusted_boundary='Windows OS build and system components; native OS reads are not claimed as a complete trace',
                environment_policy='os_allowlist; PATH restricted to pinned Python and sandbox binaries plus Windows; thread_limits=2; no network',
                backend='codex-elevated-command+windows-low-integrity-v1')


def physical_runtime_files(roots):
    """Fail closed on aliases; include arbitrary package data and configuration."""
    files = set()
    def fail(error):
        raise error
    for root in roots:
        if not Path(root).is_dir():
            raise ContractError('Declared runtime root is missing: ' + str(root))
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail):
            dirs[:] = [name for name in dirs if name != '__pycache__']
            for name in [*dirs, *names]:
                path = Path(directory) / name
                if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
                    raise ContractError('Runtime reparse alias requires explicit resolution: ' + str(path))
            files.update(Path(os.path.abspath(Path(directory) / name)) for name in names)
    return files
