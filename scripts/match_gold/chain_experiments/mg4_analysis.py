"""mg4_contested gate analysis: per-tier precision on tier_random with tranche/borrower
sub-codes, and what the WRONG edges on the new contested tiers look like.

Usage: python mg4_analysis.py [batch_id]   (default mg4_contested)
Reads out/<batch>/gold_edges.csv (from build_gold_edges.py <batch>) + cohort holdings.
NOTE: the flag-on build's edges were sampled from a scratch flag-on run; row_ids are
production row_ids, so holdings fields join, but production position_ids differ.
"""
import json
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from pipeline.position_matching import _inst_subtype_sql, _name_key_sql, _quarter_label_sql  # noqa: E402

BATCH = sys.argv[1] if len(sys.argv) > 1 else "mg4_contested"
OUT = Path(__file__).resolve().parent / "out" / BATCH
HOLD = REPO / "data/output/private_markets_holdings.csv"
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
cik_list = ",".join(f"'{e['cik']}'" for e in json.load(open(MAN))["entries"])

con = duckdb.connect()
con.execute(f"""
CREATE TABLE h AS
SELECT row_id, cik, {_quarter_label_sql('report_date')} AS q, issuer_name, {_name_key_sql('issuer_name')} AS name_key,
       entity_id, {_inst_subtype_sql("COALESCE(instrument_description, bdc_investment_identifier, '')")} AS subtype,
       TRY_CAST(maturity_date AS DATE) AS mat, TRY_CAST(basis_spread AS DOUBLE) AS spread,
       TRY_CAST(principal_amount AS DOUBLE) AS pa, TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS cost
FROM read_csv_auto('{HOLD.as_posix()}', all_varchar=true, sample_size=-1)
WHERE LOWER(source)='bdc' AND cik IN ({cik_list})""")
con.execute(f"CREATE TABLE ge AS SELECT * FROM read_csv_auto('{(OUT/'gold_edges.csv').as_posix()}', all_varchar=true)")
con.execute("""
CREATE TABLE gx AS
SELECT ge.packet_id, ge.stratum, ge.cik, ge.edge_index, ge.verdict, ge.tier,
       b.name_key AS b_key, e.name_key AS e_key, b.entity_id AS b_ent, e.entity_id AS e_ent,
       b.issuer_name AS b_name, e.issuer_name AS e_name, b.mat AS b_mat, e.mat AS e_mat,
       b.spread AS b_spr, e.spread AS e_spr, b.pa AS b_pa, e.pa AS e_pa, b.cost AS b_cost, e.cost AS e_cost,
       b.fv AS b_fv, e.fv AS e_fv, b.subtype AS b_sub, e.subtype AS e_sub, b.row_id AS b_row
FROM ge LEFT JOIN h b ON b.row_id=ge.b_row_id LEFT JOIN h e ON e.row_id=ge.e_row_id""")
con.execute("""
CREATE TABLE gs AS SELECT *,
  CASE WHEN verdict<>'WRONG' THEN NULL
       WHEN b_key=e_key OR (b_ent IS NOT NULL AND b_ent=e_ent) THEN 'WRONG_TRANCHE' ELSE 'WRONG_BORROWER' END AS sub
FROM gx""")

def show(t, sql):
    print("\n==", t); r = con.execute(sql); print(" | ".join(d[0] for d in r.description))
    for row in r.fetchall():
        print(" | ".join("" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x)) for x in row))

n = con.execute("SELECT COUNT(*), SUM(b_row IS NULL) FROM gx").fetchone()
print(f"{BATCH}: edges={n[0]} unjoined={n[1]}")

show("per-tier precision, tier_random only, UNCERTAIN excluded, with sub-codes", """
SELECT tier, COUNT(*) AS n, SUM(verdict='CONFIRMED') AS conf, SUM(verdict='WRONG') AS wrong,
  ROUND(SUM(verdict='CONFIRMED')*1.0/COUNT(*),3) AS precision,
  SUM(sub='WRONG_TRANCHE') AS tranche, SUM(sub='WRONG_BORROWER') AS borrower
FROM gs WHERE stratum='tier_random' AND verdict IN ('CONFIRMED','WRONG') GROUP BY 1 ORDER BY precision DESC""")
show("ALL tier_random", """
SELECT COUNT(*) AS n, ROUND(SUM(verdict='CONFIRMED')*1.0/COUNT(*),3) AS precision,
  ROUND(SUM(sub='WRONG_TRANCHE')*1.0/COUNT(*),3) AS tranche_hop_rate, ROUND(SUM(sub='WRONG_BORROWER')*1.0/COUNT(*),3) AS wrong_borrower_rate
FROM gs WHERE stratum='tier_random' AND verdict IN ('CONFIRMED','WRONG')""")
show("WRONG edges on the contested tiers: what differs", """
SELECT tier, sub, COUNT(*) AS n,
  SUM(b_mat IS NOT NULL AND e_mat IS NOT NULL AND b_mat<>e_mat) AS mat_differs,
  SUM(b_spr IS NOT NULL AND e_spr IS NOT NULL AND ABS(b_spr-e_spr)>0.01) AS spr_differs,
  SUM(CASE WHEN b_pa>0 AND e_pa>0 THEN CASE WHEN ABS(LN(b_pa/e_pa))>LN(1.25) THEN 1 ELSE 0 END ELSE 0 END) AS pa_off_25pct,
  SUM(CASE WHEN b_cost>0 AND e_cost>0 THEN CASE WHEN ABS(LN(b_cost/e_cost))>LN(1.25) THEN 1 ELSE 0 END ELSE 0 END) AS cost_off_25pct,
  SUM(b_sub IS NOT NULL AND e_sub IS NOT NULL AND b_sub<>e_sub) AS sub_differs
FROM gs WHERE verdict='WRONG' AND (tier LIKE '%contested%' OR tier LIKE '%leftover%') GROUP BY 1,2 ORDER BY 1,2""")
show("sample WRONG edges on leftover tiers", """
SELECT tier, cik, b_name, e_name, b_mat, e_mat, b_spr, e_spr, b_pa, e_pa
FROM gs WHERE verdict='WRONG' AND tier LIKE '%leftover%' ORDER BY tier, cik LIMIT 14""")
show("per-CIK WRONG on contested_name_key (>=1 wrong)", """
SELECT cik, COUNT(*) AS n, SUM(verdict='WRONG') AS wrong FROM gs
WHERE tier='SUPP_B2_contested_name_key' AND verdict IN ('CONFIRMED','WRONG') GROUP BY 1 HAVING SUM(verdict='WRONG')>0 ORDER BY wrong DESC""")
