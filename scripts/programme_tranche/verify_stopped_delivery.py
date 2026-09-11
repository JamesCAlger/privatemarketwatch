"""Bounded syntax/link/hash checks for the stopped, non-accepting handoff."""
import ast
from pathlib import Path
import re

from pipeline.programme.core import ContractError, atomic_json, read_json, record, sha, verify_records

ROOT=Path(__file__).resolve().parents[2]
DOCS=ROOT/'docs/production_stack'
EVIDENCE=DOCS/'programme_tranche_evidence_2026-09-10'


def main():
    documents=[DOCS/name for name in ('programme_runner.md','programme_tranche_handoff_2026-09-10.md',
        'programme_tranche_resume_proposal_2026-09-10.md','programme_tranche_2026-09-10_work_record.md')]
    links=0
    for document in documents:
        contents=document.read_text(encoding='utf-8')
        for target in re.findall(r'\]\(([^)]+)\)',contents):
            if target.startswith(('http://','https://','#')):
                continue
            if not (document.parent/target.split('#')[0]).exists():
                raise ContractError('Broken local document link: '+target)
            links+=1
    code=[*sorted((ROOT/'pipeline/programme').glob('*.py')),
          *sorted((ROOT/'scripts/programme_tranche').glob('*.py')),
          *(ROOT/'tests'/name for name in ('test_programme_runtime.py','test_programme_runtime_metadata.py',
                                         'test_programme_measurement.py','test_programme_tranche.py'))]
    for path in code:
        ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
    handoff=EVIDENCE/'handoff-stopped-v1'
    verify_records(handoff,read_json(handoff/'complete.json')['artifacts'],exact=True,ignored_prefixes=('complete.json',))
    evaluation=EVIDENCE/'evaluation-stopped-v1'
    verify_records(evaluation,read_json(evaluation/'evaluation_manifest.json')['files'],exact=True,
                   ignored_prefixes=('evaluation_manifest.json',))
    results=read_json(evaluation/'criterion_results.json')['criteria']
    if len(results)!=28 or sum(len(item['results']) for item in results)!=50 or any(
        metric['status']!='UNMEASURED' for item in results for metric in item['results']):
        raise ContractError('Stopped candidate acquired an accepting metric')
    browser_path=ROOT/'scratch/2026-09-10_programme_tranche/browser-review/checks.json'
    browser=read_json(browser_path)
    if browser['status']!='pass' or sha(DOCS/'programme_tranche_review.html')!=browser['input_sha256']:
        raise ContractError('Browser proof belongs to another document')
    if sha(DOCS/'programme_review_comments.md')!='9a431d8d5b0aa8870ca031a0498665df2dc071107f0696fd85a3e8ea5ea6b267':
        raise ContractError('Original owner comments changed')
    atomic_json(EVIDENCE/'stopped_delivery_verification.json',dict(status='failure_handoff_verified',
        engineering_end_state_complete=False,documents=len(documents),local_document_links=links,
        python_syntax_files=len(code),browser=browser,metrics=50,criteria=28,unmeasured=50,
        original_owner_comments_unchanged=True,
        files=[record(ROOT,path.relative_to(ROOT).as_posix()) for path in
            [*documents,*code,DOCS/'programme_tranche_review.html',browser_path]],
        test_result=record(ROOT,(handoff/'focused_result.json').relative_to(ROOT).as_posix()),
        note='Verifies this failure handoff; not full-suite, recovery, integrated candidate or release acceptance.'))
    print('Stopped handoff verified: '+str(len(code))+' Python files, '+str(links)+
        ' document links, browser identity and all 50 non-accepting metric results',flush=True)


if __name__=='__main__':
    main()
