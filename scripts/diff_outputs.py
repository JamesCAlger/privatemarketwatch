"""Compare current pipeline outputs against the refactor baseline snapshot."""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MANIFEST_FILE = ROOT / "docs" / "refactoring" / "baseline_manifest.json"
SQL_SPECS = [
    ("classification_index.sql", "pipeline.unified_holdings", "_sql_classify_index"),
    ("classification_exposure_type.sql", "pipeline.unified_holdings", "_sql_classify_exposure_type"),
    ("classification_asset_class.sql", "pipeline.unified_holdings", "_sql_classify_asset_class"),
    ("bdc_aggregate.sql", "pipeline.unified_holdings", "_sql_is_bdc_aggregate"),
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_csv_diff(left: Path, right: Path) -> str:
    with left.open("r", encoding="utf-8", errors="replace", newline="") as a:
        with right.open("r", encoding="utf-8", errors="replace", newline="") as b:
            for line_no, (la, lb) in enumerate(zip(a, b), start=1):
                if la != lb:
                    return (
                        f"first differing line {line_no}\n"
                        f"  baseline: {la[:240].rstrip()}\n"
                        f"  current:  {lb[:240].rstrip()}"
                    )
            extra_a = a.readline()
            extra_b = b.readline()
            if extra_a:
                return f"current ended before baseline; next baseline line: {extra_a[:240].rstrip()}"
            if extra_b:
                return f"baseline ended before current; next current line: {extra_b[:240].rstrip()}"
    return "no textual row diff found"


def diff(compare_sql: bool = True) -> int:
    if not MANIFEST_FILE.exists():
        print(f"Missing manifest: {MANIFEST_FILE.relative_to(ROOT).as_posix()}")
        return 2
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    failures: list[str] = []
    checked = 0
    skipped = 0

    for entry in manifest.get("artifacts", []):
        if entry.get("status") != "byte_identical":
            skipped += 1
            continue
        rel = entry["path"]
        current = ROOT / rel
        baseline = ROOT / entry["snapshot_path"]
        checked += 1
        if not current.exists():
            failures.append(f"{rel}: current file is missing")
            continue
        if not baseline.exists():
            failures.append(f"{rel}: baseline snapshot is missing")
            continue
        current_sha = _sha256(current)
        if current_sha == entry["sha256"] and filecmp.cmp(current, baseline, shallow=False):
            continue
        detail = ""
        if current.suffix.lower() == ".csv":
            detail = "\n" + _first_csv_diff(baseline, current)
        failures.append(
            f"{rel}: differs from baseline "
            f"(baseline {entry['sha256']}, current {current_sha}){detail}"
        )

    if compare_sql:
        generated = {}
        for filename, module_name, func_name in SQL_SPECS:
            try:
                module = __import__(module_name, fromlist=[func_name])
                generated[filename] = getattr(module, func_name)().encode("utf-8")
            except Exception as exc:
                failures.append(f"generated SQL {filename}: could not import/call {module_name}.{func_name}: {exc}")
        for entry in manifest.get("generated_sql", []):
            if entry.get("status") != "byte_identical":
                continue
            rel = f"data/snapshots/baseline/generated_sql/{entry['name']}"
            path = ROOT / rel
            checked += 1
            if not path.exists():
                failures.append(f"{rel}: SQL snapshot is missing")
                continue
            if _sha256(path) != entry["sha256"]:
                failures.append(f"{rel}: SQL snapshot changed on disk")
                continue
            current_sql = generated.get(entry["name"])
            if current_sql is None:
                continue
            digest = hashlib.sha256(current_sql).hexdigest()
            if digest != entry["sha256"]:
                failures.append(
                    f"generated SQL {entry['name']}: differs from baseline "
                    f"(baseline {entry['sha256']}, current {digest})"
                )

    if failures:
        print(f"Diff failed: {len(failures)} divergent artifact(s), {checked} checked, {skipped} skipped")
        for failure in failures[:50]:
            print(f"- {failure}")
        if len(failures) > 50:
            print(f"... {len(failures) - 50} more")
        return 1

    print(f"Diff clean: {checked} checked, {skipped} explicitly skipped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-sql", action="store_true", help="skip generated SQL snapshot checks")
    args = parser.parse_args()
    return diff(compare_sql=not args.no_sql)


if __name__ == "__main__":
    raise SystemExit(main())
