"""Writes the three tables and a manifest. Same inputs give the same manifest: no timestamps."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import duckdb

from . import (CORRECTION_COLUMNS, CORRECTION_RULE_COLUMNS, LABEL_EXAMPLE_COLUMNS, LOADER_VERSION, NOT_LOADED_COLUMNS,
               RULE_COLUMNS, WRAPPER_DRIFT_COLUMNS, LoadError)

TABLES = {
    "reading_rule": (RULE_COLUMNS, ["rule_id"]),
    "correction": (CORRECTION_COLUMNS, ["correction_id"]),
    "correction_rule": (CORRECTION_RULE_COLUMNS, ["source_file"]),
    "not_loaded": (NOT_LOADED_COLUMNS, ["cik", "wrapper_key", "entry"]),
    "wrapper_drift": (WRAPPER_DRIFT_COLUMNS, ["cik"]),
    "rule_label_example": (LABEL_EXAMPLE_COLUMNS, ["rule_id", "label"]),
}
_INTEGER = {"priority"}
_BOOLEAN = {"changed", "expected_match"}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def text_sha256(data):
    """SHA-256 of a text file's bytes with every CRLF read as LF (slice 4 Task 5, repair a). The wrapper-drift check
    uses it, so a checkout that writes CRLF line endings (Windows, core.autocrlf) hashes the same as one that writes LF;
    any other change still changes the hash. data: bytes, or a path to read. stg_wrapper_drift computes the same value
    in SQL: sha256(replace(content, chr(13) || chr(10), chr(10))) over read_text."""
    raw = data if isinstance(data, (bytes, bytearray)) else Path(data).read_bytes()
    return hashlib.sha256(bytes(raw).replace(b"\r\n", b"\n")).hexdigest()


def _sorted_unique(name, rows):
    columns, key = TABLES[name]
    rows = sorted(rows, key=lambda r: tuple(str(r[c]) for c in key))
    keys = [tuple(r[c] for c in key) for r in rows]
    dups = sorted({k for a, k in zip(keys, keys[1:]) if a == k})
    if dups:
        raise LoadError(f"{name}: {len(dups)} duplicate key(s), first {dups[0]}")
    return [[r[c] for c in columns] for r in rows]


def _content_hash(rows):
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def _write_parquet(con, name, rows, folder):
    columns, _ = TABLES[name]
    types = {c: ("INTEGER" if c in _INTEGER else "BOOLEAN" if c in _BOOLEAN else "VARCHAR") for c in columns}
    con.execute(f'CREATE OR REPLACE TABLE "{name}" (' + ", ".join(f'"{c}" {types[c]}' for c in columns) + ")")
    if rows:
        tmp = Path(folder) / f"{name}.ndjson"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(dict(zip(columns, r)), ensure_ascii=True) + "\n")
        spec = ", ".join(f"'{c}': '{types[c]}'" for c in columns)
        con.execute(f"INSERT INTO \"{name}\" SELECT * FROM read_json('{tmp.as_posix()}', "
                    f"format='newline_delimited', columns={{{spec}}}, maximum_object_size=67108864)")
        os.remove(tmp)
    con.execute(f"COPY \"{name}\" TO '{(Path(folder) / (name + '.parquet')).as_posix()}' (FORMAT PARQUET)")


def write(out_dir, tables, inputs):
    """Write the tables under out_dir, replacing what is there. Returns the manifest.

    `tables` maps table name to a list of row dicts; `inputs` maps a relative path to its SHA-256.
    tables["wrapper_copy_sha256"] (fund -> SHA-256 of the wrapper copy read) is not a table: it goes into the
    manifest under the same key, path-free, for dbt's build-time check (stg_wrapper_drift).
    Everything is written to a temporary folder first, so a failure leaves the old output in place.
    """
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    prepared = {name: _sorted_unique(name, tables.get(name, [])) for name in TABLES}
    manifest = {
        "loader_version": LOADER_VERSION,
        "inputs": dict(sorted(inputs.items())),
        "tables": {name: {"rows": len(rows), "content_sha256": _content_hash(rows)}
                   for name, rows in prepared.items()},
        # Funds whose production wrapper changed since the new pipeline's copy was taken (table wrapper_drift).
        "production_wrappers_changed": sorted(r["cik"] for r in tables.get("wrapper_drift", []) if r["changed"]),
        # SHA-256 of each wrapper copy the loader parsed, by fund (final fix wave F1).
        "wrapper_copy_sha256": dict(sorted((tables.get("wrapper_copy_sha256") or {}).items())),
        # Loader version 6: text hash (CRLF read as LF) of every file of a scope fund in the two agent stores, loaded or
        # skipped, keyed <store>/<dir>/<file>; dbt hashes the same files at build time (stg_agent_store_drift).
        "agent_store_sha256": dict(sorted((tables.get("agent_store_sha256") or {}).items())),
        # The files of agent_store_sha256 that were not loaded, with the reason.
        "agent_store_skipped": dict(sorted((tables.get("agent_store_skipped") or {}).items())),
    }
    tmp = Path(tempfile.mkdtemp(prefix=".readings_tmp_", dir=str(out_dir.parent)))
    try:
        con = duckdb.connect()
        for name, rows in prepared.items():
            _write_parquet(con, name, rows, tmp)
        con.close()
        (tmp / "_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        os.replace(tmp, out_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return manifest
