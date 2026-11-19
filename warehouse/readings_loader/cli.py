"""Command line: load the scope funds' wrappers and row-correction stores into warehouse/data/readings.

The wrappers read are the new pipeline's own copies (warehouse/wrappers/<cik>.json, owner decision 2026-11-19).
Production keeps its wrappers in data/overrides/bdc_xbrl_wrappers until cutover; the loader compares each one with
the hash recorded when the copy was taken (warehouse/wrappers/_source.json) and writes the result to the table
wrapper_drift and the manifest, so an edit on the production side is seen and carried over by hand.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from . import LoadError, row_stores, store, wrappers

SCOPE_FILE = Path("data/reference/quarter_acceptance_thresholds.json")
WRAPPERS_DIR = Path("warehouse/wrappers")
PRODUCTION_WRAPPERS_DIR = Path("data/overrides/bdc_xbrl_wrappers")
SOURCE_FILE = "_source.json"
ROW_STORES = [
    ("row_corrections", Path("data/overrides/row_corrections.csv")),
    ("row_corrections_by_context", Path("data/overrides/row_corrections_by_context.csv")),
]


def load_scope(scope_file):
    data = json.loads(Path(scope_file).read_text(encoding="utf-8"))
    return [str(c).strip().zfill(10) for c in data["findings_scope"]["ciks"]]


def wrapper_drift(ciks, wrappers_dir, production_dir):
    """(rows, inputs): per fund, the production wrapper's SHA-256 when copied and now. Missing record -> LoadError."""
    source_path = Path(wrappers_dir) / SOURCE_FILE
    if not source_path.exists():
        raise LoadError(f"no copy record at {source_path.as_posix()}")
    funds = json.loads(source_path.read_text(encoding="utf-8")).get("funds") or {}
    rows, inputs = [], {source_path.as_posix(): store.file_sha256(source_path)}
    for cik in sorted(ciks):
        copied = (funds.get(cik) or {}).get("sha256", "")
        if not copied:
            raise LoadError(f"{cik}: no copied hash in {source_path.as_posix()}")
        prod = Path(production_dir) / f"{cik}.json"
        current = store.file_sha256(prod) if prod.exists() else ""
        if current:
            inputs[prod.as_posix()] = current
        rows.append({"cik": cik, "copied_sha256": copied, "current_sha256": current, "changed": current != copied})
    return rows, inputs


def load(ciks, wrappers_dir, row_store_paths, production_dir=None):
    """(tables, inputs) for the given funds. Raises LoadError if a wrapper is missing or unreadable.

    With production_dir, also the wrapper_drift table (production wrapper changed since the copy was taken)."""
    tables = {"reading_rule": [], "correction": [], "not_loaded": [], "wrapper_drift": [], "rule_label_example": []}
    inputs = {}
    for cik in sorted(ciks):
        path = Path(wrappers_dir) / f"{cik}.json"
        if not path.exists():
            raise LoadError(f"no wrapper for {cik} at {path.as_posix()}")
        wrapper = json.loads(path.read_text(encoding="utf-8-sig"))
        rules, corrections, not_loaded = wrappers.flatten(cik, wrapper)
        tables["reading_rule"] += rules
        tables["correction"] += corrections
        tables["not_loaded"] += not_loaded
        tables["rule_label_example"] += wrappers.label_examples(cik, wrapper)
        inputs[path.as_posix()] = store.file_sha256(path)
    if production_dir is not None:
        drift, drift_inputs = wrapper_drift(ciks, wrappers_dir, production_dir)
        tables["wrapper_drift"] = drift
        inputs.update(drift_inputs)
    for name, path in row_store_paths:
        tables["correction"] += row_stores.read_row_corrections(path, name, ciks)
        inputs[Path(path).as_posix()] = store.file_sha256(path)
    return tables, inputs


def main(argv=None):
    p = argparse.ArgumentParser(prog="readings_loader", description=__doc__)
    p.add_argument("--out", default="warehouse/data/readings")
    p.add_argument("--scope-file", default=str(SCOPE_FILE))
    p.add_argument("--wrappers", default=str(WRAPPERS_DIR))
    p.add_argument("--production-wrappers", default=str(PRODUCTION_WRAPPERS_DIR))
    args = p.parse_args(argv)
    try:
        tables, inputs = load(load_scope(args.scope_file), args.wrappers, ROW_STORES, args.production_wrappers)
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
    changed = manifest.get("production_wrappers_changed", [])
    print("production wrappers changed since the copy: " + (", ".join(changed) if changed else "none"))
    return 0
