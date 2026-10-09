"""Read-only: the wrapper cohort ranked by published fair value at a quarter, smallest first.

    python scripts/v05_evidence/cohort_by_size.py [quarter, default 2026-03-31]

Published basis (rows of a JV's own schedule left out), from data/output. Prints rank, CIK, name,
fair value in $M, rows, and the fund's latest quarter with holdings.
"""
import json
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
quarter = sys.argv[1] if len(sys.argv) > 1 else "2026-03-31"
manifest = json.loads((REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json").read_text(encoding="utf-8"))


def ciks(node):
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "cik" and isinstance(value, (str, int)):
                found.add(str(value).zfill(10))
            found |= ciks(value)
    elif isinstance(node, list):
        for value in node:
            found |= ciks(value) if isinstance(value, (dict, list)) else ({str(value).zfill(10)} if str(value).isdigit() else set())
    return found


cohort = sorted(ciks(manifest))
con = duckdb.connect()
rows = con.execute("""
    SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, any_value(entity_name) AS name,
           sum(TRY_CAST(fair_value AS DOUBLE)) FILTER (WHERE CAST(report_date AS VARCHAR)[:10] = ?) / 1e6 AS fv_m,
           count(*) FILTER (WHERE CAST(report_date AS VARCHAR)[:10] = ?) AS n,
           max(CAST(report_date AS VARCHAR)[:10]) AS latest, count(DISTINCT report_date) AS quarters
    FROM read_parquet(?) WHERE coalesce(CAST(accounting_record_class AS VARCHAR),'') <> 'underlying_schedule'
      AND lpad(CAST(cik AS VARCHAR),10,'0') IN (SELECT unnest(?)) GROUP BY 1 ORDER BY fv_m NULLS FIRST
""", [quarter, quarter, (REPO / "data/output/private_markets_holdings.parquet").as_posix(), cohort]).fetchall()
print("cohort CIKs in manifest: %d | with published holdings: %d" % (len(cohort), len(rows)))
for rank, (cik, name, fv, n, latest, quarters) in enumerate(rows, 1):
    print("%3d %s %-48s %10s %6d  latest %s  quarters %d" % (rank, cik, str(name)[:48], "-" if fv is None else "%.1f" % fv, n, latest, quarters))
