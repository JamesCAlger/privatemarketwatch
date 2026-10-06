"""Read-only: the published rows one row rule flags for a fund-quarter, with rate, class and source-fact fields.

    python scripts/v05_evidence/flagged.py <label> <rule> <cik> <quarter> [max rows]
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, rule, cik, quarter = sys.argv[1], sys.argv[2], sys.argv[3].zfill(10), sys.argv[4]
limit = int(sys.argv[5]) if len(sys.argv) > 5 else 12
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
rows = con.execute(f"""SELECT round(TRY_CAST(h.fair_value AS DOUBLE)/1e6,2) AS fv_m, TRY_CAST(h.cost AS DOUBLE) AS cost, h.interest_rate, h.interest_rate_reported AS filed,
        h.basis_spread AS spread, h.pik_rate AS pik, h.asset_category AS cat, h.index_classification AS idx, h.src_context_id AS ctx,
        CAST(h.bdc_investment_identifier AS VARCHAR)[:95] AS id, regexp_replace(CAST(h.src_facts AS VARCHAR), ',?"_financial_units".*', '}}')[:110] AS facts
    FROM read_parquet('{S}/row_validation_issues.parquet') i JOIN read_parquet('{S}/private_markets_holdings.parquet') h ON h.row_id = i.row_id
    WHERE i.rule_id = ? AND lpad(CAST(h.cik AS VARCHAR),10,'0') = ? AND CAST(h.report_date AS VARCHAR)[:10] = ?
    ORDER BY abs(TRY_CAST(h.fair_value AS DOUBLE)) DESC""", [rule, cik, quarter]).fetchall()
print("%d rows flagged; fv $M | cost | rate | filed | spread | pik | category | class | context | id | facts" % len(rows))
for r in rows[:limit]:
    print("   " + " | ".join(str(v) for v in r))
