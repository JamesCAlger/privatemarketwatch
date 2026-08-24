"""Validate ONE bdc_cik_review verdict file (schema + bundle checks).

Per-item dispatcher gate: unlike validate_verdicts.py --all, this does NOT
check worklist membership across the whole store (historical verdicts from
retired worklists would fail), only the named file. Exit 0 = valid.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.bdc_cik_review import validate_verdict_file


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_one_verdict.py <verdict.json>")
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"INVALID: missing file: {path}")
        return 1
    errors = validate_verdict_file(path)
    if errors:
        for e in errors:
            print(f"INVALID: {e}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
