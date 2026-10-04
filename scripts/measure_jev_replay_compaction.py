"""Compare optional encodings on all ready replay requests; no submissions."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import make_request
from pipeline.jev_screening import fingerprint
from pipeline.jev_state_compaction import compact_request, expand_request
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write
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
    if len(packets) > 100 or summary['builder_sha256'] != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Bounded current-builder replay required')
    codec = tiktoken.get_encoding('cl100k_base')
    rows = []
    for key, packet in sorted(packets.items()):
        if packet['evidence_status']['status'] != 'ready_for_model':
            continue
        original = make_request(packet)
        original_hash = fingerprint(original)
        encodings = {'original': original}
        for version in ('lossless-grid.v1', 'lossless-grid.v2'):
            encoded = compact_request(original, version=version)
            if fingerprint(expand_request(encoded)) != original_hash or fingerprint(original) != original_hash:
                raise ValueError('Reconstruction or input immutability failed')
            encodings[version] = encoded
        rows.append({'rule': key[0], 'row_id': key[1], 'cik': packet['flag']['cik'],
            'bundle_fingerprint': fingerprint(packet), 'round_trip_verified': True,
            'encodings': {name: {'request_sha256': fingerprint(value),
                'whole_request_proxy_tokens': len(codec.encode(json.dumps(value, ensure_ascii=True), disallowed_special=()))}
                for name, value in encodings.items()}})
    aggregates = {}
    for version in ('original', 'lossless-grid.v1', 'lossless-grid.v2'):
        values = [r['encodings'][version]['whole_request_proxy_tokens'] for r in rows]
        aggregates[version] = {'sum_proxy_tokens': sum(values), 'maximum': max(values, default=None),
                              'above_runner_proxy_limit': sum(n > MAX_PROXY_TOKENS for n in values)}
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
        'compactor_sha256': sha(ROOT / 'pipeline/jev_state_compaction.py'),
        'ready_requests': len(rows), 'runner_proxy_limit': MAX_PROXY_TOKENS,
        'aggregates': aggregates, 'records': rows, 'api_calls': 0,
        'runner_encoding_changed': False, 'production_clearance_enabled': False,
        'limitations': ['Exact reconstruction does not establish unchanged model interpretation, confidence or provider token fit.',
            'No source facts, candidates, notes, empty cells or annotations were intentionally omitted.',
            'Proxy savings are not measured provider billing or B1 savings.']}
    path = run / ('replay_compaction_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'ready_requests': len(rows), 'aggregates': aggregates}), flush=True)


if __name__ == '__main__':
    main()
