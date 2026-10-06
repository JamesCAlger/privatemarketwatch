"""Read-only: published rows of a fund whose values were merged from several contexts with a conflict or a fill."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
for r in duckdb.connect().execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], CAST(bdc_investment_identifier AS VARCHAR)[:90], round(TRY_CAST(fair_value AS DOUBLE)/1e6,2),
        src_context_count, src_conflict_fields, src_filled_fields, CAST(src_facts AS VARCHAR)[:260]
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ?
      AND (nullif(trim(coalesce(src_conflict_fields,'')),'') IS NOT NULL OR nullif(trim(coalesce(src_filled_fields,'')),'') IS NOT NULL) ORDER BY 1, 3 DESC LIMIT 20""", [cik]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
