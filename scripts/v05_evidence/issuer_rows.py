"""Read-only: published and source rows for one fund-quarter whose identifier contains a phrase, with the fields that say where values came from.

    python scripts/v05_evidence/issuer_rows.py <label> <cik> <quarter> "<phrase>"
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik, quarter, phrase = sys.argv[1], sys.argv[2].zfill(10), sys.argv[3], sys.argv[4]
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
print("published: fv | cost | principal | units | category | class | record class | context | cost source | id | facts")
for r in con.execute(f"""SELECT fair_value, cost, principal_amount, shares_held, asset_category, index_classification, accounting_record_class, src_context_id, cost_source,
        CAST(bdc_investment_identifier AS VARCHAR)[:90], regexp_replace(CAST(src_facts AS VARCHAR), ',?"_financial_units".*', '}}')[:120]
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
      AND contains(lower(CAST(bdc_investment_identifier AS VARCHAR)), lower(?)) ORDER BY 10""", [cik, quarter, phrase]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("source (current period): fv | cost | principal | units | context | id | facts")
for r in con.execute(f"""SELECT fair_value, cost, principal_amount, shares_held, src_context_id, CAST(investment_identifier AS VARCHAR)[:90], CAST(src_facts AS VARCHAR)[:120]
    FROM read_parquet('{S}/bdc_holdings.parquet') WHERE lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
      AND CAST(period AS VARCHAR)[:10] = ? AND contains(lower(CAST(investment_identifier AS VARCHAR)), lower(?)) ORDER BY 6""", [cik, quarter, quarter, phrase]).fetchall():
    print("   " + " | ".join(str(v) for v in r))
