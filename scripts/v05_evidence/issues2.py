"""Read-only: one rule's row issues for a fund: quarter, value text, and the matching source rows' fair value."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, rule, cik = sys.argv[1], sys.argv[2], sys.argv[3].zfill(10)
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect(config={"threads": 2, "memory_limit": "3GB"})
con.execute(f"""CREATE TEMP TABLE i AS SELECT CAST(report_date AS VARCHAR)[:10] AS d, CAST(value AS VARCHAR) AS v, row_key, message
    FROM read_parquet('{S}/row_validation_issues.parquet') WHERE rule_id = ? AND lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') = ?""", [rule, cik])
con.execute(f"""CREATE TEMP TABLE s AS SELECT CAST(report_date AS VARCHAR)[:10] AS d, CAST(period AS VARCHAR)[:10] AS p, trim(CAST(investment_identifier AS VARCHAR)) AS id,
        TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(principal_amount AS DOUBLE) AS par, CAST(dimensions_raw AS VARCHAR) AS dims
    FROM read_parquet('{S}/bdc_holdings.parquet') WHERE lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') = ?""", [cik])
print("quarter | value | source rows current-period n | $M | principal | dims tail | row_key")
for r in con.execute("""SELECT i.d, i.v[:80], count(s.id), round(sum(s.fv)/1e6,2), any_value(s.par), right(any_value(s.dims), 80), any_value(i.row_key)[:40]
    FROM i LEFT JOIN s ON s.d = i.d AND s.p = i.d AND (s.id = i.v OR starts_with(s.id, i.v || ' |')) GROUP BY i.d, i.v ORDER BY 1, 2""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
