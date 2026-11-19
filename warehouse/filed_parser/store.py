"""Table definitions and the write-once Parquet store (spec: warehouse/docs/filed_layer.md, sections 3-4)."""
import datetime
import hashlib
import json
import os
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

import duckdb

from . import PARSER_VERSION

# (column, DuckDB type) in output order. Every table starts with accession.
TABLES = {
    "filing": [
        ("accession", "VARCHAR"), ("cik", "VARCHAR"), ("document_type", "VARCHAR"),
        ("document_period_end_date", "DATE"), ("amendment_flag", "BOOLEAN"),
        ("fiscal_year_focus", "VARCHAR"), ("fiscal_period_focus", "VARCHAR"),
        ("registrant_name", "VARCHAR"), ("instance_file", "VARCHAR"),
        ("instance_sha256", "VARCHAR"), ("instance_bytes", "BIGINT"),
        ("html_file", "VARCHAR"), ("html_sha256", "VARCHAR"), ("html_bytes", "BIGINT"),
        ("parser_version", "VARCHAR"), ("dei_conflict", "BOOLEAN"),
    ],
    "context": [
        ("accession", "VARCHAR"), ("context_id", "VARCHAR"), ("entity_scheme", "VARCHAR"),
        ("entity_identifier", "VARCHAR"), ("period_type", "VARCHAR"), ("instant_date", "DATE"),
        ("start_date", "DATE"), ("end_date", "DATE"), ("member_count", "INTEGER"),
    ],
    "context_member": [
        ("accession", "VARCHAR"), ("context_id", "VARCHAR"), ("member_index", "INTEGER"),
        ("axis", "VARCHAR"), ("member_kind", "VARCHAR"), ("member", "VARCHAR"),
        ("typed_element", "VARCHAR"), ("container", "VARCHAR"),
    ],
    "unit": [
        ("accession", "VARCHAR"), ("unit_id", "VARCHAR"), ("numerator", "VARCHAR"),
        ("denominator", "VARCHAR"),
    ],
    "tagged_fact": [
        ("accession", "VARCHAR"), ("fact_id", "VARCHAR"), ("fact_index", "INTEGER"),
        ("id_is_synthetic", "BOOLEAN"), ("concept", "VARCHAR"), ("concept_namespace", "VARCHAR"),
        ("concept_local", "VARCHAR"), ("context_id", "VARCHAR"), ("unit_id", "VARCHAR"),
        ("value_text", "VARCHAR"), ("value_numeric", "DECIMAL(38,10)"), ("decimals", "VARCHAR"),
        ("precision", "VARCHAR"), ("is_nil", "BOOLEAN"), ("value_length", "INTEGER"),
        ("value_sha256", "VARCHAR"), ("value_truncated", "BOOLEAN"),
    ],
    "document_row": [
        ("accession", "VARCHAR"), ("row_index", "INTEGER"), ("table_index", "INTEGER"),
        ("row_in_table", "INTEGER"), ("cell_count", "INTEGER"), ("cells", "VARCHAR[]"),
        ("cell_colspans", "INTEGER[]"), ("cell_rowspans", "INTEGER[]"),
        ("fact_count", "INTEGER"),
    ],
    "fact_placement": [
        ("accession", "VARCHAR"), ("fact_id", "VARCHAR"), ("placement_index", "INTEGER"),
        ("ix_element", "VARCHAR"), ("concept", "VARCHAR"), ("context_id", "VARCHAR"),
        ("row_index", "INTEGER"), ("cell_index", "INTEGER"), ("displayed_text", "VARCHAR"),
        ("scale", "VARCHAR"), ("sign", "VARCHAR"), ("format", "VARCHAR"), ("in_hidden", "BOOLEAN"),
        ("shown_row_index", "INTEGER"), ("shown_cell_index", "INTEGER"),
    ],
    "footnote": [
        ("accession", "VARCHAR"), ("footnote_id", "VARCHAR"), ("text", "VARCHAR"),
        ("text_length", "INTEGER"), ("text_sha256", "VARCHAR"),
    ],
    "fact_footnote": [
        ("accession", "VARCHAR"), ("fact_id", "VARCHAR"), ("footnote_id", "VARCHAR"),
    ],
}

PRIMARY_KEYS = {
    "filing": ["accession"],
    "context": ["accession", "context_id"],
    "context_member": ["accession", "context_id", "axis"],
    "unit": ["accession", "unit_id"],
    "tagged_fact": ["accession", "fact_id"],
    "document_row": ["accession", "row_index"],
    "fact_placement": ["accession", "fact_id"],
    "footnote": ["accession", "footnote_id"],
    "fact_footnote": ["accession", "fact_id", "footnote_id"],
}


class InputChanged(Exception):
    """Same accession, different input hash: the raw cache changed."""


def describe_file(path, root, kind):
    """Inputs entries for one raw file: {kind_file, kind_sha256, kind_bytes}. path None gives nulls."""
    if path is None:
        return {f"{kind}_file": None, f"{kind}_sha256": None, f"{kind}_bytes": None}
    path = Path(path)
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return {
        f"{kind}_file": path.relative_to(root).as_posix(),
        f"{kind}_sha256": h.hexdigest(),
        f"{kind}_bytes": path.stat().st_size,
    }


_US, _RS = b"\x1f", b"\x1e"


def _enc(v):
    """Explicit text encoding of one value for the content hash (no dependence on repr())."""
    if v is None:
        return "\\N"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, Decimal):
        if v.is_zero():
            return "0"
        return format(v.normalize(), "f")
    if isinstance(v, datetime.datetime):
        raise TypeError("datetime is not an expected column type")
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        is_text = all(isinstance(x, str) for x in v)
        is_int = all(isinstance(x, int) and not isinstance(x, bool) for x in v)
        if not (is_text or is_int):
            raise TypeError("list values must be all text or all integers")
        return json.dumps(list(v), separators=(",", ":"), ensure_ascii=False)
    raise TypeError(f"cannot hash value of type {type(v).__name__}")


def _row_line(row):
    """Values joined by 0x1F, row ended by 0x1E, UTF-8."""
    return _US.join(_enc(v).encode("utf-8") for v in row) + _RS


def content_hash(rows):
    h = hashlib.sha256()
    for r in rows:
        h.update(_row_line(r))
    return h.hexdigest()


def build_rows(cik, accession, tables, inputs):
    """All nine tables as lists of tuples in primary-key order, plus primary-key duplicate counts."""
    dei = (tables.get("filing_dei") or [(None,) * 6 + (False,)])[0]
    filing = (
        accession, cik, dei[0], dei[1], dei[2], dei[3], dei[4], dei[5],
        inputs["instance_file"], inputs["instance_sha256"], inputs["instance_bytes"],
        inputs.get("html_file"), inputs.get("html_sha256"), inputs.get("html_bytes"),
        PARSER_VERSION, dei[6],
    )
    out, dups = {}, {}
    for name, cols in TABLES.items():
        rows = [filing] if name == "filing" else list(tables.get(name, []))
        names = [c for c, _ in cols]
        idx = [names.index(c) for c in PRIMARY_KEYS[name]]
        rows.sort(key=lambda r: tuple(r[i] for i in idx))
        keys = [tuple(r[i] for i in idx) for r in rows]
        dups[name] = sum(1 for a, b in zip(keys, keys[1:]) if a == b)
        out[name] = rows
    return out, dups


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def _write_parquet(con, name, rows, path):
    cols = TABLES[name]
    con.execute(f'DROP TABLE IF EXISTS "{name}"')
    con.execute(f'CREATE TABLE "{name}" (' + ", ".join(f'"{c}" {t}' for c, t in cols) + ")")
    if rows:
        fd, tmp = tempfile.mkstemp(suffix=".ndjson", prefix=f"{name}_", dir=str(Path(path).parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                names = [c for c, _ in cols]
                for r in rows:
                    fh.write(json.dumps(dict(zip(names, r)), default=_json_default, ensure_ascii=True))
                    fh.write("\n")
            spec = ", ".join(f"'{c}': '{t}'" for c, t in cols)
            con.execute(
                f'INSERT INTO "{name}" SELECT * FROM read_json(\'{Path(tmp).as_posix()}\', '
                f"format='newline_delimited', columns={{{spec}}}, maximum_object_size=268435456, "
                "hive_partitioning=false)")
        finally:
            os.remove(tmp)
    con.execute(f'COPY "{name}" TO \'{Path(path).as_posix()}\' (FORMAT PARQUET)')
    con.execute(f'DROP TABLE "{name}"')


def read_parquet_rows(path, name):
    """Rows of one Parquet file as tuples, in file order."""
    cols = ", ".join(f'"{c}"' for c, _ in TABLES[name])
    con = duckdb.connect()
    try:
        cur = con.execute(f"SELECT {cols} FROM read_parquet('{Path(path).as_posix()}', hive_partitioning=false)")
        while True:
            chunk = cur.fetchmany(50000)
            if not chunk:
                break
            yield from chunk
    finally:
        con.close()


def _manifest_path(folder):
    return folder / "_manifest.json"


def _read_manifest(folder):
    p = _manifest_path(folder)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def folder_for(out_root, cik, accession):
    return Path(out_root) / f"cik={cik}" / f"accession={accession}"


def decide(out_root, cik, accession, inputs, reparse=False):
    """'write', 'skip' or 'skip_version'. Raises InputChanged (spec write rules 2-4)."""
    folder = folder_for(out_root, cik, accession)
    m = _read_manifest(folder)
    if m is None:
        return "write"
    old = m.get("inputs", {})
    for kind in ("instance", "html"):
        if old.get(f"{kind}_sha256") != inputs.get(f"{kind}_sha256"):
            if reparse:
                return "write"
            raise InputChanged(
                f"{accession}: input hash changed for {inputs.get(kind + '_file') or old.get(kind + '_file')} "
                "(raw cache changed; a person decides; --reparse overrides)")
    if reparse:
        return "write"
    if m.get("parser_version") != PARSER_VERSION:
        print(f"WARNING: {accession} was written by parser version {m.get('parser_version')}, "
              f"current is {PARSER_VERSION}; skipped (use --reparse)")
        return "skip_version"
    return "skip"


def staging_root(out_root):
    """Sibling of the output folder, so temporary folders never match the readers' glob under out_root."""
    return Path(out_root).parent / "_filed_staging"


def sweep_staging(out_root):
    """Remove everything left in the staging folder by an earlier (crashed) run."""
    st = staging_root(out_root)
    if st.exists():
        for p in st.iterdir():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except OSError:
                    pass


def write_filing(out_root, cik, accession, tables, inputs, reparse=False):
    """Write one filing folder atomically. Returns the manifest dict with a non-persisted 'status'."""
    action = decide(out_root, cik, accession, inputs, reparse)
    final = folder_for(out_root, cik, accession)
    if action != "write":
        m = _read_manifest(final)
        m["status"] = "skipped" if action == "skip" else "skipped_version"
        return m
    rows, dups = build_rows(cik, accession, tables, inputs)
    stats = dict(tables.get("stats", []))
    stats["dei_conflict"] = int(rows["filing"][0][-1])
    manifest = {
        "parser_version": PARSER_VERSION,
        "cik": cik,
        "accession": accession,
        "inputs": {k: inputs.get(k) for k in (
            "instance_file", "instance_sha256", "instance_bytes",
            "html_file", "html_sha256", "html_bytes")},
        "tables": {n: {"rows": len(r), "content_hash": content_hash(r)} for n, r in rows.items()},
        "pk_duplicates": dups,
        "stats": stats,
        "html_parser": tables.get("html_parser"),
        "written_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    parent = final.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = staging_root(out_root)
    staging.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="_tmp_", dir=str(staging)))
    old = None
    try:
        con = duckdb.connect()
        try:
            for name in TABLES:
                _write_parquet(con, name, rows[name], tmp / f"{name}.parquet")
        finally:
            con.close()
        _manifest_path(tmp).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        if final.exists():
            old = Path(tempfile.mkdtemp(prefix="_old_", dir=str(staging)))
            os.rmdir(old)
            os.rename(final, old)
        os.rename(tmp, final)
    except BaseException:
        if old is not None and old.exists() and not final.exists():
            os.rename(old, final)
            old = None
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    manifest["status"] = "written"
    return manifest


def verify_filing(out_root, cik, accession, tables, inputs):
    """Compare a fresh parse to the manifest and to the Parquet files. Writes nothing. Returns problems."""
    folder = folder_for(out_root, cik, accession)
    m = _read_manifest(folder)
    if m is None:
        return [f"{accession}: no manifest"]
    problems = []
    if m.get("parser_version") != PARSER_VERSION:
        problems.append(f"parser_version {m.get('parser_version')} != {PARSER_VERSION}")
    for kind in ("instance", "html"):
        if m["inputs"].get(f"{kind}_sha256") != inputs.get(f"{kind}_sha256"):
            problems.append(f"{kind} input hash differs from manifest")
    rows, _ = build_rows(cik, accession, tables, inputs)
    for name in TABLES:
        mt = m["tables"].get(name)
        fresh = (len(rows[name]), content_hash(rows[name]))
        if mt is None or (mt["rows"], mt["content_hash"]) != fresh:
            problems.append(f"{name}: fresh parse differs from manifest")
        p = folder / f"{name}.parquet"
        if not p.exists():
            problems.append(f"{name}: parquet file missing")
            continue
        h = hashlib.sha256()
        n = 0
        for r in read_parquet_rows(p, name):
            h.update(_row_line(r))
            n += 1
        if mt is not None and (n, h.hexdigest()) != (mt["rows"], mt["content_hash"]):
            problems.append(f"{name}: parquet file differs from manifest ({n} rows)")
    return problems
