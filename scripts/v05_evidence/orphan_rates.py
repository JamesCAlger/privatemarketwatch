"""Read-only: for one fund, source contexts that carry rate facts and no value, beside value rows with no rate facts.

    python scripts/v05_evidence/orphan_rates.py <label> <cik> [quarter]
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE b AS SELECT CAST(report_date AS VARCHAR)[:10] AS d, CAST(investment_identifier AS VARCHAR) AS id, src_context_id AS ctx,
        TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS cost, TRY_CAST(principal_amount AS DOUBLE) AS par,
        TRY_CAST(interest_rate AS DOUBLE) AS rate, TRY_CAST(basis_spread AS DOUBLE) AS spread, TRY_CAST(pik_rate AS DOUBLE) AS pik, CAST(maturity_date AS VARCHAR) AS mat
    FROM read_parquet('{S}/bdc_holdings.parquet') WHERE lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') = ?
      AND CAST(period AS VARCHAR)[:10] = CAST(report_date AS VARCHAR)[:10]""", [cik])
print("quarter | rate-only contexts (rate/spread/pik, no value) | value loans with no rate facts, fv > 0 | $M of those")
for r in con.execute("""SELECT d, count(*) FILTER (WHERE fv IS NULL AND cost IS NULL AND (rate IS NOT NULL OR spread IS NOT NULL OR pik IS NOT NULL)),
        count(*) FILTER (WHERE fv > 0 AND rate IS NULL AND spread IS NULL AND pik IS NULL AND regexp_matches(lower(id), 'loan|note|debt')),
        round(sum(fv) FILTER (WHERE fv > 0 AND rate IS NULL AND spread IS NULL AND pik IS NULL AND regexp_matches(lower(id), 'loan|note|debt'))/1e6,1)
    FROM b GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
if len(sys.argv) > 3:
    q = sys.argv[3]
    print("rate-only: ctx | rate | spread | pik | maturity | id")
    for r in con.execute("SELECT ctx, rate, spread, pik, mat, id[:110] FROM b WHERE d = ? AND fv IS NULL AND cost IS NULL AND (rate IS NOT NULL OR spread IS NOT NULL OR pik IS NOT NULL) ORDER BY id", [q]).fetchall():
        print("   " + " | ".join(str(v) for v in r))
    print("value loans without rate facts: ctx | fv | par | maturity | id")
    for r in con.execute("SELECT ctx, fv, par, mat, id[:110] FROM b WHERE d = ? AND fv > 0 AND rate IS NULL AND spread IS NULL AND pik IS NULL AND regexp_matches(lower(id), 'loan|note|debt') ORDER BY id", [q]).fetchall():
        print("   " + " | ".join(str(v) for v in r))
