"""Read-only dry run: pair a rate-only context with the one value row of the same issuer that has no rate facts.

A pair needs: same filing and period, same issuer key (first 16 letters and digits of the identifier), exactly one
rate-only context and exactly one value row with a principal and no rate facts under that key.

    python scripts/v05_evidence/orphan_pairs.py <label> <cik>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
con.execute(f"""CREATE TEMP TABLE b AS SELECT accession_number AS acc, CAST(period AS VARCHAR)[:10] AS p, CAST(report_date AS VARCHAR)[:10] AS d,
        CAST(investment_identifier AS VARCHAR) AS id, src_context_id AS ctx, left(regexp_replace(lower(CAST(investment_identifier AS VARCHAR)), '[^a-z0-9]', '', 'g'), 16) AS k,
        TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS cost, TRY_CAST(principal_amount AS DOUBLE) AS par,
        TRY_CAST(interest_rate AS DOUBLE) AS rate, TRY_CAST(basis_spread AS DOUBLE) AS spread, TRY_CAST(pik_rate AS DOUBLE) AS pik
    FROM read_parquet('{S}/bdc_holdings.parquet') WHERE lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') = ?""", [cik])
con.execute("""CREATE TEMP TABLE pairs AS
    WITH o AS (SELECT * FROM b WHERE fv IS NULL AND cost IS NULL AND par IS NULL AND (rate IS NOT NULL OR spread IS NOT NULL OR pik IS NOT NULL)),
         t AS (SELECT * FROM b WHERE fv IS NOT NULL AND par IS NOT NULL AND rate IS NULL AND spread IS NULL AND pik IS NULL),
         oc AS (SELECT acc, p, k, count(*) AS n FROM o GROUP BY ALL), tc AS (SELECT acc, p, k, count(*) AS n FROM t GROUP BY ALL)
    SELECT o.d, o.p, o.acc, o.ctx AS octx, t.ctx AS tctx, o.rate, o.spread, o.pik, t.fv, t.par, o.id AS oid, t.id AS tid
    FROM o JOIN t USING (acc, p, k) JOIN oc USING (acc, p, k) JOIN tc USING (acc, p, k) WHERE oc.n = 1 AND tc.n = 1""")
print("pairs, current period only:", con.execute("SELECT count(*), round(sum(fv)/1e6,1) FROM pairs WHERE p = d").fetchone())
print("quarter | rate | spread | pik | fv $M | par $M | rate context: id | value context: id")
for r in con.execute("""SELECT d, rate, spread, pik, round(fv/1e6,1), round(par/1e6,1), octx || ': ' || oid[:62], tctx || ': ' || tid[:62] FROM pairs WHERE p = d ORDER BY d, tid""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
