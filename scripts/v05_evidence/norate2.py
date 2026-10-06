"""Read-only: credit rows with neither a published rate nor a spread (X02), by fund: was anything filed, and what are they."""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d,
        TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(principal_amount AS DOUBLE) AS par, TRY_CAST(interest_rate_reported AS DOUBLE) AS filed,
        TRY_CAST(pik_rate AS DOUBLE) AS pik, asset_category, index_classification, CAST(bdc_investment_identifier AS VARCHAR) AS id,
        coalesce(TRY_CAST(nonaccrual_footnote AS BOOLEAN), false) OR coalesce(TRY_CAST(nonaccrual_dimension AS BOOLEAN), false) AS nonaccrual,
        regexp_matches(lower(CAST(bdc_investment_identifier AS VARCHAR)), 'revolv|delayed draw|unfunded|commitment') AS named_commit
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE asset_class = 'PRIVATE_CREDIT' AND accounting_record_class <> 'underlying_schedule'
      AND nullif(trim(CAST(interest_rate AS VARCHAR)),'') IS NULL AND nullif(trim(CAST(basis_spread AS VARCHAR)),'') IS NULL""")
print("fund | rows | quarters | a rate was filed (withheld) | fair value at or below zero | named revolver or delayed draw | fund interest or equity-like class | non-accrual | PIK rate only | none of these | $M none of these")
for r in con.execute("""SELECT cik, count(*), count(DISTINCT d), count(filed), count(*) FILTER (WHERE coalesce(fv,0) <= 0), count(*) FILTER (WHERE named_commit),
        count(*) FILTER (WHERE index_classification <> 'DIRECT_LENDING' OR asset_category IN ('FUND','EQUITY_COMMON','EQUITY_PREFERRED','OTHER')),
        count(*) FILTER (WHERE nonaccrual), count(*) FILTER (WHERE pik > 0),
        count(*) FILTER (WHERE filed IS NULL AND coalesce(fv,0) > 0 AND NOT named_commit AND index_classification = 'DIRECT_LENDING' AND asset_category = 'LOAN' AND NOT nonaccrual AND NOT coalesce(pik > 0, false)),
        round(coalesce(sum(fv) FILTER (WHERE filed IS NULL AND coalesce(fv,0) > 0 AND NOT named_commit AND index_classification = 'DIRECT_LENDING' AND asset_category = 'LOAN' AND NOT nonaccrual AND NOT coalesce(pik > 0, false)),0)/1e6,0)
    FROM h GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
for cik in sys.argv[2:]:
    print("== %s plain loans with value and nothing filed (largest): quarter | $M | principal | id" % cik)
    for r in con.execute("""SELECT d, round(fv/1e6,1), par, id[:100] FROM h WHERE cik = ? AND filed IS NULL AND coalesce(fv,0) > 0 AND NOT named_commit
          AND index_classification = 'DIRECT_LENDING' AND asset_category = 'LOAN' AND NOT nonaccrual AND NOT coalesce(pik > 0, false) ORDER BY fv DESC LIMIT 8""", [cik.zfill(10)]).fetchall():
        print("   " + " | ".join(str(v) for v in r))
