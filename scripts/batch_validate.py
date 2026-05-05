"""Batch validate templates and collect results with fail_reasons.

Uses direct import instead of subprocesses for 10x+ faster execution.
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.validate_html_template import validate_cik

# Load all CIKs from template_claims.json
claims_path = Path('data/output/template_claims.json')
with open(claims_path) as f:
    claims = json.load(f)
CIKS = sorted(claims.keys(), key=lambda x: int(x))

# Allow filtering by command line
if len(sys.argv) > 1 and sys.argv[1] != '--all':
    CIKS = [c for c in sys.argv[1:] if c in claims or c.lstrip('0') in claims]

results = {}
for i, cik in enumerate(CIKS):
    sys.stdout.write(f"[{i+1}/{len(CIKS)}] CIK {cik:>10}... ")
    sys.stdout.flush()
    try:
        report = validate_cik(cik)
        status = report.get('overall', 'UNKNOWN')
        summary = report.get('summary', {})

        def _safe_round(val, digits=4):
            return round(val, digits) if val is not None else 0

        results[cik] = {
            'status': status,
            'ratio': str(_safe_round(summary.get('median_self_ref_ratio'), 4)),
            'in_range': f"{summary.get('self_ref_pass', 0)}/{summary.get('self_ref_pass', 0) + summary.get('self_ref_fail', 0)}",
            'filing_count': str(len(report.get('filings', []))),
            'median_carry': str(_safe_round(summary.get('median_carry'), 3)),
            'median_fv_fill': str(_safe_round(summary.get('median_fv_fill'), 3)),
            'extraction_coverage': str(_safe_round(summary.get('extraction_coverage'), 3)),
            'count_instability': summary.get('count_instability', 0),
            'fail_reasons': report.get('fail_reasons', []),
            'warn_reasons': report.get('warn_reasons', []),
        }
    except Exception as e:
        status = 'ERR'
        results[cik] = {'status': status, 'error': str(e)}
        traceback.print_exc()

    print(status)

    # Save incrementally every 10 CIKs
    if (i + 1) % 10 == 0:
        with open('data/output/batch_validate_results.json', 'w') as f:
            json.dump(results, f, indent=2)

# Summary
print("\n" + "=" * 70)
by_status = {}
for cik, r in results.items():
    by_status.setdefault(r['status'], []).append(cik)

for s in ['PASS', 'FAIL', 'NO_DATA', 'UNKNOWN', 'TIMEOUT', 'ERR']:
    if s in by_status:
        print(f"  {s}: {len(by_status[s])}")

if 'FAIL' in by_status:
    print(f"\nFAIL details:")
    for cik in by_status['FAIL']:
        r = results[cik]
        print(f"  CIK {cik}: ratio={r.get('ratio','?')}, in_range={r.get('in_range','?')}, "
              f"carry={r.get('median_carry','?')}, fv_fill={r.get('median_fv_fill','?')}, "
              f"count_instability={r.get('count_instability','?')}")
        for fr in r.get('fail_reasons', []):
            print(f"    FAIL: {fr}")
        for wr in r.get('warn_reasons', []):
            print(f"    WARN: {wr}")

# Save results
with open('data/output/batch_validate_results.json', 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to data/output/batch_validate_results.json")
