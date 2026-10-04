"""Separate evidence, policy and size readiness without transferring old scores."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import make_request
from pipeline.jev_screening import Policy, fingerprint, route_flag
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
    holdings_hash = sha(repo / 'data/output/private_markets_holdings.csv')
    if any(p['provenance']['holdings_sha256'] != holdings_hash for p in packets.values()):
        raise ValueError('Holdings snapshot changed')
    codec = tiktoken.get_encoding('cl100k_base')
    sizes = {key: len(codec.encode(json.dumps(make_request(p), ensure_ascii=True), disallowed_special=()))
             for key, p in packets.items() if p['evidence_status']['status'] == 'ready_for_model'}
    policies = {'default_C107_X08': Policy(),
                'explicit_C104_development_probe': Policy(eligible_rules=('C107', 'X08', 'C104'))}
    groups = {}
    for name, policy in policies.items():
        rows = []
        for key, packet in sorted(packets.items()):
            receipt = route_flag(packet, None, None, policy=policy, expected_provenance=packet['provenance'])
            reasons = list(receipt['reasons'])
            if receipt['route'] == 'pending':
                status = 'size_fallback' if sizes[key] > MAX_PROXY_TOKENS else 'awaiting_current_model_and_audit'
            else:
                status = 'evidence_or_policy_fallback'
            rows.append({'rule': key[0], 'row_id': key[1], 'bundle_fingerprint': fingerprint(packet),
                'status': status, 'router_without_model_reasons': reasons, 'proxy_tokens': sizes.get(key)})
        counts = dict(Counter(r['status'] for r in rows))
        if sum(counts.values()) != len(packets):
            raise ValueError('Incomplete funnel accounting')
        groups[name] = {'policy': asdict(policy), 'counts': counts,
            'by_rule': {rule: dict(Counter(r['status'] for r in rows if r['rule'] == rule))
                        for rule in sorted({k[0] for k in packets})}, 'records': rows}
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
        'router_sha256': sha(ROOT / 'pipeline/jev_screening.py'), 'holdings_sha256': holdings_hash,
        'selected_flags': len(packets), 'evidence_ready': len(sizes),
        'evidence_ready_and_within_proxy_cap': sum(n <= MAX_PROXY_TOKENS for n in sizes.values()),
        'runner_proxy_limit': MAX_PROXY_TOKENS, 'policy_scenarios': groups,
        'current_model_results_supplied': 0, 'audit_records_supplied': 0,
        'production_clearance_enabled': False, 'b1_work_suppressed': False,
        'limitations': ['Counts are nested readiness stages, not measured B1 jobs, independent clearances or production coverage.',
            'Expected provenance uses the checked frozen replay, not a newly certified production queue.',
            'C104 eligibility is an explicit development probe; the default policy excludes it.',
            'No high-error-rate population is inferred from this selected sample; production risk eligibility remains unvalidated.',
            'Historical model scores are not applied to changed current requests.']}
    path = run / ('screening_funnel_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'selected': len(packets), 'evidence_ready': len(sizes),
        'scenarios': {name: {k: v for k, v in g.items() if k != 'records'} for name, g in groups.items()}}), flush=True)


if __name__ == '__main__':
    main()
