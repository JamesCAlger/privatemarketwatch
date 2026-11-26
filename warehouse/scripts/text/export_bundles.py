"""Write the rate-column bundles of int_text_bundle to one JSON file each (text slice R phase 1, 2026-11-26).

Read-only on the warehouse: opens target/warehouse.duckdb with read_only=True and writes nothing to it.

Usage (from the repository root or from warehouse/):
  warehouse\\.venv\\Scripts\\python.exe warehouse\\scripts\\text\\export_bundles.py <out_dir> <max_rows> [--state STATE]

  out_dir    folder to write <unit_key>.json files into (created if missing). Must not be under data/ or
             warehouse/target/.
  max_rows   stop after this many bundles (a guard; bundles are taken in unit_key order).
  --state    only bundles whose worklist_state equals STATE (e.g. uncovered); default all.

Each file holds bundle_json exactly as the model built it (UTF-8, no re-formatting), so the same build gives the same
bytes. A manifest _manifest.tsv lists unit_key, worklist_state, bundle_chars and the file's sha256. Progress is ASCII.
"""
import argparse
import hashlib
import os
import sys

import duckdb

WAREHOUSE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
REPO = os.path.dirname(WAREHOUSE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir")
    parser.add_argument("max_rows", type=int)
    parser.add_argument("--state", default=None)
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    for forbidden in (os.path.join(REPO, "data"), os.path.join(WAREHOUSE, "data"), os.path.join(WAREHOUSE, "target")):
        if os.path.commonpath([out_dir, forbidden]) == forbidden:
            print("refused: out_dir is under " + forbidden)
            return 2
    os.makedirs(out_dir, exist_ok=True)

    con = duckdb.connect(os.path.join(WAREHOUSE, "target", "warehouse.duckdb"), read_only=True)
    try:
        sql = "select unit_key, worklist_state, bundle_chars, bundle_json from int_text_bundle"
        params = []
        if args.state:
            sql += " where worklist_state = ?"
            params.append(args.state)
        sql += " order by unit_key limit ?"
        params.append(args.max_rows)
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    total = 0
    manifest = ["unit_key\tworklist_state\tbundle_chars\tsha256"]
    for i, (unit_key, state, chars, body) in enumerate(rows, 1):
        data = body.encode("utf-8")
        with open(os.path.join(out_dir, unit_key + ".json"), "wb") as f:
            f.write(data)
        total += len(data)
        manifest.append("\t".join([unit_key, str(state), str(chars), hashlib.sha256(data).hexdigest()]))
        if i % 10 == 0 or i == len(rows):
            print("written %d of %d" % (i, len(rows)))
    with open(os.path.join(out_dir, "_manifest.tsv"), "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(manifest) + "\n")
    print("bundles: %d, bytes: %d, folder: %s" % (len(rows), total, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
