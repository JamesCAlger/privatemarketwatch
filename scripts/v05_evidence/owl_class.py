"""Read-only: how Blue Owl 'specialty finance' and interest rows are classed in a sandbox, by wording."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
for r in duckdb.connect().execute(f"""SELECT regexp_extract(lower(CAST(bdc_investment_identifier AS VARCHAR)), '(specialty finance [a-z]+ investment|llc interest|class [a-z] units|class [a-z] interests)', 1) AS wording,
        asset_category, index_classification, asset_class, count(*), round(sum(TRY_CAST(fair_value AS DOUBLE))/1e6,0), count(TRY_CAST(principal_amount AS DOUBLE)), count(TRY_CAST(shares_held AS DOUBLE))
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '0001812554'
      AND regexp_matches(lower(CAST(bdc_investment_identifier AS VARCHAR)), 'specialty finance|llc interest|class [a-z] units|class [a-z] interests')
    GROUP BY 1,2,3,4 ORDER BY 6 DESC""").fetchall():
    print("   ", r)
