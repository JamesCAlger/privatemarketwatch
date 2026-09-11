"""Rebuild legacy identity outputs against exactly one isolated holdings parent."""
import argparse,json,logging,sys,time,shutil
from pathlib import Path
sys.dont_write_bytecode=True
from scripts.programme_closeout.worker import install_audit_guard
from scripts.programme_closeout.candidate import atomic_json,commit_bundle,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--attempt',type=Path,required=True);a=p.parse_args();attempt=a.attempt.resolve()
    workspace=Path(__file__).resolve().parents[2]
    if workspace!=attempt/'workspace':raise ValueError('Worker must execute in isolated workspace')
    manifest=json.loads((attempt/'inputs.json').read_text())
    install_audit_guard(attempt)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    import duckdb,pandas as pd
    from unittest.mock import patch
    original_connect=duckdb.connect
    def connect(*args,**kwargs):
        con=original_connect(*args,**kwargs);con.execute('SET threads=2');con.execute("SET memory_limit='4GB'")
        con.execute("SET temp_directory='"+(attempt/'temp').as_posix().replace("'","''")+"'");return con
    from pipeline import config,entity_resolution,position_matching,utils
    if config.PROJECT_ROOT.resolve()!=workspace:raise ValueError('Unpinned pipeline import')
    for attr in ('UNIFIED_HOLDINGS_FILE','POSITION_MATCHES_FILE'):
        if not getattr(config,attr).resolve().is_relative_to(workspace):raise ValueError('Unpinned output '+attr)
    bundle=attempt/'bundle';bundle.mkdir();times={};start=time.monotonic()
    with patch.object(duckdb,'connect',connect):
        entity_resolution.build_entity_lookup(config.UNIFIED_HOLDINGS_FILE,enrich=True)
        times['entity_seconds']=time.monotonic()-start;logging.info('Programme entity stage completed')
        frame=pd.read_csv(config.UNIFIED_HOLDINGS_FILE,dtype=str);t=time.monotonic()
        matches=position_matching.match_positions(frame,contested_assignment=True)
        times['matching_seconds']=time.monotonic()-t;t=time.monotonic()
        frame,matches=position_matching.assign_position_ids(frame,matches,contested_assignment=True,use_registry=False)
        times['position_ids_seconds']=time.monotonic()-t
        frame.to_csv(config.UNIFIED_HOLDINGS_FILE,index=False)
        matches.to_csv(config.POSITION_MATCHES_FILE,index=False)
        for path in (config.UNIFIED_HOLDINGS_FILE,config.POSITION_MATCHES_FILE):utils.write_parquet_companion(path,strict=True)
    for path in (config.UNIFIED_HOLDINGS_FILE,config.POSITION_MATCHES_FILE,
                 entity_resolution.ENTITY_LOOKUP_FILE,entity_resolution.ENTITY_STATS_FILE,
                 position_matching.POSITION_ID_EDGES_FILE):
        if not path.exists():raise ValueError('Missing identity artifact '+str(path))
        shutil.copy2(path,bundle/path.name)
        if path.with_suffix('.parquet').exists():shutil.copy2(path.with_suffix('.parquet'),bundle/path.with_suffix('.parquet').name)
    atomic_json(bundle/'summary.json',dict(rows=len(frame),matches=len(matches),times=times,
        parent_holdings_sha256=manifest['parent_holdings_sha256'],total_seconds=time.monotonic()-start,
        role='Synchronized legacy matching/entity candidate; persistent-ID migration and independent identity accuracy separate.',
        flags=dict(contested_assignment=True,use_registry=False),financial_semantics='Unchanged cash-leg legacy rates; no return formula migration.'))
    commit_bundle(bundle,[f.name for f in bundle.iterdir() if f.is_file()],manifest['fingerprint'],'not_evaluated')
    print('Identity candidate bundle committed',flush=True)
if __name__=='__main__':main()
