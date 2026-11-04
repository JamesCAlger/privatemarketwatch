"""Read-only: the wrapper cohort ranked by published fair value at a quarter, smallest first.

    python scripts/v05_evidence/cohort_by_size.py [quarter, default 2026-03-31]

Published basis (rows of a JV's own schedule left out), from data/output. Prints rank, CIK, name,
fair value in $M, rows, and the fund's latest quarter with holdings.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline.cohort_guard import load_cohort_ciks

quarter = sys.argv[1] if len(sys.argv) > 1 else "2026-03-31"
cohort = sorted(load_cohort_ciks())
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
