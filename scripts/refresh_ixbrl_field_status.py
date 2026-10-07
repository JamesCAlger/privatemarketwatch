"""Re-read the printed-schedule field status for named funds and splice it into the artifact.

The artifact (``bdc_ixbrl_field_status.csv``) is not rebuilt by the unified build. After a change
to how a fund's printed columns are read (for example ``reference_rate_columns`` in its wrapper),
run this for that fund, then rebuild. Rows of every other fund are kept as they are.

    set PM_OUTPUT_DIR=scratch\\fund_sandbox\\<label>\\output
    python scripts/refresh_ixbrl_field_status.py --ciks 0001812554

Refuses to write the published ``data/output`` unless ``--published`` is given.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAD = "lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0')"


def splice(existing: Path, fresh: Path, ciks: list[str], out: Path) -> dict:
    """Write ``out`` = rows of ``existing`` for other funds + all rows of ``fresh``. Returns row counts."""
    import duckdb

    def reader(path: Path) -> str:
        return "read_csv('%s', header=true, all_varchar=true, sample_size=-1)" % path.as_posix()

    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE subset AS SELECT unnest(?) AS cik", [ciks])
    columns = [r[0] for r in con.execute("DESCRIBE SELECT * FROM " + reader(existing)).fetchall()]
    new_columns = [r[0] for r in con.execute("DESCRIBE SELECT * FROM " + reader(fresh)).fetchall()]
    if set(columns) != set(new_columns):
        raise ValueError("field-status columns differ: %s" % sorted(set(columns) ^ set(new_columns)))
    outside = con.execute("SELECT count(*) FROM %s WHERE %s NOT IN (SELECT cik FROM subset)" % (reader(fresh), PAD)).fetchone()[0]
    if outside:
        raise ValueError("%d re-read rows belong to funds that were not named" % outside)
    select = ", ".join('"%s"' % c for c in columns)
    con.execute("CREATE TEMP TABLE kept AS SELECT %s FROM %s WHERE %s NOT IN (SELECT cik FROM subset)" % (select, reader(existing), PAD))
    replaced = con.execute("SELECT count(*) FROM %s WHERE %s IN (SELECT cik FROM subset)" % (reader(existing), PAD)).fetchone()[0]
    con.execute("CREATE TEMP TABLE added AS SELECT %s FROM %s" % (select, reader(fresh)))
    counts = dict(kept=con.execute("SELECT count(*) FROM kept").fetchone()[0], replaced=replaced,
                  written=con.execute("SELECT count(*) FROM added").fetchone()[0])
    con.execute("COPY (SELECT * FROM kept UNION ALL SELECT * FROM added) TO '%s' (HEADER, DELIMITER ',')" % out.as_posix())
    con.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ciks", nargs="+", required=True)
    parser.add_argument("--published", action="store_true", help="allow writing data/output")
    args = parser.parse_args(argv)
    if not os.environ.get("PM_OUTPUT_DIR") and not args.published:
        parser.error("PM_OUTPUT_DIR is not set; this would write the published data/output (use --published to allow)")
    from pipeline.bdc_xbrl_html_bridge import extract_bdc_ixbrl_field_status
    from pipeline.config import BDC_IXBRL_FIELD_STATUS_FILE
    from pipeline.utils import write_parquet_companion

    ciks = sorted({"".join(ch for ch in c if ch.isdigit()).zfill(10) for c in args.ciks})
    artifact = BDC_IXBRL_FIELD_STATUS_FILE
    if not artifact.exists():
        parser.error("no artifact to splice into: %s" % artifact)
    started = time.time()
    with tempfile.TemporaryDirectory() as folder:
        fresh = Path(folder) / "fresh.csv"
        merged = Path(folder) / "merged.csv"
        extract_bdc_ixbrl_field_status(ciks=ciks, out_file=fresh)
        counts = splice(artifact, fresh, ciks, merged)
        artifact.write_bytes(merged.read_bytes())
    write_parquet_companion(artifact)
    print("field status refreshed for %s in %.0f s: %s -> %s" % (",".join(ciks), time.time() - started, counts, artifact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
