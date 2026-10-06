"""Read-only: end-of-run summary for a sandbox: published-versus-filed match by fund, and credit rows with a published rate.

    python scripts/v05_evidence/summary.py <label>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d, TRY_CAST(fair_value AS DOUBLE) AS fv,
        asset_class, asset_category, TRY_CAST(interest_rate AS DOUBLE) AS rate, CAST(src_transforms AS VARCHAR) AS tr
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE coalesce(accounting_record_class,'') <> 'underlying_schedule' AND CAST(report_date AS VARCHAR) >= '2022'""")
con.execute(f"""CREATE TEMP TABLE ff AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d,
        max(TRY_CAST(investments_at_fair_value AS DOUBLE)) AS filed FROM read_csv_auto('{S}/fund_financials.csv', sample_size=-1) WHERE source = 'companyfacts' GROUP BY 1,2""")
print("fund | quarters | within 0.5M of filed (cash rows excluded) | credit rows | with a published rate | from the PIK tag")
for r in con.execute("""WITH q AS (SELECT cik, d, sum(fv) FILTER (WHERE coalesce(asset_category,'') <> 'CASH') AS pub FROM h GROUP BY 1,2)
    SELECT q.cik, count(*), count(*) FILTER (WHERE abs(q.pub - ff.filed) <= 5e5),
        (SELECT count(*) FROM h WHERE h.cik = q.cik AND asset_class = 'PRIVATE_CREDIT'),
        (SELECT count(*) FROM h WHERE h.cik = q.cik AND asset_class = 'PRIVATE_CREDIT' AND rate IS NOT NULL),
        (SELECT count(*) FROM h WHERE h.cik = q.cik AND contains(coalesce(tr,''), 'interest_rate:pik_only'))
    FROM q LEFT JOIN ff USING (cik, d) GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
