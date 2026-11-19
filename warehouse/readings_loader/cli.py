"""Command line: load the scope funds' wrappers and row-correction stores into warehouse/data/readings."""
import argparse
import json
from collections import Counter
from pathlib import Path

from . import LoadError, row_stores, store, wrappers

SCOPE_FILE = Path("data/reference/quarter_acceptance_thresholds.json")
WRAPPERS_DIR = Path("data/overrides/bdc_xbrl_wrappers")
ROW_STORES = [
    ("row_corrections", Path("data/overrides/row_corrections.csv")),
    ("row_corrections_by_context", Path("data/overrides/row_corrections_by_context.csv")),
]


def load_scope(scope_file):
    data = json.loads(Path(scope_file).read_text(encoding="utf-8"))
    return [str(c).strip().zfill(10) for c in data["findings_scope"]["ciks"]]


def load(ciks, wrappers_dir, row_store_paths):
    """(tables, inputs) for the given funds. Raises LoadError if a wrapper is missing or unreadable."""
    tables = {"reading_rule": [], "correction": [], "not_loaded": []}
    inputs = {}
    for cik in sorted(ciks):
        path = Path(wrappers_dir) / f"{cik}.json"
        if not path.exists():
            raise LoadError(f"no wrapper for {cik} at {path.as_posix()}")
        rules, corrections, not_loaded = wrappers.flatten(cik, json.loads(path.read_text(encoding="utf-8-sig")))
        tables["reading_rule"] += rules
        tables["correction"] += corrections
        tables["not_loaded"] += not_loaded
        inputs[path.as_posix()] = store.file_sha256(path)
    for name, path in row_store_paths:
        tables["correction"] += row_stores.read_row_corrections(path, name, ciks)
        inputs[Path(path).as_posix()] = store.file_sha256(path)
    return tables, inputs


def main(argv=None):
    p = argparse.ArgumentParser(prog="readings_loader", description=__doc__)
    p.add_argument("--out", default="warehouse/data/readings")
    p.add_argument("--scope-file", default=str(SCOPE_FILE))
    p.add_argument("--wrappers", default=str(WRAPPERS_DIR))
    args = p.parse_args(argv)
    try:
        tables, inputs = load(load_scope(args.scope_file), args.wrappers, ROW_STORES)
        manifest = store.write(args.out, tables, inputs)
    except LoadError as exc:
        print(f"ERROR: {exc}")
        return 1
    for name, info in manifest["tables"].items():
        print(f"{name}: {info['rows']} rows")
    for title, table, column in (("rules by class", "reading_rule", "rule_class"),
                                 ("rules by origin", "reading_rule", "origin"),
                                 ("corrections by store", "correction", "store"),
                                 ("corrections by kind", "correction", "kind")):
        counts = Counter(r[column] for r in tables[table])
        print(f"{title}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for n in tables["not_loaded"]:
        print(f"not loaded: {n['cik']} {n['wrapper_key']} {n['entry']} ({n['reason']})")
    return 0
