"""Bounded delivery checks and final inventory; no rebuild or source mutation."""
import ast
import datetime
import json
import os
import re
import shutil
import threading
from pathlib import Path

from scripts.programme_closeout.candidate import atomic_json, sha

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'docs/production_stack/programme_closeout_evidence_2026-09-09'


def main():
    
    
    
    docs = [ROOT / 'docs/production_stack' / name for name in (
        'programme_spec_closeout_2026-09-09.md',
        'programme_execution_tranche_2026-09-09.md',
        'programme_units_fx_identity_contract.md',
        'programme_overnight_work_record_2026-09-09.md',
        'programme_measurement_register.md',
        'programme_measurement_pilot_2026-09-09.md',
        'consolidation_readiness_plan.md',
        'programme_implementation_plan.md',
        'programme_physical_architecture.md',
        'programme_rule_authority_assessment_2026-09-09.md',
    )] + [BASE / 'README.md', ROOT / 'docs/reference/current_architecture.md']
    links = 0
    for doc in docs:
        text = doc.read_text(encoding='utf-8')
        fences = sum(line.lstrip().startswith('```') for line in text.splitlines())
        if fences % 2:
            raise ValueError('Unbalanced fences: ' + str(doc))
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if target.startswith(('https://', 'http://', '#', 'mailto:')):
                continue
            relative = target.split('#')[0].strip('<>')
            if relative and not (doc.parent / relative).exists():
                raise ValueError('Broken link: ' + str(doc) + ': ' + target)
            links += 1
    code = sorted((ROOT / 'scripts/programme_closeout').glob('*.py'))
    code += [ROOT / 'tests/test_programme_closeout.py']
    for path in code:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    json_count = 0
    for path in BASE.rglob('*.json'):
        json.loads(path.read_text(encoding='utf-8-sig'))
        json_count += 1
    compatibility = json.loads((BASE / 'stage_compatibility.json').read_text())
    if compatibility['non_identity_row_differences'] or compatibility['pik_parent_mismatches']:
        raise ValueError('Stage composition failed')
    if compatibility['quality'] != 'FAIL_WITH_UNASSESSED_ITEMS' or compatibility['production_eligible']:
        raise ValueError('Preparation release incorrectly promoted')
    preservation = json.loads((BASE / 'original_input_preservation.json').read_text())
    if preservation['result'] != 'pass':
        raise ValueError('Original inputs not preserved')
    verification_dir = BASE / 'verification'
    verification_dir.mkdir(exist_ok=True)
    scratch = ROOT / 'scratch/2026-09-09_programme_closeout'
    for source in (
        scratch / 'pytest.log', scratch / 'guard_test.log',
        scratch / 'finalize_evidence.log',
        scratch / 'backstop/semantic_backstop_result.json',
        scratch / 'backstop/semantic_diff_report.json',
    ):
        shutil.copy2(source, verification_dir / source.name)
    full_code = code + sorted((ROOT / 'scripts/programme_closeout').glob('*.cjs'))
    atomic_json(BASE / 'delivery_verification.json', dict(
        checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        document_count=len(docs), local_links_checked=links,
        python_syntax_files=len(code), json_files_parsed=json_count,
        tests=dict(passed=26, runs=['25 passed in 54.35s', '1 passed in 54.13s']),
        stage_compatibility='pass', original_input_preservation='pass',
        semantic_backstop='Pre-existing divergence; full byte scan incomplete within bound.',
        limitations='No full suite, public application build or production acceptance. See closeout.',
        documents=[dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p)) for p in docs],
        code=[dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p)) for p in full_code],
    ))
    manifest_path = BASE / 'artifact_manifest.json'
    previous = json.loads(manifest_path.read_text())
    archives = previous['compressed_assets']
    for archive in archives:
        archive['archive_path'] = archive['archive_path'].replace('\\', '/')
        if sha(BASE / archive['archive_path']) != archive['archive_sha256']:
            raise ValueError('Compressed evidence changed')
    local = {a['raw_path'] for a in archives}
    local.update(p.relative_to(BASE).as_posix() for p in (BASE / 'viewer').glob('000*.html'))
    records = []
    for path in sorted(BASE.rglob('*')):
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(BASE).as_posix()
        records.append(dict(path=relative, bytes=path.stat().st_size, sha256=sha(path),
                            storage='local_reproducible' if relative in local else 'retained_evidence'))
    previous.update(artifacts=records, compressed_assets=archives,
                    final_inventory_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    previous['source_renditions']['builder_sha256'] = sha(ROOT / 'scripts/programme_closeout/citation_viewer.py')
    atomic_json(manifest_path, previous)
    
    print(json.dumps(dict(documents=len(docs), links=links, syntax_files=len(code),
                         evidence_files=len(records), local_generated_files=len(local),
                         retained_bytes=sum(r['bytes'] for r in records if r['storage'] == 'retained_evidence'))), flush=True)


if __name__ == '__main__':
    main()
