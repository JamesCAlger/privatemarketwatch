"""Read-only: evidence for pct_of_net_assets_identity (BCRED, Blue Owl) and C04 (equity rows without units)."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d, TRY_CAST(fair_value AS DOUBLE) AS fv,
        TRY_CAST(pct_of_net_assets AS DOUBLE) AS p, TRY_CAST(pct_of_net_assets_calculated AS DOUBLE) AS c, asset_category, index_classification,
        TRY_CAST(shares_held AS DOUBLE) AS sh, accounting_record_class AS cls
    FROM read_parquet('{S}/private_markets_holdings.parquet')""")
print("pct identity (reported vs fair value / net assets, 10 pct band): fund | rows with a reported pct | outside the band | of those: reported is 0.0 or 0.1 (rounding floor) | JV-schedule rows | other | median abs gap in pct points (other)")
for r in con.execute("""SELECT cik, count(*), count(*) FILTER (WHERE abs(p - c) > 0.10 * abs(c)),
        count(*) FILTER (WHERE abs(p - c) > 0.10 * abs(c) AND cls <> 'underlying_schedule' AND p <= 0.1),
        count(*) FILTER (WHERE abs(p - c) > 0.10 * abs(c) AND cls = 'underlying_schedule'),
        count(*) FILTER (WHERE abs(p - c) > 0.10 * abs(c) AND cls <> 'underlying_schedule' AND p > 0.1),
        round(median(abs(p - c)) FILTER (WHERE abs(p - c) > 0.10 * abs(c) AND cls <> 'underlying_schedule' AND p > 0.1), 3)
    FROM h WHERE p > 0 AND c IS NOT NULL AND fv <> 0 AND cik IN ('0001803498','0001812554') GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("C04: fund | equity rows | with units | share | fund-quarters under 70 pct | rows without units: zero fair value | $M without units")
for r in con.execute("""WITH e AS (SELECT * FROM h WHERE regexp_matches(lower(asset_category), 'equity|stock') AND cls <> 'underlying_schedule'),
      q AS (SELECT cik, d, avg(CASE WHEN coalesce(sh,0) <> 0 THEN 1.0 ELSE 0 END) AS s FROM e GROUP BY 1,2)
    SELECT e.cik, count(*), count(*) FILTER (WHERE coalesce(sh,0) <> 0), round(avg(CASE WHEN coalesce(sh,0) <> 0 THEN 1.0 ELSE 0 END),3),
        (SELECT count(*) FROM q WHERE q.cik = e.cik AND s < 0.7), count(*) FILTER (WHERE coalesce(sh,0) = 0 AND coalesce(fv,0) = 0),
        round(coalesce(sum(fv) FILTER (WHERE coalesce(sh,0) = 0),0)/1e6,0) FROM e GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
