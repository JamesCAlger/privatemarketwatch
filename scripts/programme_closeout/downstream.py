"""Owned controller for a derivative candidate; no production writes."""
import argparse,json,os,shutil,subprocess,sys,time
from pathlib import Path
from scripts.programme_closeout.candidate import atomic_json,sha,fingerprint,read_bundle,process_private_bytes,verify_files
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);p.add_argument('--attempt',default='identity-01');p.add_argument('--parent',choices=['unified-01','identity-02'],default='unified-01');p.add_argument('--stage',choices=['identity','evidence'],default='identity');a=p.parse_args()
    candidate=a.candidate.resolve();assert candidate.is_relative_to(ROOT/'data/programme/candidates')
    parent=candidate/'attempts'/a.parent/'bundle';snap=json.loads((candidate/'snapshot.json').read_text())
    parent_input=candidate/'attempts'/a.parent/'inputs.json'
    parent_fingerprint=json.loads(parent_input.read_text())['fingerprint'] if parent_input.exists() else snap['input_fingerprint']
    parent_result=read_bundle(parent,parent_fingerprint);verify_files(candidate/'frozen',snap['artifacts'])
    if not a.attempt.startswith(a.stage+'-') or '/' in a.attempt or '\\' in a.attempt:raise ValueError('Invalid attempt name')
    attempt=candidate/'attempts'/a.attempt
    if attempt.exists():raise ValueError('Attempt already exists; never reuse partial outputs')
    attempt.mkdir();workspace=attempt/'workspace';shutil.copytree(candidate/'frozen',workspace);(attempt/'temp').mkdir()
    for entry in parent_result['artifacts']:
        name=entry['path']
        if Path(name).suffix in ('.csv','.parquet'):shutil.copy2(parent/name,workspace/'data/output'/name)
    worker=Path(__file__).with_name(a.stage+'_worker.py');dst=workspace/'scripts/programme_closeout'/worker.name;shutil.copy2(worker,dst)
    manifest=dict(parent_result_sha256=sha(parent/'result.json'),parent_holdings_sha256=sha(parent/'private_markets_holdings.csv'),
       frozen_fingerprint=snap['input_fingerprint'],worker_sha256=sha(dst),controller_sha256=sha(Path(__file__)),
       runtime='Trusted copied code; Python mutation/network guard and source/result hash verification. Not an OS security sandbox.')
    manifest['fingerprint']=fingerprint(manifest);atomic_json(attempt/'inputs.json',manifest)
    command=[sys.executable,'-m','scripts.programme_closeout.'+a.stage+'_worker','--attempt',str(attempt)]
    env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',TEMP=str(attempt/'temp'),TMP=str(attempt/'temp'))
    started=time.monotonic();peak=0;last=0
    with (attempt/'process.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(command,cwd=workspace,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atomic_json(attempt/'process.json',dict(pid=proc.pid,command=command,timeout_seconds=None))
        try:
            while proc.poll() is None:
                elapsed=time.monotonic()-started;memory=process_private_bytes(proc) or 0;peak=max(peak,memory)
                if elapsed-last>=30:
                    last=elapsed;atomic_json(attempt/'resources.json',dict(seconds=elapsed,private_bytes=memory,peak_private_bytes=peak));print(f'Identity running {elapsed:.0f}s, pid {proc.pid}',flush=True)
                time.sleep(1)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
    atomic_json(attempt/'process_result.json',dict(exit_code=proc.returncode,seconds=time.monotonic()-started,peak_private_bytes=peak))
    if proc.returncode:print((attempt/'process.log').read_text(errors='replace')[-3500:]);raise RuntimeError('Identity candidate failed; attempt retained')
    read_bundle(attempt/'bundle',manifest['fingerprint']);print('Identity stage complete',flush=True)
if __name__=='__main__':main()
