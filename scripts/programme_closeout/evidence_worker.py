"""Synchronize PIK evidence consumers with an isolated identity candidate."""
import argparse,json,logging,shutil,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
from scripts.programme_closeout.worker import install_audit_guard
from scripts.programme_closeout.candidate import atomic_json,commit_bundle,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--attempt',type=Path,required=True);a=p.parse_args();attempt=a.attempt.resolve()
    workspace=Path(__file__).resolve().parents[2]
    if workspace!=attempt/'workspace':raise ValueError('Worker must execute in isolated workspace')
    inputs=json.loads((attempt/'inputs.json').read_text());install_audit_guard(attempt)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    from pipeline import config,pik_status
    if config.PROJECT_ROOT.resolve()!=workspace:raise ValueError('Unpinned pipeline root')
    if not config.BDC_POSITION_PIK_EVIDENCE_FILE.is_file():raise ValueError('Missing pinned PIK evidence')
    start=time.monotonic();status=pik_status.build_position_pik_status()
    # Existing builder returns the status and strict transition frames.
    if isinstance(status,tuple):status,strict_transitions=status
    else:strict_transitions=None
    summary,transitions=pik_status.build_pik_schedule_proxy_outputs(status)
    bundle=attempt/'bundle';bundle.mkdir()
    files=(config.POSITION_PIK_STATUS_FILE,config.PIK_TRANSITIONS_FILE,config.PIK_SCHEDULE_PROXY_SUMMARY_FILE,config.PIK_SCHEDULE_PROXY_TRANSITIONS_FILE)
    for path in files:
        if not path.is_file():raise ValueError('Missing evidence artifact '+str(path))
        shutil.copy2(path,bundle/path.name)
    atomic_json(bundle/'summary.json',dict(rows=len(status),summary_rows=len(summary),terms_transitions=len(transitions),
        strict_status_counts={str(k):int(v) for k,v in status['pik_current_status'].value_counts(dropna=False).items()},
        parent_holdings_sha256=inputs['parent_holdings_sha256'],source_evidence_sha256=sha(config.BDC_POSITION_PIK_EVIDENCE_FILE),
        elapsed_seconds=time.monotonic()-start,role='Synchronized legacy PIK status and terms proxy, using pinned source-evidence cache. Terms transitions are not confirmed distress.'))
    commit_bundle(bundle,[f.name for f in bundle.iterdir() if f.is_file()],inputs['fingerprint'],'not_evaluated')
    print('Evidence candidate bundle committed',flush=True)
if __name__=='__main__':main()
