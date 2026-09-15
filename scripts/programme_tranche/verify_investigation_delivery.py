"""Verify the investigation handoff without rewriting earlier tranche evidence."""
import ast
import os
from pathlib import Path
import re
import shutil
import threading
from urllib.parse import unquote

from pipeline.programme.core import atomic_json, now, read_json, record, sha, verify_records

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT/'docs/production_stack'
EVIDENCE = DOCS/'programme_tranche_evidence_2026-09-10'
SCRATCH = ROOT/'scratch/2026-09-10_verification_investigation'


def main():
    
    investigation = EVIDENCE/'verification-investigation-v1'
    verify_records(investigation, read_json(investigation/'complete.json')['artifacts'],
                   exact=True, ignored_prefixes=('complete.json',))
    result = read_json(investigation/'result.json')
    assert result['repaired_outcomes'] == {'passed': 61, 'failed': 1}
    assert result['preservation']['status'] == 'pass'
    assert not result['preservation']['semantic_changes_since_preparation']
    documents = [DOCS/name for name in (
        'programme_verification_investigation_2026-09-10.md',
        'programme_tranche_handoff_2026-09-10.md',
        'programme_tranche_resume_proposal_2026-09-10.md',
        'programme_runner.md', 'consolidation_readiness_plan.md',
        'programme_implementation_plan.md', 'programme_tranche_2026-09-10_work_record.md')]
    documents.append(ROOT/'docs/reference/current_architecture.md')
    links = 0
    for path in documents:
        content = path.read_text(encoding='utf-8-sig')
        assert len(re.findall(r'^```', content, re.M)) % 2 == 0, path
        for target in re.findall(r'\]\(([^)]+)\)', content):
            if target.startswith(('http://', 'https://', '#', 'mailto:')):
                continue
            assert (path.parent/unquote(target.split('#')[0])).exists(), (path, target)
            links += 1
    code = [*sorted((ROOT/'scripts/programme_tranche').glob('*.py')),
            *(ROOT/'tests'/name for name in ('conftest.py', 'test_agent_data_query.py',
                'test_investigation_orchestration.py', 'test_bdc_xbrl_wrapper.py', 'test_unified_holdings.py'))]
    for path in code:
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    assert sha(DOCS/'programme_review_comments.md') == '9a431d8d5b0aa8870ca031a0498665df2dc071107f0696fd85a3e8ea5ea6b267'
    browser_dir = SCRATCH/'browser-review-v1'
    browser = read_json(browser_dir/'checks.json')
    assert browser['status'] == 'pass'
    assert browser['input_sha256'] == sha(DOCS/'programme_tranche_review.html')
    assert browser['comment_boxes'] == 32 and not browser['network'] and not browser['errors']
    out = EVIDENCE/'verification-investigation-review-v1'
    assert not out.exists(), 'Preserve previous evidence'
    out.mkdir()
    for name in ('checks.json', 'desktop.png', 'mobile.png', 'print-check.pdf'):
        shutil.copyfile(browser_dir/name, out/name)
    shutil.copyfile(SCRATCH/'check_review.cjs', out/'check_review.cjs')
    atomic_json(out/'delivery.json', dict(recorded_utc=now(), status='investigation_complete',
        engineering_end_state_complete=False, production_validator_repair_applied=False,
        documents=len(documents), local_document_links=links, python_syntax_files=len(code),
        original_owner_comments_unchanged=True, browser=browser,
        investigation=record(ROOT, (investigation/'complete.json').relative_to(ROOT).as_posix()),
        files=[record(ROOT, path.relative_to(ROOT).as_posix()) for path in
               [*documents, *code, DOCS/'programme_tranche_review.html']],
        scope='Investigation and bounded test repairs verified. Full suite, production validator correction, financial measurement and recovery remain.'))
    atomic_json(out/'complete.json', dict(recorded_utc=now(), artifacts=[record(out, path.relative_to(out).as_posix())
        for path in sorted(out.rglob('*')) if path.is_file()]))
    print('Investigation evidence, documents, syntax, browser and owner comments verified.', flush=True)
    


if __name__ == '__main__':
    main()
