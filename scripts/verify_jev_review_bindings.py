"""Cross-check current replay content against previously frozen review bindings."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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
    if not args.review_label.replace('_', '').isalnum():
        raise ValueError('Invalid review label')
    summary, packets = load_replay(run, args.replay)
    directory = run / args.review_label
    manifest_path = directory / 'manifest.json'
    manifest = read(manifest_path)
    if (manifest.get('replay') != args.replay or manifest['builder_sha256'] != summary['builder_sha256']
            or len(manifest['inventory']) != len(packets) or len(packets) > 100):
        raise ValueError('Review and replay versions or counts differ')
    holdings_hash = sha(repo / 'data/output/private_markets_holdings.csv')
    if holdings_hash != manifest['holdings_sha256']:
        raise ValueError('Current holdings changed')
    expected = {fingerprint(p): p for p in packets.values()}
    seen, sources, records = set(), {}, []
    for item in manifest['inventory']:
        path = (directory / item['file']).resolve()
        if path.parent != directory or sha(path) != item['sha256']:
            raise ValueError('Prepared input changed or escaped directory')
        prepared = read(path)
        packet_id = prepared['snapshot']['bundle_fingerprint']
        if packet_id in seen or packet_id not in expected:
            raise ValueError('Replay content differs from prepared bindings')
        seen.add(packet_id)
        packet = expected[packet_id]
        if prepared['snapshot']['holdings_sha256'] != holdings_hash:
            raise ValueError('Prepared holdings binding differs')
        source = Path(prepared['source']['path']).resolve()
        if not source.is_relative_to(repo / 'data/raw') or source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Unsupported cached source path or size')
        if source not in sources:
            sources[source] = sha(source)
        if sources[source] != prepared['source']['sha256']:
            raise ValueError('Original source changed')
        if packet['filing'].get('sha256') and packet['filing']['sha256'] != sources[source]:
            raise ValueError('Replay source binding differs')
        form = prepared['review_form']
        if form['reviewer'] is not None or form['disposition'] is not None or any(v is not None for v in form['checks'].values()):
            raise ValueError('Expected unfinished prepared input, not a completed finding')
        records.append({'review_id': prepared['review_id'], 'packet_fingerprint': packet_id,
                        'prepared_file_sha256': item['sha256']})
    if seen != set(expected):
        raise ValueError('Unaccounted replay packets')
    report = {'replay': args.replay, 'review_label': args.review_label,
        'prepared_manifest_sha256': sha(manifest_path), 'builder_sha256': summary['builder_sha256'],
        'holdings_sha256': holdings_hash, 'packets': len(records), 'source_files': len(sources),
        'records': records, 'source_bytes_unchanged': True, 'prepared_bindings_match': True,
        'completed_reviews': 0, 'production_clearance_enabled': False,
        'limitation': 'Content agreement with earlier bindings is not an independent source-evidence audit.'}
    destination = run / ('review_binding_check_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(120, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
