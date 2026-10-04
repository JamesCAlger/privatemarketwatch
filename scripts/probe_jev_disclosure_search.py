"""Compare source-table navigation in two already investigated cached filings."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import parse_source, parser_runtime
from pipeline.jev_disclosure_search import anchor_issuer_seeds, disclosure_search
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    summary, packets = load_replay(run, args.replay)
    runtime = parser_runtime()
    if summary.get('parser_runtime') != runtime:
        raise ValueError('Current dependency-bound replay required')
    ab_ids = {'ROW-54bec5b9be81ee4d', 'ROW-96818d4e9b1777d0',
              'ROW-1e319095e85a0c34', 'ROW-24cf5e7b72e10c93'}
    ab = [p for p in packets.values() if p['flag']['row_id'] in ab_ids]
    if len(ab) != 4:
        raise ValueError('Expected four existing AB Centers flags')
    if len({(p['output_position']['cik'], p['output_position']['accession_number']) for p in ab}) != 1:
        raise ValueError('AB Centers packets do not share a filing')
    ab_filing = next(p['filing'] for p in ab if p.get('filing', {}).get('path'))
    tcw_path = run / 'exploratory_context_089f24a29d1a0ec6.json'
    tcw = read(tcw_path)
    if tcw['published_position']['row_id'] != 'ROW-ecc8c78a0d433f52':
        raise ValueError('Unexpected exploratory position')
    cases = [
        {'name': 'AB Centers', 'positions': [p['output_position'] for p in ab],
         'source': Path(ab_filing['path']), 'source_sha256': ab_filing['sha256'],
         'source_review_phrase': 'AB Centers', 'within_frozen_67': True,
         'bindings': [fingerprint(p) for p in ab],
         'original_candidates': sorted({(c['table_index'], c['row_index']) for p in ab for c in p['source_candidates']})},
        {'name': 'Superior Industries', 'positions': [tcw['published_position']],
         'source': repo / tcw['source_relative_path'], 'source_sha256': tcw['source_sha256'],
         'source_review_phrase': 'Superior Industries', 'within_frozen_67': False,
         'bindings': [sha(tcw_path)], 'original_candidates': []},
    ]
    reports = []
    for case in cases:
        source = case.pop('source').resolve()
        if not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Source outside bounded cache')
        if sha(source) != case['source_sha256']:
            raise ValueError('Source changed')
        print('Disclosure navigation: ' + case['name'], flush=True)
        parsed = parse_source(source.read_bytes())
        anchors = sorted({p['src_context_id'] for p in case['positions']})
        raw_phrases = sorted({p['issuer_name'] for p in case['positions']})
        raw = disclosure_search(parsed, issuer_phrases=raw_phrases, context_ids=anchors)
        reviewed = disclosure_search(parsed, issuer_phrases=[case['source_review_phrase']], context_ids=anchors)
        seed_result = anchor_issuer_seeds(disclosure_search(parsed, issuer_phrases=[], context_ids=anchors))
        derived = (disclosure_search(parsed, issuer_phrases=[s['phrase'] for s in seed_result['seeds']], context_ids=anchors)
                   if seed_result['seeds'] else None)
        if sha(source) != case['source_sha256']:
            raise ValueError('Source changed during navigation')
        reports.append({**case, 'source_relative_path': str(source.relative_to(repo)),
                        'published_name_search': raw, 'reviewed_phrase_search': reviewed,
                        'source_issuer_seeds': seed_result, 'source_issuer_search': derived,
                        'phrase_basis': 'Manually identified in earlier source investigations; not blind or automatically inferred.'})
    if parser_runtime() != runtime:
        raise ValueError('Parser dependencies changed')
    report = {'replay': args.replay, 'parser_runtime': runtime,
              'search_sha256': sha(ROOT / 'pipeline/jev_disclosure_search.py'),
              'role_sha256': sha(ROOT / 'pipeline/jev_disclosure_role.py'),
              'records': reports, 'source_files': 2, 'frozen_experiment_cases': 67,
              'api_calls': 0, 'production_changes': 0, 'independent_reviews': 0,
              'limitation': 'Navigation development on two already inspected sources. Four existing flags plus one separate exploratory position; not new model cases, recall measurement, sibling identity or clearance.'}
    path = run / ('disclosure_search_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'cases': [{
        'name': r['name'], 'published_phrase_matches': len(r['published_name_search']['matches']),
        'reviewed_phrase_matches': len(r['reviewed_phrase_search']['matches']),
        'source_issuer_seed_count': len(r['source_issuer_seeds']['seeds']),
        'source_issuer_matches': len(r['source_issuer_search']['matches']) if r['source_issuer_search'] else None,
        'reviewed_match_roles': dict(Counter(m['header_role']['role'] for m in r['reviewed_phrase_search']['matches'])),
        'missing_anchors': r['reviewed_phrase_search']['missing_context_anchors']}
        for r in reports]}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(150, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
