"""Check the final review document, immutable evidence and original owner comments."""
import argparse
import ast
from pathlib import Path
import re

from pipeline.programme.core import ContractError, atomic_json, read_json, record, sha, verify_records

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/production_stack'
EVIDENCE = DOCS / 'programme_tranche_evidence_2026-09-10'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff', default='handoff-integrated-v1')
    parser.add_argument('--evaluation', default='evaluation-v1')
    parser.add_argument('--browser', default='browser-review-integrated-v1')
    parser.add_argument('--record-incomplete-verification', action='store_true')
    args = parser.parse_args()
    for value in vars(args).values():
        if isinstance(value, bool):
            continue
        if not value or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in value):
            raise ContractError('Use portable artifact names')
    documents = [DOCS / name for name in ('programme_runner.md', 'programme_tranche_handoff_2026-09-10.md',
        'programme_tranche_resume_proposal_2026-09-10.md', 'programme_tranche_2026-09-10_work_record.md')]
    links = 0
    for document in documents:
        for target in re.findall(r'\]\(([^)]+)\)', document.read_text(encoding='utf-8')):
            if target.startswith(('http://', 'https://', '#')):
                continue
            if not (document.parent / target.split('#')[0]).exists():
                raise ContractError('Broken local document link: ' + target)
            links += 1
    code = [*sorted((ROOT / 'pipeline/programme').glob('*.py')),
            *sorted((ROOT / 'scripts/programme_tranche').glob('*.py')),
            *(ROOT / 'tests' / name for name in ('test_programme_runtime.py', 'test_programme_runtime_metadata.py',
                                               'test_programme_measurement.py', 'test_programme_tranche.py'))]
    for path in code:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    handoff = EVIDENCE / args.handoff
    verify_records(handoff, read_json(handoff / 'complete.json')['artifacts'], exact=True, ignored_prefixes=('complete.json',))
    summary = read_json(handoff / 'verification.json')
    engineering_complete = summary['engineering_tranche_complete']
    if summary['production_adoption'] or (not engineering_complete and not args.record_incomplete_verification):
        raise ContractError('Handoff has the wrong end-state')
    if not engineering_complete and summary['execution_status'] != 'verification_incomplete':
        raise ContractError('Incomplete engineering verification must be explicit')
    evaluation = EVIDENCE / args.evaluation
    verify_records(evaluation, read_json(evaluation / 'evaluation_manifest.json')['files'], exact=True,
                   ignored_prefixes=('evaluation_manifest.json',))
    results = read_json(evaluation / 'criterion_results.json')['criteria']
    if len(results) != 28 or sum(len(item['results']) for item in results) != 50:
        raise ContractError('Acceptance inventory is incomplete')
    browser_path = ROOT / 'scratch/2026-09-10_programme_tranche' / args.browser / 'checks.json'
    browser = read_json(browser_path)
    if browser['status'] != 'pass' or sha(DOCS / 'programme_tranche_review.html') != browser['input_sha256']:
        raise ContractError('Browser proof belongs to another document')
    if sha(DOCS / 'programme_review_comments.md') != '9a431d8d5b0aa8870ca031a0498665df2dc071107f0696fd85a3e8ea5ea6b267':
        raise ContractError('Original owner comments changed')
    atomic_json(EVIDENCE / 'integrated_delivery_verification.json', dict(status='engineering_review_ready' if engineering_complete else
        'candidate_verified_verification_incomplete',
        engineering_end_state_complete=engineering_complete, documents=len(documents), local_document_links=links,
        python_syntax_files=len(code), browser=browser, criteria=28, metrics=50,
        product_verdict=summary['product_acceptance']['verdict'], original_owner_comments_unchanged=True,
        files=[record(ROOT, path.relative_to(ROOT).as_posix()) for path in
            [*documents, *code, DOCS / 'programme_tranche_review.html', browser_path,
             handoff / 'complete.json', evaluation / 'evaluation_manifest.json']],
        scope=('Engineering tranche ready for owner review; financial acceptance and independent source review remain separate'
               if engineering_complete else
               'Verified candidate and honest incomplete-verification handoff; engineering end-state is not complete')))
    print('Delivery records verified; engineering complete=' + str(engineering_complete), flush=True)


if __name__ == '__main__':
    main()
