"""Profile unfiltered table navigation on the same 67 frozen development flags."""
import argparse
from collections import Counter, defaultdict
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
    parser.add_argument('--review-label', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    runtime = parser_runtime()
    summary, packets = load_replay(run, args.replay)
    if len(packets) != 67 or summary.get('parser_runtime') != runtime:
        raise ValueError('Expected current 67-case replay')
    if not args.review_label.replace('_', '').isalnum():
        raise ValueError('Invalid review label')
    directory = run / args.review_label
    manifest = read(directory / 'manifest.json')
    if manifest['replay'] != args.replay or len(manifest['inventory']) != len(packets):
        raise ValueError('Prepared review inventory differs')
    by_fingerprint = {fingerprint(p): p for p in packets.values()}
    seen, sources = set(), defaultdict(list)
    for item in manifest['inventory']:
        path = (directory / item['file']).resolve()
        if path.parent != directory or sha(path) != item['sha256']:
            raise ValueError('Prepared input changed or escaped directory')
        prepared = read(path)
        binding = prepared['snapshot']['bundle_fingerprint']
        if binding not in by_fingerprint or binding in seen:
            raise ValueError('Prepared packet binding differs or repeats')
        seen.add(binding)
        source = prepared['source']
        sources[(source['path'], source['sha256'])].append(by_fingerprint[binding])
    if seen != set(by_fingerprint) or len(sources) != 26:
        raise ValueError('Incomplete frozen source scope')
    records = []
    for index, ((filename, digest), local_packets) in enumerate(sorted(sources.items()), 1):
        source = Path(filename).resolve()
        if not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Source outside bounded cache')
        if sha(source) != digest:
            raise ValueError('Source changed')
        print(f'Disclosure search profile: source {index}/26, {len(local_packets)} flags', flush=True)
        parsed = parse_source(source.read_bytes())
        for packet in local_packets:
            position = packet['output_position']
            name = position.get('issuer_name')
            phrases = [name] if isinstance(name, str) and name.strip() else []
            context = position.get('src_context_id')
            anchors = [context] if isinstance(context, str) and context.strip() else []
            try:
                result = disclosure_search(parsed, issuer_phrases=phrases, context_ids=anchors)
                refusal = None
            except ValueError as exc:
                result, refusal = None, str(exc)
            # Preserve the failed phrase search separately; exact contexts can
            # still supply bounded navigation without relaxing name matching.
            anchor_search = disclosure_search(parsed, issuer_phrases=[], context_ids=anchors) if anchors else None
            seeds = anchor_issuer_seeds(anchor_search) if anchor_search else None
            derived = (disclosure_search(parsed, issuer_phrases=[s['phrase'] for s in seeds['seeds']], context_ids=anchors)
                       if seeds and seeds['seeds'] else None)
            original = {(c['table_index'], c['row_index']) for c in packet['source_candidates']}
            found = {(m['table_index'], m['row_index']) for m in result['matches']} if result else set()
            records.append({'rule': packet['rule']['id'], 'row_id': packet['flag']['row_id'],
                'bundle_fingerprint': fingerprint(packet), 'cik': position['cik'],
                'source_sha256': digest, 'source_relative_path': str(source.relative_to(repo)),
                'issuer_phrase_origin': 'Exact published issuer_name, without manual correction or token dropping.',
                'refusal': refusal, 'search': result,
                'exact_anchor_search': anchor_search, 'source_issuer_seeds': seeds,
                'source_issuer_search': derived,
                'builder_candidate_coordinates': sorted(original),
                'navigation_only_coordinates': sorted(found - original),
                'builder_only_coordinates': sorted(original - found),
                'current_evidence_status': packet['evidence_status']['status']})
        if sha(source) != digest:
            raise ValueError('Source changed during profile')
    if parser_runtime() != runtime:
        raise ValueError('Parser runtime changed')
    successful = [r for r in records if r['search'] is not None]
    counts = {
        'flags': len(records), 'source_files': len(sources), 'refused': len(records) - len(successful),
        'flags_with_no_matches': sum(not r['search']['matches'] for r in successful),
        'flags_with_phrase_matches': sum(any(m['matched_phrases'] for m in r['search']['matches']) for r in successful),
        'flags_with_anchor_matches': sum(any(m['matched_context_anchors'] for m in r['search']['matches']) for r in successful),
        'flags_with_missing_anchor': sum(bool(r['search']['missing_context_anchors']) for r in successful),
        'flags_with_navigation_only_coordinates': sum(bool(r['navigation_only_coordinates']) for r in successful),
        'flags_with_builder_only_coordinates': sum(bool(r['builder_only_coordinates']) for r in successful),
        'refusal_reasons': dict(Counter(r['refusal'] for r in records if r['refusal'])),
        'flags_with_source_issuer_seed': sum(bool(r['source_issuer_search']) for r in records),
        'flags_with_anchor_only_fallback': sum(r['search'] is None and bool(r['exact_anchor_search']) for r in records),
        'flags_with_source_seed_additions': sum(bool(r['source_issuer_search']) and bool(
            {(m['table_index'], m['row_index']) for m in r['source_issuer_search']['matches']} -
            {(m['table_index'], m['row_index']) for m in (r['search'] or {'matches': []})['matches']}) for r in records),
    }
    report = {'replay': args.replay, 'review_manifest_sha256': sha(directory / 'manifest.json'),
              'parser_runtime': runtime, 'search_sha256': sha(ROOT / 'pipeline/jev_disclosure_search.py'),
              'role_sha256': sha(ROOT / 'pipeline/jev_disclosure_role.py'), 'counts': counts, 'records': records,
              'api_calls': 0, 'production_changes': 0, 'independent_reviews': 0,
              'limitation': 'Exact-name and context navigation, not independently measured relevance or recall. Other periods, instruments and roles are intentionally retained; existing candidates are not replaced and no flag is cleared.'}
    path = run / ('disclosure_search_profile_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, **counts}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
