"""Size all ready frozen requests offline using the runner's token proxy."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import make_request
from pipeline.jev_screening import fingerprint
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
    def count(value):
        return len(codec.encode(json.dumps(value, ensure_ascii=True), disallowed_special=()))
    rows = []
    for key, packet in sorted(packets.items()):
        if packet['evidence_status']['status'] != 'ready_for_model':
            continue
        request = make_request(packet)
        rows.append({'rule': key[0], 'row_id': key[1], 'cik': packet['flag']['cik'],
            'request_sha256': fingerprint(request), 'bundle_fingerprint': fingerprint(packet),
            'whole_request_proxy_tokens': count(request),
            'state_proxy_tokens': count(request['state']),
            'longest_question_proxy_tokens': max(count(q) for q in request['questions'].values()),
            'state_sections_proxy_tokens': {name: count(value) for name, value in request['state'].items()},
            'source_candidates': len(packet['source_candidates']),
            'source_notes': len(request['state']['source_notes'])})
    counts = sorted(r['whole_request_proxy_tokens'] for r in rows)
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
        'selected_flags': len(packets), 'ready_requests': len(rows),
        'ready_by_rule': dict(Counter(r['rule'] for r in rows)),
        'runner_proxy_limit': MAX_PROXY_TOKENS,
        'above_runner_proxy_limit': sum(n > MAX_PROXY_TOKENS for n in counts),
        'minimum': min(counts, default=None), 'maximum': max(counts, default=None),
        'median': counts[len(counts) // 2] if len(counts) % 2 else
                  ((counts[len(counts)//2-1] + counts[len(counts)//2])/2 if counts else None),
        'sum_whole_request_proxy_tokens': sum(counts), 'records': rows,
        'api_calls': 0, 'production_clearance_enabled': False,
        'limitations': ['cl100k is a proxy, not the provider tokenizer or an acceptance guarantee.',
            'Per-component counts do not reproduce provider state serialization or billing.',
            'Readiness and token fit do not establish correctness or independent clearance.']}
    destination = run / ('request_size_profile_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name,
        **{k: v for k, v in report.items() if k not in {'records', 'limitations'}}}), flush=True)


if __name__ == '__main__':
    main()
