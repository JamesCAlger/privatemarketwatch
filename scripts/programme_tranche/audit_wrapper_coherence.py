"""Read-only, bounded inventory of all committed wrapper coherence errors."""
import json
from pathlib import Path
import time

from pipeline.bdc_xbrl_wrapper_oracle import validate_wrapper_json_coherence
from pipeline.programme.core import atomic_json, record

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'scratch/2026-09-10_verification_investigation/wrapper_coherence.json'


def main():
    started = time.monotonic()
    paths = sorted((ROOT/'data/overrides/bdc_xbrl_wrappers').glob('*.json'))
    assert len(paths) < 500, 'Bounded diagnostic exceeded its file limit'
    checked, failures = 0, []
    for path in paths:
        if 'reference' in path.name:
            continue
        assert time.monotonic()-started < 30, 'Bounded diagnostic exceeded its time limit'
        raw = json.loads(path.read_text(encoding='utf-8'))
        if raw.get('schema_version') not in ('bdc-xbrl-wrapper.v2', 'bdc-xbrl-wrapper.v3'):
            continue
        checked += 1
        issues = validate_wrapper_json_coherence(raw)
        errors = [issue for issue in issues if not issue.startswith('warning:')]
        if errors:
            item = dict(source=record(ROOT, path.relative_to(ROOT).as_posix()), errors=errors)
            failures.append(item)
            print(path.name+': '+repr(errors), flush=True)
    atomic_json(OUT, dict(checked=checked, failures=failures, elapsed_seconds=time.monotonic()-started))
    print(str(checked)+' wrappers checked; '+str(len(failures))+' with hard errors', flush=True)


if __name__ == '__main__':
    main()
