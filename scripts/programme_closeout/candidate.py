"""Frozen isolated candidate snapshots and manifest-last bundles.

The legacy pipeline executes only in a copied workspace. This adapter does not
adopt/publish data or rewrite the original project's config.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]


def process_private_bytes(proc):
    if os.name!='nt':return None
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[
            (name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage',
            'QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
    counts=Counters();counts.cb=ctypes.sizeof(counts)
    fn=ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    if not fn(int(proc._handle),ctypes.byref(counts),counts.cb):raise OSError('Cannot monitor child memory')
    return counts.PrivateUsage


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def atomic_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.pending-'+str(os.getpid()))
    with temp.open('x',encoding='utf-8') as f:
        json.dump(value,f,sort_keys=True,indent=2)
        f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def safe_relative(root, rel):
    root=Path(root).resolve()
    target=(root/rel).resolve()
    if not target.is_relative_to(root) or target==root:
        raise ValueError('Path outside bundle root: '+str(rel))
    return target


def record_file(root,path):
    path=Path(path)
    return dict(path=path.relative_to(root).as_posix(),bytes=path.stat().st_size,sha256=sha(path))


def verify_files(root, records):
    for item in records:
        path=safe_relative(root,item['path'])
        if not path.is_file() or path.stat().st_size!=item['bytes'] or sha(path)!=item['sha256']:
            raise ValueError('Missing/changed artifact: '+item['path'])


def commit_bundle(root, artifacts, input_fingerprint, quality, extra=None):
    root=Path(root)
    if (root/'complete.json').exists():
        raise ValueError('Completed bundle is immutable')
    if quality not in ('pass','fail','unassessable','not_evaluated'):
        raise ValueError('Invalid quality state')
    if not artifacts:
        raise ValueError('A completed bundle must name artifacts')
    records=[record_file(root,safe_relative(root,p)) for p in artifacts]
    manifest=dict(format_version=1,input_fingerprint=input_fingerprint,artifacts=records,
                  execution='complete',quality=quality,created_utc=now(),extra=extra or {})
    atomic_json(root/'result.json',manifest)
    verify_files(root,records)
    atomic_json(root/'complete.json',dict(result_sha256=sha(root/'result.json'),
                input_fingerprint=input_fingerprint,committed_utc=now()))
    return manifest


def read_bundle(root, expected_input):
    root=Path(root)
    completion=json.loads((root/'complete.json').read_text())
    if completion['input_fingerprint']!=expected_input:
        raise ValueError('Stale input fingerprint')
    if sha(root/'result.json')!=completion['result_sha256']:
        raise ValueError('Changed result manifest')
    result=json.loads((root/'result.json').read_text())
    if result['input_fingerprint']!=expected_input:
        raise ValueError('Result/input mismatch')
    verify_files(root,result['artifacts'])
    return result


def snapshot(candidate):
    candidate=Path(candidate).resolve()
    if not candidate.is_relative_to(ROOT/'data/programme/candidates'):
        raise ValueError('Candidate must be below data/programme/candidates')
    if candidate.exists():
        raise ValueError('Use a new candidate name')
    candidate.mkdir(parents=True)
    frozen=candidate/'frozen';frozen.mkdir()
    files=[]
    for base in ('pipeline','scripts'):
        files.extend(p for p in (ROOT/base).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.tsv','.sql'))
    for name in ('AGENTS.md','requirements.txt','pyproject.toml','pytest.ini'):
        if (ROOT/name).is_file():files.append(ROOT/name)
    files.extend(p for p in (ROOT/'data/output').iterdir() if p.is_file())
    files.extend(p for p in (ROOT/'data/reference').rglob('*') if p.is_file())
    files.extend(p for p in (ROOT/'data/overrides').rglob('*') if p.is_file())
    # Cache/input templates are small; no SEC/raw-filing downloads or junctions.
    files.extend(p for p in (ROOT/'data/raw/filing_templates').glob('*.json'))
    total=sum(p.stat().st_size for p in files)
    print(f'Freeze {len(files)} inputs; {total/1024**3:.2f} GiB',flush=True)
    records=[]
    for i,src in enumerate(sorted(set(files))):
        rel=src.relative_to(ROOT)
        dst=frozen/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        before=(src.stat().st_size,src.stat().st_mtime_ns)
        shutil.copy2(src,dst)
        if before!=(src.stat().st_size,src.stat().st_mtime_ns):
            raise ValueError('Input changed during snapshot: '+str(rel))
        records.append(record_file(frozen,dst))
        if i%150==0:print(f'Snapshot files {i+1}/{len(files)}',flush=True)
    manifest=dict(format_version=1,created_utc=now(),artifacts=records,
        code_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        dirty_worktree=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).splitlines(),
        python=sys.version,byte_limit=None,original_root=str(ROOT),
        snapshot_role='current cached output/input dependencies; raw source cache not replicated',
        existing_absent_controls=[str(p.relative_to(ROOT)) for p in
            (ROOT/'data/output/lien_cache.csv',ROOT/'data/overrides/fund_strategy_overrides.json') if not p.exists()])
    manifest['input_fingerprint']=fingerprint(records)
    atomic_json(candidate/'snapshot.json',manifest)
    atomic_json(candidate/'snapshot_complete.json',dict(manifest_sha256=sha(candidate/'snapshot.json')))
    print('Snapshot complete: '+manifest['input_fingerprint'],flush=True)


def run(candidate, attempt_name, stage):
    candidate=Path(candidate).resolve()
    if not candidate.is_relative_to(ROOT/'data/programme/candidates'):
        raise ValueError('Invalid candidate root')
    manifest=json.loads((candidate/'snapshot.json').read_text())
    if sha(candidate/'snapshot.json')!=json.loads((candidate/'snapshot_complete.json').read_text())['manifest_sha256']:
        raise ValueError('Snapshot manifest changed')
    frozen=candidate/'frozen'
    print('Verify frozen snapshot before execution',flush=True)
    verify_files(frozen,manifest['artifacts'])
    attempt=safe_relative(candidate/'attempts',attempt_name)
    if attempt.exists():raise ValueError('Attempt already exists; verify or choose another')
    attempt.mkdir(parents=True)
    workspace=attempt/'workspace'
    shutil.copytree(frozen,workspace)
    env=os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',OMP_NUM_THREADS='2',
               OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',NUMEXPR_NUM_THREADS='2',
               TEMP=str(attempt/'temp'),TMP=str(attempt/'temp'))
    (attempt/'temp').mkdir()
    command=[sys.executable,'-m','scripts.programme_closeout.worker','--attempt',str(attempt),
             '--stage',stage,'--input-fingerprint',manifest['input_fingerprint']]
    started=time.monotonic()
    with (attempt/'process.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(command,cwd=workspace,env=env,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atomic_json(attempt/'process.json',dict(pid=proc.pid,command=command,started_utc=now(),
                                               timeout_seconds=None,stage=stage))
        try:
            last=0;peak=0
            while proc.poll() is None:
                elapsed=time.monotonic()-started
                memory=process_private_bytes(proc)
                peak=max(peak,memory or 0)
                if elapsed-last>=30:
                    last=elapsed
                    atomic_json(attempt/'resources.json',dict(elapsed_seconds=elapsed,private_bytes=memory,
                                peak_private_bytes=peak,private_byte_limit=None))
                    print(f'{stage}: running {elapsed:.0f}s, pid {proc.pid}; private {(memory or 0)/1024**3:.2f} GiB',flush=True)
                time.sleep(1)
        finally:
            if proc.poll() is None:
                proc.kill();proc.wait()
    atomic_json(attempt/'process_result.json',dict(exit_code=proc.returncode,elapsed_seconds=time.monotonic()-started))
    print(f'{stage}: exit {proc.returncode}; elapsed {time.monotonic()-started:.1f}s',flush=True)
    if proc.returncode:
        print((attempt/'process.log').read_text(encoding='utf-8',errors='replace')[-5000:],flush=True)
        raise RuntimeError('Candidate execution failed; failed artifacts retained')
    read_bundle(attempt/'bundle',manifest['input_fingerprint'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['snapshot','run','verify'])
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--attempt',default='unified-01')
    p.add_argument('--stage',choices=['unified'],default='unified')
    a=p.parse_args()
    if a.action=='snapshot':snapshot(a.candidate)
    elif a.action=='run':run(a.candidate,a.attempt,a.stage)
    else:
        manifest=json.loads((a.candidate/'snapshot.json').read_text())
        print(json.dumps(read_bundle(a.candidate/'attempts'/a.attempt/'bundle',manifest['input_fingerprint']),indent=2))


if __name__=='__main__':main()
