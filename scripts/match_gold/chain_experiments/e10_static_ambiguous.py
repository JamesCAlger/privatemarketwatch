"""E10: size of the static-ambiguous group (rows whose block shares name_key, maturity,
subtype and EXACT spread with >=1 other row in the same CIK-quarter) and how often the
production chaining pairs them against FV rank order across adjacent quarters.

Read-only. Cohort BDC rows only.
"""
import json
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from pipeline.position_matching import (  # noqa: E402
    _inst_subtype_sql, _name_key_sql, _next_quarter_sql, _quarter_label_sql)

HOLD = REPO / "data/output/private_markets_holdings.csv"
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
cik_list = ",".join(f"'{e['cik']}'" for e in json.load(open(MAN))["entries"])

con = duckdb.connect()
con.execute("CREATE MACRO avgb(x) AS AVG(CASE WHEN x THEN 1 ELSE 0 END)")
con.execute(f"""
CREATE TABLE h AS
SELECT row_id, cik, {_quarter_label_sql('report_date')} AS q, {_name_key_sql('issuer_name')} AS name_key,
       {_inst_subtype_sql("COALESCE(instrument_description, bdc_investment_identifier, '')")} AS subtype,
       TRY_CAST(maturity_date AS DATE) AS mat, TRY_CAST(basis_spread AS DOUBLE) AS spread,
       TRY_CAST(principal_amount AS DOUBLE) AS pa, TRY_CAST(fair_value AS DOUBLE) AS fv,
       TRY_CAST(cost AS DOUBLE) AS cost, position_id
FROM read_csv_auto('{HOLD.as_posix()}', all_varchar=true, sample_size=-1)
WHERE LOWER(source)='bdc' AND cik IN ({cik_list}) AND issuer_name IS NOT NULL AND issuer_name <> ''""")

con.execute("""
CREATE TABLE b AS
SELECT *, COUNT(*) OVER (PARTITION BY cik, q, name_key, mat, subtype, spread) AS n_static,
          COUNT(*) OVER (PARTITION BY cik, q, name_key, mat, subtype, spread, pa) AS n_static_pa,
          COUNT(*) OVER (PARTITION BY cik, q, name_key, mat, subtype, spread, pa, cost, fv) AS n_all
FROM h""")

def show(t, sql):
    print("\n==", t); r = con.execute(sql); print(" | ".join(d[0] for d in r.description))
    for row in r.fetchall():
        print(" | ".join("" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x)) for x in row))

show("E10a: static-ambiguous group size (cohort, all quarters / latest quarter)", """
SELECT scope, COUNT(*) AS rows,
  SUM(n_static>1) AS static_amb_rows, ROUND(avgb(n_static>1),3) AS share,
  ROUND(SUM(CASE WHEN n_static>1 THEN fv END)/1e9,1) AS fv_busd, ROUND(SUM(CASE WHEN n_static>1 THEN fv END)/SUM(fv),3) AS fv_share,
  SUM(n_static>1 AND n_static_pa>1) AS still_amb_after_principal,
  SUM(n_all>1) AS identical_all_fields
FROM (SELECT 'all_quarters' AS scope, * FROM b UNION ALL SELECT 'latest_quarter', * FROM b WHERE q=(SELECT MAX(q) FROM b))
GROUP BY 1 ORDER BY 1""")

show("E10b: block-size distribution among static-ambiguous rows (all quarters)", """
SELECT CASE WHEN n_static=2 THEN '2' WHEN n_static<=4 THEN '3-4' WHEN n_static<=9 THEN '5-9' ELSE '10+' END AS block_size,
  COUNT(*) AS rows, ROUND(COUNT(*)*1.0/(SELECT COUNT(*) FROM b WHERE n_static>1),3) AS share
FROM b WHERE n_static>1 GROUP BY 1 ORDER BY MIN(n_static)""")

# Adjacent-quarter permutation blocks: same static key, both sides have the same n>=2,
# and the production chain pairs every begin row to an end row inside the block.
con.execute(f"""
CREATE TABLE pairs AS
SELECT a.cik, a.q, a.name_key, a.mat, a.subtype, a.spread, a.row_id AS a_row, e.row_id AS e_row,
       a.fv AS a_fv, e.fv AS e_fv, a.pa AS a_pa, e.pa AS e_pa, a.cost AS a_cost, e.cost AS e_cost, a.n_static
FROM b a JOIN b e ON e.cik=a.cik AND e.q={_next_quarter_sql('a.q')} AND e.position_id=a.position_id
  AND e.name_key=a.name_key AND e.mat IS NOT DISTINCT FROM a.mat AND e.subtype IS NOT DISTINCT FROM a.subtype
  AND e.spread IS NOT DISTINCT FROM a.spread
WHERE a.n_static>1 AND a.fv>0 AND e.fv>0""")
con.execute("""
CREATE TABLE blocks AS
SELECT cik, q, name_key, mat, subtype, spread, COUNT(*) AS n_pairs, MAX(n_static) AS n_static
FROM pairs GROUP BY 1,2,3,4,5,6 HAVING COUNT(*)>=2""")
con.execute("""
CREATE TABLE ranked AS
SELECT p.*, RANK() OVER (PARTITION BY p.cik,p.q,p.name_key,p.mat,p.subtype,p.spread ORDER BY p.a_fv) AS a_rank,
            RANK() OVER (PARTITION BY p.cik,p.q,p.name_key,p.mat,p.subtype,p.spread ORDER BY p.e_fv) AS e_rank,
            RANK() OVER (PARTITION BY p.cik,p.q,p.name_key,p.mat,p.subtype,p.spread ORDER BY p.a_pa) AS a_rank_pa,
            RANK() OVER (PARTITION BY p.cik,p.q,p.name_key,p.mat,p.subtype,p.spread ORDER BY p.e_pa) AS e_rank_pa
FROM pairs p JOIN blocks USING (cik, q, name_key, mat, subtype, spread)""")
show("E10c: production pairings inside fully-chained static-ambiguous blocks vs rank order", """
SELECT COUNT(*) AS chained_pairs, COUNT(DISTINCT (cik,q,name_key,mat,subtype,spread)) AS blocks,
  SUM(a_rank<>e_rank) AS fv_rank_violations, ROUND(avgb(a_rank<>e_rank),3) AS fv_violation_share,
  SUM(a_rank_pa<>e_rank_pa) AS pa_rank_violations, ROUND(avgb(a_rank_pa<>e_rank_pa),3) AS pa_violation_share,
  SUM(a_rank<>e_rank AND a_rank_pa=e_rank_pa) AS fv_viol_but_pa_ok
FROM ranked""")
show("E10d: how far apart are the FV-based returns under the production pairing vs rank pairing (violating blocks)", """
WITH v AS (SELECT cik,q,name_key,mat,subtype,spread FROM ranked GROUP BY 1,2,3,4,5,6 HAVING SUM(a_rank<>e_rank)>0),
     prod AS (SELECT r.cik,r.q,r.name_key,r.mat,r.subtype,r.spread, STDDEV_POP(LN(e_fv/a_fv)) AS sd_prod FROM ranked r JOIN v USING (cik,q,name_key,mat,subtype,spread) GROUP BY 1,2,3,4,5,6),
     rk AS (SELECT x.cik,x.q,x.name_key,x.mat,x.subtype,x.spread, STDDEV_POP(LN(y.e_fv/x.a_fv)) AS sd_rank
            FROM ranked x JOIN ranked y ON x.cik=y.cik AND x.q=y.q AND x.name_key=y.name_key AND x.mat IS NOT DISTINCT FROM y.mat
              AND x.subtype IS NOT DISTINCT FROM y.subtype AND x.spread IS NOT DISTINCT FROM y.spread AND x.a_rank=y.e_rank
            GROUP BY 1,2,3,4,5,6)
SELECT COUNT(*) AS violating_blocks, ROUND(MEDIAN(sd_prod),3) AS median_return_dispersion_prod,
       ROUND(MEDIAN(sd_rank),3) AS median_return_dispersion_rank
FROM prod JOIN rk USING (cik,q,name_key,mat,subtype,spread)""")
