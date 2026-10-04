"""Read-only three-case probe of the active Crescent issuer regex; no corrections."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    import duckdb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    source_review = run / 'missing_identity_source_review_45.json'
    reviews = read(source_review)
    if len(reviews) != 3 or {r['output_position']['cik'] for r in reviews} != {'0001954360'}:
        raise ValueError('Only the three existing Crescent cases are allowed')
    module = repo / 'pipeline/bdc_identifier.py'
    wrapper = repo / 'data/overrides/bdc_xbrl_wrappers/0001954360.json'
    tree = ast.parse(module.read_text(encoding='utf-8-sig'))
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == '_CRESCENT_HIERARCHY_INDUSTRIES' for t in n.targets)]
    if len(assignments) != 1:
        raise ValueError('Expected one literal industry list')
    labels = ast.literal_eval(assignments[0].value)
    industry_re = '|'.join(re.escape(label).replace(r'\ ', r'\s+') for label in sorted(labels, key=len, reverse=True))
    config = read(wrapper)['staging']
    pattern = config['hierarchy_issuer_re'].replace('(?:CRESCENT_INDUSTRY_LABELS)', '(?:' + industry_re + ')')
    condition = config['hierarchy_condition_extra']
    replacements = [('Health Care Equipment and Services', 'Health Care Equipment & Services'),
                    ('Financial Service', 'Financial Services')]
    db = duckdb.connect(config={'threads': '2', 'memory_limit': '1GB'})
    records = []
    for review in reviews:
        output = review['output_position']
        identifier = output['bdc_investment_identifier']
        altered = identifier
        applied = []
        for before, after in replacements:
            if before in identifier:
                altered = altered.replace(before, after)
                applied.append({'observed_label': before, 'configured_label': after})
        if len(applied) != 1:
            raise ValueError('Expected exactly one label-variant probe')
        probes = []
        for kind, value in [('original', identifier), ('label_variant_only', altered)]:
            clean = re.sub(r'\s+', ' ', value.replace('\u00a0', ' ')).replace('Investment Type', ' Investment Type').replace('Security Type', ' Security Type')
            matched, issuer = db.execute('WITH input AS (SELECT ? AS _clean) SELECT (' + condition
                + '), trim(regexp_extract(_clean, ?, 1)) FROM input', [clean, pattern]).fetchone()
            probes.append({'kind': kind, 'wrapper_branch_condition': matched, 'extracted_issuer': issuer})
        if probes[0]['extracted_issuer'] or not probes[0]['wrapper_branch_condition'] or not probes[1]['extracted_issuer']:
            raise ValueError('Proposed mechanism did not reproduce')
        if len(review['source_positions']) != 1:
            raise ValueError('Expected one exact-context source row')
        position = review['source_positions'][0]
        if not position['visible_row'].startswith(probes[1]['extracted_issuer'] + ' '):
            raise ValueError('Counterfactual issuer does not match visible source prefix')
        records.append({'row_id': review['row_id'], 'period': output['report_date'],
            'published_issuer': output['issuer_name'], 'probes': probes, 'label_variant': applied[0],
            'source_sha256': review['source_sha256'], 'source_table': position['table_index'],
            'source_row': position['row_index'], 'visible_row': position['visible_row'],
            'published_cost': output['cost'], 'cost_fact': position['monetary_fact']})
    issues = repo / 'data/output/row_validation_issues.csv'
    issue_hash = sha(issues)
    result = db.execute('''SELECT row_id, rule_id, severity, action, "column", value
        FROM read_csv_auto(?, all_varchar=true)
        WHERE row_id IN (SELECT UNNEST(?)) AND dataset='private_markets_holdings' AND source='bdc'
        ORDER BY row_id, rule_id LIMIT 101''', [str(issues), [r['row_id'] for r in records]])
    names = [c[0] for c in result.description]
    flags = [dict(zip(names, row)) for row in result.fetchall()]
    if len(flags) > 100 or sha(issues) != issue_hash:
        raise ValueError('Issue result exceeds cap or source changed')
    db.close()
    report = {'cases': records, 'existing_flags': flags, 'review_sha256': sha(source_review),
        'wrapper_sha256': sha(wrapper), 'identifier_module_sha256': sha(module),
        'staging_module_sha256': sha(repo / 'pipeline/staging_bdc.py'), 'issues_sha256': issue_hash,
        'production_corrections': 0, 'api_calls': 0,
        'limitation': 'Reproduces the wrapper issuer-regex branch, not a complete historical pipeline replay. Counterfactuals are diagnostic, not promoted fixes or independent audits.'}
    destination = run / ('missing_issuer_mechanism_' + fingerprint(report)[:16] + '.json')
    write(destination, report)
    print(json.dumps({'artifact': destination.name, 'cases': len(records),
        'original_empty_issuer': 3, 'label_variant_source_name_matches': 3, 'existing_flags': flags}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(90, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
