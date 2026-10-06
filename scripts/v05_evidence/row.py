"""Read-only: every non-empty column of published and bdc_holdings rows matching a fund, quarter and identifier text."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik, quarter, needle = sys.argv[1], sys.argv[2].zfill(10), sys.argv[3], sys.argv[4]
limit = int(sys.argv[5]) if len(sys.argv) > 5 else 1
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect(config={"threads": 2, "memory_limit": "3GB"})
for name, idcol in (("private_markets_holdings", "bdc_investment_identifier"), ("bdc_holdings", "investment_identifier")):
    rows = con.execute(f"""SELECT * FROM read_parquet('{S}/{name}.parquet')
        WHERE lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
          AND contains(lower(CAST({idcol} AS VARCHAR)), lower(?)) LIMIT {limit}""", [cik, quarter, needle]).fetchdf()
    for _, row in rows.iterrows():
        print("\n== " + name)
        for col, value in row.items():
            text = str(value)
            if value is not None and text not in ("", "nan", "None", "NaT", "<NA>"):
                print("   %-34s %s" % (col, text[:400]))
