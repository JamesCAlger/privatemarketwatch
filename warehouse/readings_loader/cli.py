"""Command line: load the scope funds' wrappers and row-correction stores into warehouse/data/readings.

The wrappers read are the new pipeline's own copies (warehouse/wrappers/<cik>.json, owner decision 2026-11-19).
Production keeps its wrappers in data/overrides/bdc_xbrl_wrappers until cutover; the loader compares each one with
the hash recorded when the copy was taken (warehouse/wrappers/_source.json) and writes the result to the table
wrapper_drift and the manifest, so an edit on the production side is seen and carried over by hand. The manifest also
records the hash of each copy read (wrapper_copy_sha256). dbt hashes both sets of files again at build time
(stg_wrapper_drift), so a build without a reload still fails on an edit made after this load (final fix wave F1).
Both wrapper hashes are text hashes: the file's bytes with CRLF read as LF (store.text_sha256, slice 4 Task 5), so a
checkout that writes CRLF line endings does not raise a false drift.
"""
import argparse
import hashlib
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
        # the text hash (CRLF read as LF, store.text_sha256): a CRLF checkout of an unchanged wrapper is not drift
        current = store.text_sha256(prod) if prod.exists() else ""
        if current:
            inputs[prod.as_posix()] = store.file_sha256(prod)
        rows.append({"cik": cik, "copied_sha256": copied, "current_sha256": current, "changed": current != copied})
    return rows, inputs


def load(ciks, wrappers_dir, row_store_paths, production_dir=None):
    """(tables, inputs) for the given funds. Raises LoadError if a wrapper is missing or unreadable.

    With production_dir, also the wrapper_drift table (production wrapper changed since the copy was taken).
    tables["wrapper_copy_sha256"] maps each fund to the SHA-256 of the copy bytes that were parsed; it goes into the
    manifest only (store.write), where dbt compares it with the copy at build time (stg_wrapper_drift)."""
    tables = {"reading_rule": [], "correction": [], "not_loaded": [], "wrapper_drift": [], "rule_label_example": [],
              "wrapper_copy_sha256": {}}
    inputs = {}
    for cik in sorted(ciks):
        path = Path(wrappers_dir) / f"{cik}.json"
        if not path.exists():
            raise LoadError(f"no wrapper for {cik} at {path.as_posix()}")
        raw = path.read_bytes()
        wrapper = json.loads(raw.decode("utf-8-sig"))
        rules, corrections, not_loaded = wrappers.flatten(cik, wrapper)
        tables["reading_rule"] += rules
        tables["correction"] += corrections
        tables["not_loaded"] += not_loaded
        tables["rule_label_example"] += wrappers.label_examples(cik, wrapper)
        # the hash of the bytes parsed above, so the record cannot describe a later edit; the drift record takes the
        # text hash (CRLF read as LF, store.text_sha256), inputs keeps the raw bytes' hash
        inputs[path.as_posix()] = hashlib.sha256(raw).hexdigest()
        tables["wrapper_copy_sha256"][cik] = store.text_sha256(raw)
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
    # The two row-correction stores. Defaults are production's files; the CI fixture build passes its own
    # (warehouse/ci/run_fixture_build.py).
    for name, path in ROW_STORES:
        p.add_argument("--" + name.replace("_", "-"), dest=name, default=str(path))
    args = p.parse_args(argv)
    row_store_paths = [(name, Path(getattr(args, name))) for name, _ in ROW_STORES]
    try:
        tables, inputs = load(load_scope(args.scope_file), args.wrappers, row_store_paths, args.production_wrappers)
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
