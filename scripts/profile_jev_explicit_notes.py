"""Measure exact-context note-link availability across the original 67 cases."""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys
import threading

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import parser_runtime
from pipeline.jev_explicit_notes import resolve_explicit_notes
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    runtime = parser_runtime()
    replay, review = 'dependency_bound_v4_55', run / 'blind_review_inputs_56'
    summary, packets = load_replay(run, replay)
    manifest = read(review / 'manifest.json')
    manifest_hash = sha(review / 'manifest.json')
    if len(packets) != 67 or summary['parser_runtime'] != runtime or manifest['replay'] != replay:
        raise ValueError('Frozen 67-case runtime required')
    by_hash = {fingerprint(p): p for p in packets.values()}
    seen, sources = set(), defaultdict(list)
    for item in manifest['inventory']:
        prepared_path = (review / item['file']).resolve()
        if prepared_path.parent != review or sha(prepared_path) != item['sha256']:
            raise ValueError('Prepared source input changed or escaped')
        prepared = read(prepared_path)
        binding = prepared['snapshot']['bundle_fingerprint']
        if binding not in by_hash or binding in seen:
            raise ValueError('Invalid source binding')
        seen.add(binding)
        sources[(prepared['source']['path'], prepared['source']['sha256'])].append(by_hash[binding])
    if seen != set(by_hash) or len(sources) != 26:
        raise ValueError('Incomplete original source scope')
    records = []
    for index, ((filename, digest), local) in enumerate(sorted(sources.items()), 1):
        source = Path(filename).resolve()
        if (not source.is_relative_to(repo / 'data/raw/filings/bdc_html')
                or source.stat().st_size > 40 * 1024 * 1024 or sha(source) != digest):
            raise ValueError('Frozen bounded source required')
        print(f'Explicit note profile: {index}/26, {len(local)} flags', flush=True)
        soup = BeautifulSoup(source.read_bytes(), 'lxml')
        by_context = defaultdict(list)
        for fact in soup.find_all('ix:nonfraction'):
            if str(fact.get('name', '')).split(':')[-1].lower() in {'investmentownedatcost', 'investmentownedatfairvalue'}:
                by_context[fact.get('contextref')].append(fact)
        for packet in local:
            context = packet['output_position'].get('src_context_id')
            facts = by_context.get(context, []) if context else []
            ids = [f.get('id') for f in facts]
            refusal, diagnostic = None, None
            if not ids:
                refusal = 'no_standard_monetary_facts_at_exact_context'
            elif any(not f for f in ids) or len(ids) != len(set(ids)):
                refusal = 'missing_or_duplicate_selected_fact_ids'
            elif len(ids) > 100:
                refusal = 'selected_fact_cap_exceeded'
            else:
                try:
                    diagnostic = resolve_explicit_notes(soup, ids)
                except ValueError as exc:
                    refusal = str(exc)
            records.append({'row_id': packet['flag']['row_id'], 'cik': packet['flag']['cik'],
                            'bundle_fingerprint': fingerprint(packet), 'source_sha256': digest,
                            'context_id': context, 'fact_ids': ids, 'refusal': refusal,
                            'diagnostic': diagnostic, 'builder_status': packet['evidence_status']['status']})
        soup.decompose()
        if sha(source) != digest:
            raise ValueError('Source changed during profile')
    if parser_runtime() != runtime or sha(review / 'manifest.json') != manifest_hash:
        raise ValueError('Runtime or manifest changed')
    diagnosed = [r for r in records if r['diagnostic']]
    any_link = [r for r in diagnosed if any(f['notes'] for f in r['diagnostic']['records'])]
    all_resolved = [r for r in diagnosed if all(f['status'] == 'explicit_links_resolved' for f in r['diagnostic']['records'])]
    counts = {'flags': len(records), 'files': len(sources), 'diagnosed': len(diagnosed),
              'refused': len(records) - len(diagnosed), 'flags_with_any_resolved_note': len(any_link),
              'flags_with_all_selected_fact_links_resolved': len(all_resolved),
              'funds_with_any_resolved_note': len({r['cik'] for r in any_link}),
              'funds_with_all_selected_fact_links_resolved': len({r['cik'] for r in all_resolved}),
              'fact_blocker_counts': dict(Counter(b for r in diagnosed for f in r['diagnostic']['records'] for b in f['blockers'])),
              'refusal_counts': dict(Counter(r['refusal'] for r in records if r['refusal']))}
    report = {'counts': counts, 'records': records, 'replay': replay,
              'review_manifest_sha256': manifest_hash, 'parser_runtime': runtime,
              'helper_sha256': sha(ROOT / 'pipeline/jev_explicit_notes.py'),
              'script_sha256': sha(Path(__file__)), 'api_calls': 0, 'production_changes': 0,
              'limitation': 'Exact-context standard monetary facts only. Links are availability evidence, not complete note recall, period/ownership certification or readiness promotion.'}
    path = run / ('explicit_note_profile_' + fingerprint(report)[:16] + '.json')
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
