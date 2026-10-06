"""Read-only: credit rows still marked coupon-unresolved, split by whether a rate was filed at all; and X01 rows."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
src = f"read_parquet('{S}/private_markets_holdings.parquet')"
print("fund | rows marked coupon unresolved | no rate filed | rate filed, PIK above it (guard) | rate filed, other | $M guard")
for r in con.execute(f"""SELECT lpad(CAST(cik AS VARCHAR),10,'0'), count(*), count(*) FILTER (WHERE TRY_CAST(interest_rate_reported AS DOUBLE) IS NULL),
        count(*) FILTER (WHERE TRY_CAST(pik_rate AS DOUBLE) > TRY_CAST(interest_rate_reported AS DOUBLE) + 0.01),
        count(*) FILTER (WHERE TRY_CAST(interest_rate_reported AS DOUBLE) IS NOT NULL AND NOT coalesce(TRY_CAST(pik_rate AS DOUBLE) > TRY_CAST(interest_rate_reported AS DOUBLE) + 0.01, false)),
        round(coalesce(sum(TRY_CAST(fair_value AS DOUBLE)) FILTER (WHERE TRY_CAST(pik_rate AS DOUBLE) > TRY_CAST(interest_rate_reported AS DOUBLE) + 0.01),0)/1e6,1)
    FROM {src} WHERE contains(coalesce(src_transforms,''), 'interest_rate:coupon_unresolved') AND accounting_record_class <> 'underlying_schedule' GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("X01 (equity row with a rate), sample: fund | quarter | id | rate | class | category")
for r in con.execute(f"""SELECT lpad(CAST(cik AS VARCHAR),10,'0'), CAST(report_date AS VARCHAR)[:10], CAST(bdc_investment_identifier AS VARCHAR)[:80], interest_rate, index_classification, asset_category
    FROM {src} WHERE asset_class = 'PRIVATE_EQUITY' AND TRY_CAST(interest_rate AS DOUBLE) > 0 AND coalesce(index_classification,'') <> 'PREFERRED_EQUITY'
    ORDER BY TRY_CAST(fair_value AS DOUBLE) DESC LIMIT 8""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
