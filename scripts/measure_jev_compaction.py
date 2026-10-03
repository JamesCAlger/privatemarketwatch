"""Measure lossless encoding on frozen requests; no API calls or new funds."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_state_compaction import compact_request, expand_request
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, write


def main():
    import tiktoken
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    tokenizer = tiktoken.get_encoding('cl100k_base')
    reports = []
    for label in ['development_model_01', 'consumed_holdout_model_01', 'controlled_model_01', 'weak_probe_model_01']:
        paths = sorted((run / label / 'requests').glob('*.json'))
        if len(paths) > 50:
            raise ValueError('Run request limit exceeded')
        for path in paths:
            original = read(path)
            compact = compact_request(original)
            if fingerprint(expand_request(compact)) != fingerprint(original):
                raise ValueError('Evidence round trip failed')
            counts = [len(tokenizer.encode(json.dumps(r, ensure_ascii=True), disallowed_special=()))
                      for r in [original, compact]]
            reports.append({'run': label, 'request_id': path.stem, 'original_proxy_tokens': counts[0],
                            'compact_proxy_tokens': counts[1], 'saved_proxy_tokens': counts[0] - counts[1],
                            'lossless_round_trip': True})
    before = sum(r['original_proxy_tokens'] for r in reports)
    after = sum(r['compact_proxy_tokens'] for r in reports)
    summary = {'requests': len(reports), 'original_proxy_tokens': before, 'compact_proxy_tokens': after,
               'proxy_reduction_pct': 100 * (before - after) / before,
               'limitation': 'cl100k token proxy, not provider billing. Lossless reconstruction does not establish unchanged model behaviour.'}
    write(run / 'compaction_measurement_01.json', {'summary': summary, 'records': reports})
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
