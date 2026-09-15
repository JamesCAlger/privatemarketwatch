"""Bounded post-failure inspection; never retrospectively certifies dependencies."""
from __future__ import annotations

import os
from pathlib import Path
import threading
import time

from pipeline.programme.core import ContractError, atomic_json, read_json, record, sha

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / 'data/programme/candidates/t1-runtime-20260910-v3'
ATTEMPT = CANDIDATE / 'attempts/unified-01'
OUTPUT = ROOT / 'docs/production_stack/programme_tranche_evidence_2026-09-10/runtime-failure-v1'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=False)
    
    started=time.monotonic()
    runtime=read_json(CANDIDATE/'runtime.json')
    ledger=read_json(ATTEMPT/'bundle/read_ledger.json')
    if len(ledger['python_paths'])>10000:
        raise ContractError('Diagnostic read ledger exceeds 10000 paths')
    declared={item['path']:item for item in runtime['content']}
    folded={path.casefold():item for path,item in declared.items()}
    roots=[Path(root).resolve() for root in runtime['content_roots']]
    omissions=[]; changes=[]; checked=0
    for value in ledger['python_paths']:
        path=Path(value).resolve()
        if path.is_relative_to(ATTEMPT.resolve()) or not path.is_file():
            continue
        if not any(path.is_relative_to(root) for root in roots):
            raise ContractError('Diagnostic found an undeclared external root')
        observed=dict(path=path.as_posix(),bytes=path.stat().st_size,sha256=sha(path))
        checked+=1
        prior=declared.get(observed['path'])
        if prior is None:
            omissions.append(dict(observed, case_alias_only=observed['path'].casefold() in folded,
                evidence_timing='post_execution_only; cannot certify prior state'))
        elif prior != observed:
            changes.append(dict(expected=prior,observed_after_execution=observed))
    if (ATTEMPT/'complete.json').exists() or (ATTEMPT/'result.json').exists():
        raise ContractError('Failed stage unexpectedly has a completion result')
    process=read_json(ATTEMPT/'process_result.json')
    if process['exit_code'] != 0 or not process['worker_stopped']:
        raise ContractError('Worker termination evidence changed')
    summary=read_json(ATTEMPT/'bundle/summary.json')
    report=dict(status='blocked_missing_preexecution_runtime_identity',candidate=CANDIDATE.name,
        external_python_reads_checked=checked, runtime_manifest_files=len(declared),
        missing_runtime_records=omissions,changed_declared_records=changes,
        worker_exit_code=process['exit_code'],worker_stopped=process['worker_stopped'],
        worker_elapsed_seconds=process['elapsed_seconds'],worker_summary=summary,
        stage_sealed=False,downstream_stages_started=False,
        diagnostic_elapsed_seconds=time.monotonic()-started,
        meaning='The build worker finished, but complete dependency identity was not established. Retained output is an unsealed development artifact and cannot feed supported descendants.',
        code=record(ROOT,Path(__file__).relative_to(ROOT).as_posix()),
        inputs=[record(ROOT,path.relative_to(ROOT).as_posix()) for path in
            (CANDIDATE/'runtime.json',ATTEMPT/'bundle/read_ledger.json',ATTEMPT/'process_result.json')])
    atomic_json(OUTPUT/'result.json',report)
    
    print('Runtime closure: '+str(checked)+' external paths; '+str(len(omissions))+
        ' omitted; '+str(len(changes))+' changed declared paths. Result remains unsealed.',flush=True)


if __name__=='__main__':
    main()
