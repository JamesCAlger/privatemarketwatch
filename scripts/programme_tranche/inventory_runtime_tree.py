"""Bounded file-count/size assessment before complete runtime content hashing."""
from collections import defaultdict
import os
from pathlib import Path
import site
import sys
import threading
import time

from pipeline.programme.core import atomic_json


def main():
    timer=threading.Timer(180,lambda:os._exit(124));timer.daemon=True;timer.start()
    start=time.monotonic(); groups=defaultdict(lambda:dict(files=0,bytes=0));aliases=[]
    roots=[Path(sys.executable).resolve().parent,Path(site.getusersitepackages()).resolve()]
    for index,root in enumerate(roots):
        for directory,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[name for name in dirs if name!='__pycache__']
            for name in dirs:
                path=Path(directory)/name
                if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:
                    aliases.append(str(path))
            for name in files:
                path=Path(directory)/name;info=path.stat()
                group=str(index)+'/'+path.relative_to(root).parts[0]
                groups[group]['files']+=1;groups[group]['bytes']+=info.st_size
    output=Path(__file__).resolve().parents[2]/'data/programme/tranches/t1-20260910/runtime_tree_assessment.json'
    result=dict(roots=[str(root) for root in roots],groups=dict(groups),directory_aliases=aliases,
        files=sum(g['files'] for g in groups.values()),bytes=sum(g['bytes'] for g in groups.values()),
        excluded='__pycache__; worker redirects bytecode lookup/writes to a fresh local directory',
        elapsed_seconds=time.monotonic()-start)
    atomic_json(output,result);timer.cancel()
    print('Complete runtime tree: '+str(result['files'])+' files; '+str(round(result['bytes']/1024**3,2))+
        ' GiB; '+str(len(aliases))+' directory aliases',flush=True)


if __name__=='__main__':main()
