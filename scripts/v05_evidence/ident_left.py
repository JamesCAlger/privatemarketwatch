"""Read-only: what still fails the percent identity and the income identity in a sandbox."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE ff AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d, *
    EXCLUDE (cik, report_date) FROM read_csv_auto('{S}/fund_financials.csv', sample_size=-1) WHERE source = 'companyfacts'""")
con.execute(f"""CREATE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d,
        TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(pct_of_net_assets AS DOUBLE) AS p, CAST(bdc_investment_identifier AS VARCHAR) AS id
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE coalesce(accounting_record_class,'') <> 'underlying_schedule' AND bdc_dimensions_raw IS NOT NULL""")
print("percent identity: fund | quarter | rows with pct | failing | filed net assets $M | implied net assets (median fv/pct) $M | sample")
for r in con.execute("""WITH j AS (SELECT h.*, max(TRY_CAST(ff.net_assets AS DOUBLE)) OVER (PARTITION BY h.cik, h.d) AS nav FROM h LEFT JOIN ff USING (cik, d) WHERE p > 0 AND fv <> 0),
      k AS (SELECT *, NOT (abs(fv - p/100*nav) <= 0.10*abs(fv) OR abs(p - 100*fv/nav) <= 0.06) AS bad FROM j WHERE nav > 0)
    SELECT cik, d, count(*), count(*) FILTER (WHERE bad), round(max(nav)/1e6), round(median(fv/(p/100)) FILTER (WHERE p >= 0.3)/1e6),
        arg_max(id[:50] || ' fv=' || CAST(fv AS VARCHAR) || ' pct=' || CAST(p AS VARCHAR), abs(fv)) FILTER (WHERE bad)
    FROM k GROUP BY 1,2 HAVING count(*) FILTER (WHERE bad) > 0 ORDER BY 1,2""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("income identity: fund | quarter | NII | total income | total expenses | gap | gap / income")
for r in con.execute("""SELECT cik, d, TRY_CAST(net_investment_income AS DOUBLE), TRY_CAST(total_investment_income AS DOUBLE), TRY_CAST(total_expenses AS DOUBLE),
        TRY_CAST(net_investment_income AS DOUBLE) - (TRY_CAST(total_investment_income AS DOUBLE) - TRY_CAST(total_expenses AS DOUBLE)),
        round((TRY_CAST(net_investment_income AS DOUBLE) - (TRY_CAST(total_investment_income AS DOUBLE) - TRY_CAST(total_expenses AS DOUBLE))) / nullif(TRY_CAST(total_investment_income AS DOUBLE),0), 3)
    FROM ff WHERE d >= '2022' AND abs(TRY_CAST(net_investment_income AS DOUBLE) - (TRY_CAST(total_investment_income AS DOUBLE) - TRY_CAST(total_expenses AS DOUBLE))) > 0.05*abs(TRY_CAST(total_investment_income AS DOUBLE)) ORDER BY 1,2""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
