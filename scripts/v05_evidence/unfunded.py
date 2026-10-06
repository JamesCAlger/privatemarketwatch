"""Read-only: shape of the rows behind X06 (principal over 10x fair value), C107 (negative cost) and C103 (negative fair value)."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(bdc_investment_identifier AS VARCHAR) AS id, instrument_description AS instr,
        TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS cost, TRY_CAST(principal_amount_usd AS DOUBLE) AS par_usd, TRY_CAST(principal_amount AS DOUBLE) AS par,
        regexp_matches(lower(CAST(bdc_investment_identifier AS VARCHAR)), 'revolv|delayed draw|ddtl|unfunded|commitment') AS named_commit
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE accounting_record_class <> 'underlying_schedule'""")
print("X06 (principal usd over 10x |fv|): fund | rows | named revolver/delayed draw | fair value at or below zero or under 2 pct of principal | median fv/principal | sum fv $M")
for r in con.execute("""SELECT cik, count(*), count(*) FILTER (WHERE named_commit), count(*) FILTER (WHERE fv <= 0 OR abs(fv) < 0.02*par_usd), round(median(fv/par_usd),4), round(sum(fv)/1e6,1)
    FROM h WHERE par_usd > 10*abs(fv) AND par_usd > 0 GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("C107 (negative cost): fund | rows | named revolver/delayed draw | fair value also at or below zero | no principal or principal over 10x |fv| | sum cost $M | largest negative cost $M")
for r in con.execute("""SELECT cik, count(*), count(*) FILTER (WHERE named_commit), count(*) FILTER (WHERE fv <= 0), count(*) FILTER (WHERE par IS NULL OR par_usd > 10*abs(fv)),
        round(sum(cost)/1e6,1), round(min(cost)/1e6,2) FROM h WHERE cost < 0 GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("C103 shape (negative fv, cost not negative): fund | rows | cost exactly zero | no principal | named | sum fv $M | most negative $M")
for r in con.execute("""SELECT cik, count(*), count(*) FILTER (WHERE cost = 0), count(*) FILTER (WHERE par IS NULL), count(*) FILTER (WHERE named_commit), round(sum(fv)/1e6,2), round(min(fv)/1e6,2)
    FROM h WHERE fv < 0 AND NOT coalesce(cost < 0, false) GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
