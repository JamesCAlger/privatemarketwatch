"""Verify Parquet companions faithfully persist their CSV counterparts.

For each phase-1 contract artifact (pipeline.output_schemas.OUTPUT_SCHEMAS)
where both files exist, compares the Parquet against CAST(CSV-as-VARCHAR)
using the same cast expressions the companion writer used:

- row counts,
- per-column non-null counts (localizes any divergence to a column),
- order-insensitive whole-row hash-sum (multiset equality of full rows).

Any mismatch is a parity failure. Exit 0 = all clean, 1 = failures, 2 = no
artifact had both files. Report: data/output/parquet_csv_parity.json.

Usage:
    python scripts/parquet_csv_parity.py            # all contract artifacts
    python scripts/parquet_csv_parity.py bdc_holdings.csv position_matches.csv
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import OUTPUT_DIR  # noqa: E402
from pipeline.output_schemas import OUTPUT_SCHEMAS  # noqa: E402
from pipeline.utils import _contract_cast_expr  # noqa: E402

REPORT_FILE = OUTPUT_DIR / "parquet_csv_parity.json"


def _q(path: Path) -> str:
    return str(path).replace("\\", "/")


def check_artifact(con: duckdb.DuckDBPyConnection, name: str) -> dict:
    csv_file = OUTPUT_DIR / name
    pq_file = csv_file.with_suffix(".parquet")
    if not csv_file.exists() or not pq_file.exists():
        return {"status": "skipped_missing", "csv": csv_file.exists(),
                "parquet": pq_file.exists()}

    contract = OUTPUT_SCHEMAS[name]
    cols = list(contract.keys())
    select = ", ".join(_contract_cast_expr(c, t) for c, t in contract.items())
    quoted = ", ".join('"' + c.replace('"', '""') + '"' for c in cols)

    con.execute(
        f"CREATE OR REPLACE TEMP VIEW csv_side AS "
        f"SELECT {select} FROM read_csv_auto('{_q(csv_file)}', header=true, "
        f"all_varchar=true)"
    )
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW pq_side AS "
        f"SELECT {quoted} FROM read_parquet('{_q(pq_file)}')"
    )

    agg = (
        "SELECT COUNT(*) AS n, "
        + ", ".join(
            f'COUNT("{c}") AS nn_{i}' for i, c in enumerate(cols)
        )
        + ", SUM(CAST(hash(ROW({})) AS HUGEINT)) AS rowhash".format(quoted)
    )
    csv_stats = con.execute(agg + " FROM csv_side").fetchone()
    pq_stats = con.execute(agg + " FROM pq_side").fetchone()

    issues = []
    if csv_stats[0] != pq_stats[0]:
        issues.append(f"row count: csv={csv_stats[0]} parquet={pq_stats[0]}")
    for i, c in enumerate(cols):
        if csv_stats[1 + i] != pq_stats[1 + i]:
            issues.append(
                f"non-null count for {c}: csv={csv_stats[1 + i]} "
                f"parquet={pq_stats[1 + i]}"
            )
    if csv_stats[-1] != pq_stats[-1]:
        issues.append("whole-row hash-sum differs (value-level divergence)")

    return {
        "status": "FAIL" if issues else "PASS",
        "rows": pq_stats[0],
        "columns": len(cols),
        "issues": issues,
    }


def main(argv: list[str]) -> int:
    names = argv or sorted(OUTPUT_SCHEMAS)
    unknown = [n for n in names if n not in OUTPUT_SCHEMAS]
    if unknown:
        print(f"Unknown artifacts (no contract): {unknown}")
        return 2

    con = duckdb.connect()
    report = {}
    for name in names:
        print(f"checking {name} ...", flush=True)
        report[name] = check_artifact(con, name)
        r = report[name]
        detail = "; ".join(r.get("issues", [])) or f"{r.get('rows', '-')} rows"
        print(f"  {r['status']}: {detail}")
    con.close()

    REPORT_FILE.write_text(json.dumps(report, indent=2, default=str),
                           encoding="utf-8")
    print(f"Report: {REPORT_FILE}")

    checked = [r for r in report.values() if r["status"] in ("PASS", "FAIL")]
    failed = [n for n, r in report.items() if r["status"] == "FAIL"]
    if not checked:
        print("No artifact had both CSV and Parquet present.")
        return 2
    if failed:
        print(f"PARITY FAILURES: {failed}")
        return 1
    print(f"All {len(checked)} checked artifacts PASS "
          f"({len(report) - len(checked)} skipped, missing a side).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
