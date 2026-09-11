"""Guarded legacy-pipeline worker, only executable inside a copied candidate."""
from __future__ import annotations
import argparse
import json
import logging
import os
from pathlib import Path
import re
import socket
import sys
import time
from unittest.mock import patch
from contextlib import ExitStack

sys.dont_write_bytecode=True
from scripts.programme_closeout.candidate import atomic_json, commit_bundle, fingerprint, now


def install_audit_guard(attempt):
    """Block Python filesystem mutation outside the candidate attempt and all network/process starts."""
    allowed=Path(attempt).resolve()
    def check(path):
        if isinstance(path,(str,bytes,os.PathLike)):
            p=Path(os.fsdecode(path)).resolve()
            if not p.is_relative_to(allowed):
                raise PermissionError('Candidate write outside attempt: '+str(p))
    def hook(event,args):
        if event=='open':
            path,mode,flags=args
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
                check(path)
        elif event in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.truncate','os.utime'):
            check(args[0])
        elif event in ('os.rename','os.link','os.symlink'):
            check(args[0]);check(args[1])
        elif event in ('socket.connect','socket.bind','subprocess.Popen','os.system','os.exec'):
            raise PermissionError('Candidate external operation disabled: '+event)
    sys.addaudithook(hook)
    return check


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--attempt',type=Path,required=True)
    p.add_argument('--stage',choices=['unified'],required=True)
    p.add_argument('--input-fingerprint',required=True)
    a=p.parse_args()
    attempt=a.attempt.resolve();workspace=Path(__file__).resolve().parents[2]
    if workspace!=attempt/'workspace' or 'data/programme/candidates' not in attempt.as_posix():
        raise RuntimeError('Worker must run from its copied candidate source')
    check=install_audit_guard(attempt)
    bundle=attempt/'bundle';bundle.mkdir()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    import duckdb
    import pandas as pd
    original_connect=duckdb.connect
    sql_reads=set()
    class Connection:
        def __init__(self,con):self.con=con
        def validate(self,query):
            query=str(query)
            if re.search(r'(?i)\b(ATTACH|INSTALL|LOAD|EXPORT|IMPORT)\b',query):
                raise PermissionError('Native external IO disabled')
            if re.search(r'(?i)\bCOPY\b',query):
                dest=re.search(r"(?i)\bTO\s+'((?:''|[^'])*)'",query)
                if not dest:raise PermissionError('Unsupported native COPY')
                check(dest.group(1).replace("''","'"))
            for match in re.finditer(r"(?i)read_(?:csv(?:_auto)?|parquet)\(\s*'((?:''|[^'])*)'",query):
                path=Path(match.group(1).replace("''","'")).resolve()
                if not path.is_relative_to(workspace):
                    raise PermissionError('Unpinned native input: '+str(path))
                sql_reads.add(path.relative_to(workspace).as_posix())
        def execute(self,q,*args,**kw):
            self.validate(q)
            start=time.monotonic()
            if len(str(q))>10000:
                logging.info('Native query start: %s chars; %s',len(str(q)),str(q).strip()[:90])
            self.con.execute(q,*args,**kw)
            if len(str(q))>10000:logging.info('Native query completed in %.1f s',time.monotonic()-start)
            return self
        def sql(self,q,*args,**kw):
            self.validate(q);return self.con.sql(q,*args,**kw)
        def __getattr__(self,name):
            if name in ('write_csv','write_parquet','to_csv','to_parquet','export','cursor'):
                raise PermissionError('Unwrapped native operation '+name)
            return getattr(self.con,name)
    def connect(*args,**kw):
        if args and str(args[0]) not in ('',':memory:'):check(args[0])
        if 'database' in kw and str(kw['database']) not in ('',':memory:'):check(kw['database'])
        con=original_connect(*args,**kw)
        con.execute("SET threads=4")
        con.execute("SET memory_limit='6GB'")
        con.execute("SET temp_directory='"+(attempt/'temp').as_posix().replace("'","''")+"'")
        return Connection(con)
    rule_events=[]
    with patch.object(duckdb,'connect',connect):
        from pipeline import config,utils,agent_b2_appliers,agent_promoted,unified_holdings
        if config.PROJECT_ROOT.resolve()!=workspace:
            raise RuntimeError('Pipeline root escaped copied source')
        original_companion=utils.write_parquet_companion
        def strict_companion(path,strict=None):
            return original_companion(path,strict=True)
        original_scoped=agent_b2_appliers.apply_scoped
        def scoped(frame,leaf):
            rule_id=fingerprint(leaf)
            before_rows=len(frame)
            before_fv=pd.to_numeric(frame.get('fair_value'),errors='coerce').sum() if 'fair_value' in frame else None
            started=time.monotonic()
            output,audit=original_scoped(frame,leaf)
            event=dict(rule_id=rule_id,cik=leaf.get('cik'),fix_class=leaf.get('fix_class'),
                scope=leaf.get('scope'),template=leaf.get('template'),input_rows=before_rows,
                output_rows=len(output),input_signed_fv=before_fv,
                output_signed_fv=pd.to_numeric(output.get('fair_value'),errors='coerce').sum() if 'fair_value' in output else None,
                elapsed_seconds=time.monotonic()-started,audit=audit)
            rule_events.append(event)
            atomic_json(bundle/'rule_events.json',rule_events)
            return output,audit
        original_apply=agent_promoted.apply_promoted_stage2_corrections
        def promoted(frame,leaves):
            # Preserve full pre-B2 frame for deterministic order/selector replay.
            path=bundle/'before_b2.csv'
            frame.to_csv(path,index=False)
            result,audits=original_apply(frame,leaves)
            result.to_csv(bundle/'after_b2.csv',index=False)
            return result,audits
        with ExitStack() as stack:
            stack.enter_context(patch.object(utils,'write_parquet_companion',strict_companion))
            stack.enter_context(patch.object(agent_b2_appliers,'apply_scoped',scoped))
            stack.enter_context(patch.object(agent_promoted,'apply_promoted_stage2_corrections',promoted))
            print('Execute cached unified build from frozen workspace',flush=True)
            data=unified_holdings.build_unified_holdings()
            # The legacy empty path bypasses its companion writer. The adapter
            # explicitly finalizes the required typed pair even when empty.
            strict_companion(config.UNIFIED_HOLDINGS_FILE)
            final_audits=config.OUTPUT_DIR/'agent_fix_application_audit.csv'
            errors=[e for e in rule_events if e['audit'].get('status') not in ('ok','no_rows')]
            atomic_json(bundle/'stage_summary.json',dict(stage=a.stage,rows=len(data),
                        b2_applications=len(rule_events),b2_execution_errors=len(errors),
                        legacy_application_audit_present=final_audits.exists(),
                        input_fingerprint=a.input_fingerprint,completed_utc=now()))
            atomic_json(bundle/'native_read_paths.json',sorted(sql_reads))
            # Archive final data separately from the mutable attempt workspace.
            import shutil
            for name in ('private_markets_holdings.csv','private_markets_holdings.parquet','agent_fix_application_audit.csv'):
                path=config.OUTPUT_DIR/name
                if path.exists():shutil.copy2(path,bundle/name)
            if errors:
                atomic_json(bundle/'execution_failure.json',dict(reason='admitted_rule_execution_error',rules=errors))
                raise RuntimeError('Correction execution errors block stage completion')
            artifacts=[p.name for p in bundle.iterdir() if p.is_file()]
            commit_bundle(bundle,artifacts,a.input_fingerprint,'not_evaluated',
                dict(role='isolated diagnostic; financial acceptance not evaluated',rows=len(data)))
    print('Candidate bundle committed',flush=True)


if __name__=='__main__':main()
