"""Read-only: B01 (position context with no fair value) rows for one fund: by quarter, with what the context does carry."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
f = (REPO / "scratch/fund_sandbox" / label / "output/oracle/check_failures.csv").as_posix()
con = duckdb.connect()
base = f"FROM read_csv('{f}', header=true, all_varchar=true) WHERE check_id = 'B01' AND lpad(regexp_replace(cik,'[^0-9]','','g'),10,'0') = '{cik}' AND period = report_date"
print("quarter | status | rows | named revolver/delayed draw | with principal | with cost | with units")
for r in con.execute(f"""SELECT report_date[:10], status, count(*), count(*) FILTER (WHERE regexp_matches(lower(raw_investment_identifier), 'revolv|delayed draw')),
        count(nullif(source_principal_amount,'')), count(nullif(source_cost,'')), count(nullif(source_shares_held,'')) {base} GROUP BY 1,2 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("samples: id | principal | cost | units")
for r in con.execute(f"SELECT raw_investment_identifier[:130], source_principal_amount, source_cost, source_shares_held {base} ORDER BY report_date DESC LIMIT 8").fetchall():
    print("   " + " | ".join(str(v) for v in r))
