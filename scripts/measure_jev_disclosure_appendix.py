"""Size hypothetical supplementary-disclosure appendices; never submit requests."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import make_request, parser_runtime
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.run_jev_screening import MAX_PROXY_TOKENS


def main():
    import tiktoken
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
    profile_path = run / 'disclosure_search_profile_da03743e49495fec.json'
    profile = read(profile_path)
    if (len(packets) != 67 or profile['replay'] != args.replay
            or profile['parser_runtime'] != parser_runtime()
            or profile['search_sha256'] != sha(ROOT / 'pipeline/jev_disclosure_search.py')
            or profile['role_sha256'] != sha(ROOT / 'pipeline/jev_disclosure_role.py')):
        raise ValueError('Expected current navigation profile')
    navigation = {(r['rule'], r['row_id']): r for r in profile['records']}
    if len(navigation) != 67 or set(navigation) != set(packets):
        raise ValueError('Navigation membership differs')
    codec = tiktoken.get_encoding('cl100k_base')
    def count(value):
        return len(codec.encode(json.dumps(value, ensure_ascii=True), disallowed_special=()))
    records = []
    for key, packet in sorted(packets.items()):
        finding = navigation[key]
        if finding['bundle_fingerprint'] != fingerprint(packet):
            raise ValueError('Navigation packet binding differs')
        if packet['evidence_status']['status'] != 'ready_for_model':
            continue
        if finding['source_sha256'] != packet['filing']['sha256']:
            raise ValueError('Navigation source binding differs')
        existing = {(c['table_index'], c['row_index']) for c in packet['source_candidates']}
        extras = {}
        for method in ('search', 'exact_anchor_search', 'source_issuer_search'):
            for row in (finding[method] or {}).get('matches', []):
                coordinate = (row['table_index'], row['row_index'])
                if coordinate in existing:
                    continue
                evidence = {k: v for k, v in row.items() if k not in {'matched_phrases', 'matched_context_anchors'}}
                if coordinate in extras and extras[coordinate] != evidence:
                    raise ValueError('Navigation methods disagree about preserved source row')
                extras[coordinate] = evidence
        full_rows = [extras[c] for c in sorted(extras)]
        locators = [{
            'table_index': r['table_index'], 'row_index': r['row_index'],
            'parsed_report_date': r['parsed_report_date'], 'header_role': r['header_role']['role'],
            'unsupported_layout': r['unsupported_layout'], 'context_ids': r['context_ids'],
            'display_cells': [{k: c[k] for k in ('column', 'span', 'text', 'hidden_source_content') if k in c}
                              for c in r['source_cells']],
        } for r in full_rows]
        original = make_request(packet)
        modes = {'base_request': original}
        for name, rows in [('full_navigation_records', full_rows), ('locator_index_only', locators)]:
            hypothetical = deepcopy(original)
            hypothetical['state']['supplementary_navigation'] = {
                'schema_version': 'hypothetical-disclosure-appendix.v1', 'mode': name,
                'source_sha256': finding['source_sha256'], 'rows': rows,
                'limitation': 'Navigation only. Other periods/instruments and unknown roles are retained. This is not independently verified evidence or a clearance basis.',
            }
            modes[name] = hypothetical
        records.append({'rule': key[0], 'row_id': key[1], 'extra_source_rows': len(full_rows),
                        'bundle_fingerprint': fingerprint(packet),
                        'request_proxy_tokens': {name: count(value) for name, value in modes.items()}})
    aggregates = {}
    for name in ('base_request', 'full_navigation_records', 'locator_index_only'):
        values = [r['request_proxy_tokens'][name] for r in records]
        aggregates[name] = {'sum_proxy_tokens': sum(values), 'maximum': max(values),
                            'above_runner_proxy_limit': sum(v > MAX_PROXY_TOKENS for v in values),
                            'newly_above_runner_proxy_limit': sum(r['request_proxy_tokens'][name] > MAX_PROXY_TOKENS
                                and r['request_proxy_tokens']['base_request'] <= MAX_PROXY_TOKENS for r in records)}
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
              'navigation_profile_sha256': sha(profile_path), 'ready_requests': len(records),
              'requests_with_additional_source_rows': sum(r['extra_source_rows'] > 0 for r in records),
              'runner_proxy_limit': MAX_PROXY_TOKENS, 'aggregates': aggregates, 'records': records,
              'api_calls': 0, 'runner_changed': False, 'production_clearance_enabled': False,
              'limitations': ['Hypothetical payloads only; no model outcomes, provider token measurements or billing estimates.',
                  'Locator index deliberately omits facts, units, headers and context definitions retained in full records. It cannot replace complete evidence.',
                  'Neither appendix establishes complete relevant notes, sibling identity or ownership scope.',
                  'Counts use cl100k, not the Jev tokenizer. Added rows are not independently certified relevant.']}
    path = run / ('disclosure_appendix_size_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'ready_requests': len(records),
                      'requests_with_additional_source_rows': report['requests_with_additional_source_rows'],
                      'aggregates': aggregates}), flush=True)


if __name__ == '__main__':
    main()
