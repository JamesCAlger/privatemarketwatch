"""Tiny child-process probe for the preparation adapter's Python audit boundary."""
import argparse,json,socket,subprocess,sys
from pathlib import Path
from scripts.programme_closeout.worker import install_audit_guard

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();allowed=a.root.resolve()
    allowed.mkdir(parents=True);outside=allowed.parent/'guard_outside.txt'
    install_audit_guard(allowed)
    result={};(allowed/'inside.txt').write_text('fixture');result['inside_write']=True
    attempts={'outside_write':lambda:outside.write_text('must not happen'),
              'network_connect':lambda:socket.socket().connect(('127.0.0.1',9)),
              'child_process':lambda:subprocess.run([sys.executable,'--version'],check=True)}
    for name,action in attempts.items():
        try:action();result[name]='NOT_BLOCKED'
        except PermissionError:result[name]='blocked'
    assert not outside.exists()
    assert all(result[k]=='blocked' for k in attempts)
    print(json.dumps(result),flush=True)
if __name__=='__main__':main()
