"""Materialize a verified candidate export into a new isolated frontend checkout."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

from pipeline.programme.artifacts import required
from pipeline.programme.core import ContractError,atomic_json,read_json,read_stage,record,sha
from pipeline.programme.runner import ROOT,candidate_path


def prepare(attempt,output):
    result=read_json(attempt/'result.json')
    read_stage(attempt,result['identity'],required('frontend'))
    exported=read_json(attempt/'bundle/frontend_export.json')
    archive=attempt/'bundle/frontend_data.zip'
    if sha(archive)!=exported['archive_sha256']: raise ContractError('Frontend archive differs from export evidence')
    if output.exists(): raise ContractError('Use a new isolated frontend build directory')
    output.mkdir(parents=True)
    frontend=output/'frontend'
    def ignore(directory,names):
        excluded={'.next','out','node_modules','.git','tsconfig.tsbuildinfo'}
        # A stray shell redirection artifact uses Windows' reserved device name.
        # It is not frontend source and cannot be copied via ordinary Win32 IO.
        # Preserve it in the shared checkout and record its exclusion below.
        if Path(directory).resolve()==(ROOT/'frontend').resolve(): excluded.add('nul')
        if Path(directory).resolve()==(ROOT/'frontend/public').resolve(): excluded.add('data')
        return set(names)&excluded
    shutil.copytree(ROOT/'frontend',frontend,ignore=ignore)
    code=[record(frontend,p.relative_to(frontend).as_posix()) for p in sorted(frontend.rglob('*')) if p.is_file()]
    data=frontend/'public/data';data.mkdir(parents=True)
    records={item['path']:item for item in exported['artifacts']}
    with zipfile.ZipFile(archive) as source:
        names=source.namelist()
        if len(set(names))!=len(names) or set(names)!=set(records): raise ContractError('Archive inventory is not exact')
        for index,name in enumerate(names,1):
            target=(data/name).resolve()
            if not target.is_relative_to(data.resolve()) or '\\' in name: raise ContractError('Unsafe export member')
            if source.getinfo(name).file_size!=records[name]['bytes']: raise ContractError('Export member size differs')
            target.parent.mkdir(parents=True,exist_ok=True)
            with source.open(name) as stream,target.open('wb') as destination: shutil.copyfileobj(stream,destination)
            if sha(target)!=records[name]['sha256']: raise ContractError('Export member content differs')
            if index%500==0: print('Verified frontend files: '+str(index)+'/'+str(len(names)),flush=True)
    # Existing installed dependencies only. No npm install or downloads.
    module_source=ROOT/'frontend/node_modules'
    if not module_source.is_dir(): raise ContractError('Existing frontend dependencies are unavailable')
    # These fixed arguments contain resolved workspace paths, never user-supplied shell code.
    def quote(value): return "'"+str(value).replace("'","''")+"'"
    command='New-Item -ItemType Junction -Path '+quote(frontend/'node_modules')+' -Target '+quote(module_source)+' -ErrorAction Stop | Out-Null'
    subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],check=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    atomic_json(output/'prepared.json',dict(attempt=str(attempt),result_sha256=sha(attempt/'result.json'),
        archive_sha256=sha(archive),release_id=exported['history']['release_id'],code=code,
        files=len(names),dependency_path=str(module_source),adoption='not_adopted',
        excluded_workspace_artifacts=['nul'] if any(p.name=='nul' for p in (ROOT/'frontend').iterdir()) else []))
    print('Prepared isolated frontend: '+str(frontend),flush=True)
    return frontend


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',required=True)
    parser.add_argument('--attempt',default='frontend-01')
    parser.add_argument('--name',required=True)
    args=parser.parse_args()
    if any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.name): raise ContractError('Invalid build name')
    if not args.attempt.startswith('frontend-') or not args.attempt[9:].isdigit(): raise ContractError('Invalid frontend attempt')
    prepare(candidate_path(args.candidate)/'attempts'/args.attempt,
        ROOT/'scratch/2026-09-12_programme_e0/public-builds'/args.name)


if __name__=='__main__': main()
