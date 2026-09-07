"""Chain-stability experiments E1-E4, E6, E7 over the mg3 gold set + cohort holdings.

Read-only. Loads private_markets_holdings.csv once (cohort filter, ~283K rows),
everything else is DuckDB SQL. Writes result CSVs to the scratch session dir.
"""
import json
import sys
import time
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from pipeline.position_matching import (  # noqa: E402
    _inst_subtype_sql, _name_key_sql, _next_quarter_sql, _quarter_label_sql)

OUT = Path(__file__).resolve().parent / "out"
HOLD = REPO / "data/output/private_markets_holdings.csv"
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
ciks = [e["cik"] for e in json.load(open(MAN))["entries"]]
cik_list = ",".join(f"'{c}'" for c in ciks)

t0 = time.time()
con = duckdb.connect()
con.execute("CREATE MACRO avgb(x) AS AVG(CASE WHEN x THEN 1 ELSE 0 END)")
con.execute(f"""
CREATE TABLE h AS
SELECT row_id, cik, report_date, {_quarter_label_sql('report_date')} AS q,
       issuer_name, {_name_key_sql('issuer_name')} AS name_key,
       canonical_name, entity_id, instrument_description, bdc_investment_identifier,
       {_inst_subtype_sql("COALESCE(instrument_description, bdc_investment_identifier, '')")} AS subtype,
       lien_position, instrument_type, TRY_CAST(maturity_date AS DATE) AS mat,
       TRY_CAST(basis_spread AS DOUBLE) AS spread, TRY_CAST(interest_rate AS DOUBLE) AS rate,
       TRY_CAST(principal_amount AS DOUBLE) AS pa, TRY_CAST(fair_value AS DOUBLE) AS fv,
       TRY_CAST(cost AS DOUBLE) AS cost, bdc_form_type, position_id, position_key
FROM read_csv_auto('{HOLD.as_posix()}', all_varchar=true, sample_size=-1)
WHERE LOWER(source) = 'bdc' AND cik IN ({cik_list})
""")
n = con.execute("SELECT COUNT(*), COUNT(DISTINCT cik), MAX(report_date) FROM h").fetchone()
print(f"holdings cohort rows={n[0]} ciks={n[1]} max_date={n[2]} ({time.time()-t0:.0f}s)")

con.execute(f"CREATE TABLE ge AS SELECT * FROM read_csv_auto('{(OUT/'gold_edges.csv').as_posix()}', all_varchar=true)")
con.execute(f"CREATE TABLE gp AS SELECT * FROM read_csv_auto('{(OUT/'gold_packets.csv').as_posix()}', all_varchar=true)")

# Enrich gold edges with holdings fields on both sides.
con.execute("""
CREATE TABLE gx AS
SELECT ge.packet_id, ge.stratum, ge.cik, ge.edge_index, ge.verdict, ge.tier, ge.rationale,
       b.row_id AS b_row, e.row_id AS e_row, b.q AS b_q, e.q AS e_q,
       b.issuer_name AS b_name, e.issuer_name AS e_name,
       b.name_key AS b_key, e.name_key AS e_key,
       b.entity_id AS b_ent, e.entity_id AS e_ent,
       b.subtype AS b_sub, e.subtype AS e_sub,
       b.lien_position AS b_lien, e.lien_position AS e_lien,
       b.instrument_type AS b_itype, e.instrument_type AS e_itype,
       b.mat AS b_mat, e.mat AS e_mat, b.spread AS b_spr, e.spread AS e_spr,
       b.pa AS b_pa, e.pa AS e_pa, b.fv AS b_fv, e.fv AS e_fv, b.cost AS b_cost, e.cost AS e_cost,
       b.bdc_form_type AS b_form, e.bdc_form_type AS e_form
FROM ge
LEFT JOIN h b ON b.row_id = ge.b_row_id
LEFT JOIN h e ON e.row_id = ge.e_row_id
""")
m = con.execute("SELECT COUNT(*), SUM(b_row IS NULL OR e_row IS NULL) FROM gx").fetchone()
print(f"gold edges={m[0]} unjoined-to-holdings={m[1]}")

def show(title, sql, save=None):
    print(f"\n== {title}")
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    rows = rel.fetchall()
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join("" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x)) for x in r))
    if save:
        con.execute(f"COPY ({sql}) TO '{(OUT/save).as_posix()}' (HEADER)")

# ---------------------------------------------------------------- E1 sub-codes
con.execute("""
CREATE TABLE e1 AS
SELECT *,
  CASE WHEN b_key = e_key THEN 'same_name_key'
       WHEN b_ent IS NOT NULL AND b_ent = e_ent THEN 'same_entity_diff_name'
       ELSE 'diff_borrower' END AS borrower_rel,
  CASE WHEN b_key = e_key OR (b_ent IS NOT NULL AND b_ent = e_ent) THEN 'WRONG_TRANCHE' ELSE 'WRONG_BORROWER' END AS subcode_det,
  CASE WHEN regexp_matches(LOWER(rationale), 'tranche|different (?:loan|facility|instrument|position|maturity)|separate (?:loan|facility|instrument|position)|sibling|other (?:loan|facility)') THEN 'tranche_kw' ELSE '' END
  || CASE WHEN regexp_matches(LOWER(rationale), 'different (?:borrower|company|issuer|entity|portfolio company)|unrelated|distinct (?:borrower|company|issuer)') THEN '+borrower_kw' ELSE '' END AS rationale_kw
FROM gx WHERE verdict = 'WRONG'
""")
show("E1: WRONG edge sub-codes (deterministic: name_key/entity agreement)", """
SELECT subcode_det, borrower_rel, COUNT(*) AS n FROM e1 GROUP BY 1,2 ORDER BY 1,2""")
show("E1: sub-code vs rationale keywords", """
SELECT subcode_det, rationale_kw, COUNT(*) AS n FROM e1 GROUP BY 1,2 ORDER BY 1,2""")
show("E1: tranche-hop share by tier, tier_random only (denominator = CONFIRMED+WRONG)", """
WITH t AS (SELECT gx.tier, gx.verdict, e1.subcode_det FROM gx LEFT JOIN e1 USING (packet_id, edge_index)
           WHERE gx.stratum='tier_random' AND gx.verdict IN ('CONFIRMED','WRONG'))
SELECT tier, COUNT(*) AS n, SUM(verdict='WRONG') AS wrong,
       SUM(subcode_det='WRONG_TRANCHE') AS wrong_tranche, SUM(subcode_det='WRONG_BORROWER') AS wrong_borrower,
       ROUND(SUM(subcode_det='WRONG_TRANCHE')*1.0/COUNT(*),3) AS tranche_hop_rate,
       ROUND(SUM(subcode_det='WRONG_BORROWER')*1.0/COUNT(*),3) AS wrong_borrower_rate
FROM t GROUP BY 1 ORDER BY tranche_hop_rate DESC""", save="e1_by_tier.csv")
show("E1: what differs on WRONG_TRANCHE edges (both sides known)", """
SELECT
  SUM(b_mat IS NOT NULL AND e_mat IS NOT NULL) AS mat_known,
  SUM(b_mat IS NOT NULL AND e_mat IS NOT NULL AND b_mat<>e_mat) AS mat_differs,
  SUM(b_spr IS NOT NULL AND e_spr IS NOT NULL) AS spr_known,
  SUM(b_spr IS NOT NULL AND e_spr IS NOT NULL AND ABS(b_spr-e_spr)>0.01) AS spr_differs,
  SUM(b_sub IS NOT NULL AND e_sub IS NOT NULL) AS sub_known,
  SUM(b_sub IS NOT NULL AND e_sub IS NOT NULL AND b_sub<>e_sub) AS sub_differs,
  SUM(b_lien IS NOT NULL AND e_lien IS NOT NULL) AS lien_known,
  SUM(b_lien IS NOT NULL AND e_lien IS NOT NULL AND b_lien<>e_lien) AS lien_differs,
  SUM(b_pa>0 AND e_pa>0) AS pa_known,
  SUM(b_pa>0 AND e_pa>0 AND ABS(LN(b_pa/e_pa))>LN(1.25)) AS pa_off_25pct,
  SUM((b_mat IS NOT NULL AND e_mat IS NOT NULL AND b_mat<>e_mat)
      OR (b_spr IS NOT NULL AND e_spr IS NOT NULL AND ABS(b_spr-e_spr)>0.01)
      OR (b_sub IS NOT NULL AND e_sub IS NOT NULL AND b_sub<>e_sub)
      OR (b_lien IS NOT NULL AND e_lien IS NOT NULL AND b_lien<>e_lien)) AS any_hard_field_differs,
  COUNT(*) AS n
FROM e1 WHERE subcode_det='WRONG_TRANCHE'""")
con.execute(f"COPY e1 TO '{(OUT/'e1_wrong_edges.csv').as_posix()}' (HEADER)")

# ---------------------------------------------------------------- E2 maturity
show("E2: maturity agreement on CONFIRMED vs WRONG gold edges", """
SELECT verdict,
  COUNT(*) AS n, SUM(b_mat IS NOT NULL AND e_mat IS NOT NULL) AS both_known,
  SUM(b_mat=e_mat) AS equal, SUM(b_mat<>e_mat) AS differ,
  ROUND(SUM(b_mat<>e_mat)*1.0/NULLIF(SUM(b_mat IS NOT NULL AND e_mat IS NOT NULL),0),3) AS differ_rate,
  SUM(b_mat<>e_mat AND ABS(DATEDIFF('day', b_mat, e_mat))<=45) AS differ_le45d,
  SUM(b_mat<>e_mat AND ABS(DATEDIFF('day', b_mat, e_mat))>365) AS differ_gt1y,
  SUM(b_mat IS NULL OR e_mat IS NULL) AS either_unknown
FROM gx WHERE verdict IN ('CONFIRMED','WRONG') GROUP BY 1""")
show("E2: CONFIRMED edges with maturity change -- what kind", """
SELECT cik, b_q, e_q, b_name, b_mat, e_mat, DATEDIFF('day', b_mat, e_mat) AS dd, b_sub, b_pa, e_pa
FROM gx WHERE verdict='CONFIRMED' AND b_mat<>e_mat ORDER BY ABS(dd) DESC LIMIT 25""",
     save="e2_confirmed_maturity_changes.csv")
show("E2: production base rate -- maturity change on adjacent-quarter chain steps (cohort)", """
WITH steps AS (
  SELECT a.cik, a.position_id, a.mat AS m1, b.mat AS m2, a.subtype
  FROM h a JOIN h b ON a.position_id=b.position_id AND a.cik=b.cik
   AND b.q = {nq} AND a.position_id IS NOT NULL)
SELECT COUNT(*) AS steps, SUM(m1 IS NOT NULL AND m2 IS NOT NULL) AS both_known,
       SUM(m1<>m2) AS differ, ROUND(SUM(m1<>m2)*1.0/NULLIF(SUM(m1 IS NOT NULL AND m2 IS NOT NULL),0),4) AS differ_rate,
       SUM(m1<>m2 AND ABS(DATEDIFF('day',m1,m2))<=45) AS differ_le45d
FROM steps""".replace("{nq}", _next_quarter_sql("a.q")))

# ---------------------------------------------------------------- E3 principal band
con.execute("""
CREATE TABLE e3 AS
SELECT verdict, tier, stratum,
       CASE WHEN b_sub IN ('REVOLVER','DDTL') OR e_sub IN ('REVOLVER','DDTL') THEN 'revolver_ddtl' ELSE 'other' END AS grp,
       ABS(LN(b_pa/e_pa)) AS lr, b_pa, e_pa
FROM gx WHERE verdict IN ('CONFIRMED','WRONG') AND b_pa>0 AND e_pa>0""")
show("E3: |ln(principal ratio)| quantiles, CONFIRMED vs WRONG, by instrument group", """
SELECT verdict, grp, COUNT(*) AS n,
  ROUND(quantile_cont(lr,0.5),3) AS p50, ROUND(quantile_cont(lr,0.75),3) AS p75,
  ROUND(quantile_cont(lr,0.9),3) AS p90, ROUND(quantile_cont(lr,0.95),3) AS p95, ROUND(MAX(lr),3) AS max
FROM e3 GROUP BY 1,2 ORDER BY 2,1""")
show("E3: band sweep -- CONFIRMED retained vs WRONG rejected (non-revolver)", """
SELECT band,
  ROUND(SUM(CASE WHEN verdict='CONFIRMED' AND lr<=LN(band) THEN 1 ELSE 0 END)*1.0/SUM(verdict='CONFIRMED'),3) AS confirmed_retained,
  ROUND(SUM(CASE WHEN verdict='WRONG' AND lr>LN(band) THEN 1 ELSE 0 END)*1.0/SUM(verdict='WRONG'),3) AS wrong_rejected,
  SUM(verdict='CONFIRMED') AS n_conf, SUM(verdict='WRONG') AS n_wrong
FROM e3, (SELECT UNNEST([1.02,1.05,1.10,1.25,1.5,2.0,4.0]) AS band) WHERE grp='other' GROUP BY 1 ORDER BY 1""",
     save="e3_band_sweep.csv")
show("E3: band sweep -- revolver/DDTL", """
SELECT band,
  ROUND(SUM(CASE WHEN verdict='CONFIRMED' AND lr<=LN(band) THEN 1 ELSE 0 END)*1.0/NULLIF(SUM(verdict='CONFIRMED'),0),3) AS confirmed_retained,
  ROUND(SUM(CASE WHEN verdict='WRONG' AND lr>LN(band) THEN 1 ELSE 0 END)*1.0/NULLIF(SUM(verdict='WRONG'),0),3) AS wrong_rejected,
  SUM(verdict='CONFIRMED') AS n_conf, SUM(verdict='WRONG') AS n_wrong
FROM e3, (SELECT UNNEST([1.05,1.25,1.5,2.0,4.0,10.0]) AS band) WHERE grp='revolver_ddtl' GROUP BY 1 ORDER BY 1""")
show("E3: principal missing on either side, by verdict", """
SELECT verdict, COUNT(*) AS n, SUM(NOT (b_pa>0 AND e_pa>0)) AS pa_missing FROM gx WHERE verdict IN ('CONFIRMED','WRONG') GROUP BY 1""")

# ---------------------------------------------------------------- E4 key completeness
con.execute("""
CREATE TABLE e4 AS
SELECT cik, q, row_id, name_key, mat, spread, pa, subtype,
  COUNT(*) OVER (PARTITION BY cik, q, name_key) AS n_name,
  COUNT(*) OVER (PARTITION BY cik, q, name_key, mat) AS n_name_mat,
  COUNT(*) OVER (PARTITION BY cik, q, name_key, mat, spread) AS n_name_mat_spr,
  COUNT(*) OVER (PARTITION BY cik, q, name_key, mat, spread, subtype) AS n_name_mat_spr_sub,
  COUNT(*) OVER (PARTITION BY cik, q, name_key, mat, spread, subtype, pa) AS n_full
FROM h WHERE name_key IS NOT NULL AND name_key <> ''""")
show("E4: cohort-wide key uniqueness (all quarters) and field coverage", """
SELECT COUNT(*) AS rows,
  ROUND(avgb(mat IS NOT NULL),3) AS mat_cov, ROUND(avgb(spread IS NOT NULL),3) AS spr_cov,
  ROUND(avgb(pa>0),3) AS pa_cov, ROUND(avgb(subtype IS NOT NULL),3) AS sub_cov,
  ROUND(avgb(n_name=1),3) AS uniq_name, ROUND(avgb(n_name_mat=1),3) AS uniq_name_mat,
  ROUND(avgb(n_name_mat_spr=1),3) AS uniq_name_mat_spr, ROUND(avgb(n_name_mat_spr_sub=1),3) AS uniq_plus_sub,
  ROUND(avgb(n_full=1),3) AS uniq_full
FROM e4""")
show("E4: per-CIK, latest quarter -- share of rows NOT unique on full key (worst 20)", """
SELECT cik, COUNT(*) AS rows,
  ROUND(avgb(mat IS NOT NULL),2) AS mat_cov, ROUND(avgb(spread IS NOT NULL),2) AS spr_cov, ROUND(avgb(pa>0),2) AS pa_cov,
  ROUND(avgb(n_name>1),3) AS name_dup, ROUND(avgb(n_name_mat_spr_sub>1),3) AS key_dup, ROUND(avgb(n_full>1),3) AS full_dup
FROM e4 WHERE q = (SELECT MAX(q) FROM e4) GROUP BY 1 ORDER BY key_dup DESC LIMIT 20""", save="e4_per_cik.csv")
con.execute(f"""COPY (SELECT cik, COUNT(*) AS rows, ROUND(avgb(mat IS NOT NULL),3) AS mat_cov,
  ROUND(avgb(spread IS NOT NULL),3) AS spr_cov, ROUND(avgb(pa>0),3) AS pa_cov,
  ROUND(avgb(n_name>1),3) AS name_dup, ROUND(avgb(n_name_mat_spr_sub>1),3) AS key_dup, ROUND(avgb(n_full>1),3) AS full_dup
  FROM e4 GROUP BY 1 ORDER BY key_dup DESC) TO '{(OUT/'e4_per_cik_allq.csv').as_posix()}' (HEADER)""")
show("E4: among name-duplicate rows, what resolves them", """
SELECT COUNT(*) AS name_dup_rows,
  ROUND(avgb(n_name_mat=1),3) AS resolved_by_mat, ROUND(avgb(n_name_mat>1 AND n_name_mat_spr=1),3) AS then_by_spread,
  ROUND(avgb(n_name_mat_spr>1 AND n_name_mat_spr_sub=1),3) AS then_by_subtype,
  ROUND(avgb(n_name_mat_spr_sub>1 AND n_full=1),3) AS then_by_principal, ROUND(avgb(n_full>1),3) AS still_dup
FROM e4 WHERE n_name>1""")

# ---------------------------------------------------------------- E6 splits / merges
con.execute(f"""
CREATE TABLE e6 AS
WITH a AS (SELECT cik, q, name_key, mat, subtype, COUNT(*) AS n FROM h WHERE name_key<>'' GROUP BY 1,2,3,4,5),
     b AS (SELECT cik, q, name_key, mat, subtype, COUNT(*) AS n FROM h WHERE name_key<>'' GROUP BY 1,2,3,4,5)
SELECT a.cik, a.q, a.name_key, a.mat, a.subtype, a.n AS n_begin, COALESCE(b.n,0) AS n_end
FROM a LEFT JOIN b ON a.cik=b.cik AND b.q={_next_quarter_sql('a.q')} AND a.name_key=b.name_key
  AND a.mat IS NOT DISTINCT FROM b.mat AND a.subtype IS NOT DISTINCT FROM b.subtype""")
show("E6: adjacent-quarter block shapes on (cik, name_key, maturity, subtype)", """
SELECT CASE WHEN n_end=0 THEN 'exit' WHEN n_begin=1 AND n_end=1 THEN '1:1'
            WHEN n_begin=1 AND n_end>1 THEN '1:N (split/add-on)' WHEN n_begin>1 AND n_end=1 THEN 'N:1 (merge/repay)'
            WHEN n_begin=n_end THEN 'N:N equal' ELSE 'N:M unequal' END AS shape,
       COUNT(*) AS blocks, SUM(n_begin) AS begin_rows, ROUND(SUM(n_begin)*1.0/(SELECT SUM(n_begin) FROM e6),3) AS row_share
FROM e6 GROUP BY 1 ORDER BY begin_rows DESC""", save="e6_block_shapes.csv")
show("E6: ambiguous blocks (n_begin>1 or n_end>1, both sides present) -- principal separation inside block", """
WITH amb AS (SELECT cik, q, name_key, mat, subtype FROM e6 WHERE n_end>0 AND (n_begin>1 OR n_end>1)),
     rows_b AS (SELECT h.cik, h.q, h.name_key, h.mat, h.subtype, h.pa FROM h JOIN amb USING (cik, q, name_key, mat, subtype)),
     sep AS (SELECT cik, q, name_key, mat, subtype, COUNT(*) AS n, COUNT(DISTINCT pa) AS n_pa,
                    MAX(pa)/NULLIF(MIN(pa),0) AS pa_ratio FROM rows_b WHERE pa>0 GROUP BY 1,2,3,4,5)
SELECT COUNT(*) AS blocks, SUM(n) AS rows,
  ROUND(avgb(n_pa=n),3) AS all_principals_distinct, ROUND(avgb(pa_ratio>1.05),3) AS spread_gt5pct, ROUND(avgb(pa_ratio>1.5),3) AS spread_gt50pct
FROM sep""")

# ---------------------------------------------------------------- E7 10-K boundary
show("E7: chain continuation rate by begin-filing form type (cohort, non-last quarter)", f"""
WITH nx AS (SELECT cik, q FROM h GROUP BY 1,2),
     r AS (SELECT a.cik, a.q, a.row_id, a.position_id, a.bdc_form_type,
             EXISTS (SELECT 1 FROM h b WHERE b.cik=a.cik AND b.position_id=a.position_id AND b.q={_next_quarter_sql('a.q')}) AS continued,
             EXISTS (SELECT 1 FROM nx WHERE nx.cik=a.cik AND nx.q={_next_quarter_sql('a.q')}) AS next_q_filed
           FROM h a WHERE a.position_id IS NOT NULL AND a.fv > 0)
SELECT bdc_form_type, COUNT(*) AS rows, ROUND(avgb(continued),3) AS continued_rate
FROM r WHERE next_q_filed GROUP BY 1 ORDER BY rows DESC""")
show("E7: per-CIK 10-K vs 10-Q continuation gap (worst 20 by gap, >=200 rows each)", f"""
WITH nx AS (SELECT cik, q FROM h GROUP BY 1,2),
     r AS (SELECT a.cik, a.q, a.bdc_form_type,
             EXISTS (SELECT 1 FROM h b WHERE b.cik=a.cik AND b.position_id=a.position_id AND b.q={_next_quarter_sql('a.q')}) AS continued,
             EXISTS (SELECT 1 FROM nx WHERE nx.cik=a.cik AND nx.q={_next_quarter_sql('a.q')}) AS next_q_filed
           FROM h a WHERE a.position_id IS NOT NULL AND a.fv > 0),
     p AS (SELECT cik,
             ROUND(AVG(CASE WHEN bdc_form_type LIKE '10-K%' THEN CAST(continued AS INT) END),3) AS k_rate, SUM(bdc_form_type LIKE '10-K%') AS k_n,
             ROUND(AVG(CASE WHEN bdc_form_type LIKE '10-Q%' THEN CAST(continued AS INT) END),3) AS q_rate, SUM(bdc_form_type LIKE '10-Q%') AS q_n
           FROM r WHERE next_q_filed GROUP BY 1)
SELECT cik, k_n, k_rate, q_n, q_rate, ROUND(q_rate-k_rate,3) AS gap FROM p WHERE k_n>=200 AND q_n>=200 ORDER BY gap DESC LIMIT 20""",
     save="e7_per_cik.csv")
# ---------------------------------------------------------------- E5-lite veto rules on gold edges
con.execute("""
CREATE TABLE e5 AS
SELECT gx.*, COALESCE(e1.subcode_det, 'OK') AS sub,
  CASE WHEN b_pa>0 AND e_pa>0 THEN ABS(LN(b_pa/e_pa)) END AS lr,
  (b_mat IS NULL OR e_mat IS NULL OR b_mat=e_mat) AS r_mat_strict,
  (b_mat IS NULL OR e_mat IS NULL OR b_mat=e_mat
     OR (b_pa>0 AND e_pa>0 AND ABS(LN(b_pa/e_pa))<=LN(1.02) AND (b_spr IS NULL OR e_spr IS NULL OR ABS(b_spr-e_spr)<=0.01))) AS r_mat_amend,
  (b_spr IS NULL OR e_spr IS NULL OR ABS(b_spr-e_spr)<=0.01) AS r_spr,
  (b_spr IS NULL OR e_spr IS NULL OR ABS(b_spr-e_spr)<=0.51) AS r_spr_loose,
  (b_sub IS NULL OR e_sub IS NULL OR b_sub=e_sub) AS r_sub,
  (b_lien IS NULL OR e_lien IS NULL OR b_lien=e_lien) AS r_lien,
  (NOT (b_pa>0 AND e_pa>0) OR ABS(LN(b_pa/e_pa)) <= LN(CASE WHEN (b_sub IN ('REVOLVER','DDTL') OR e_sub IN ('REVOLVER','DDTL')) THEN 10.0 ELSE 4.0 END)) AS r_pa_wide,
  (NOT (b_pa>0 AND e_pa>0) OR ABS(LN(b_pa/e_pa)) <= LN(CASE WHEN (b_sub IN ('REVOLVER','DDTL') OR e_sub IN ('REVOLVER','DDTL')) THEN 4.0 ELSE 2.0 END)) AS r_pa_mid
FROM gx LEFT JOIN (SELECT packet_id, edge_index, subcode_det FROM e1) e1 USING (packet_id, edge_index)
WHERE gx.verdict IN ('CONFIRMED','WRONG') AND b_row IS NOT NULL AND e_row IS NOT NULL
""")
show("E5: single veto rules -- CONFIRMED retained / WRONG rejected (tranche vs borrower)", """
SELECT rule,
  ROUND(SUM(CASE WHEN verdict='CONFIRMED' AND pass THEN 1 ELSE 0 END)*1.0/SUM(verdict='CONFIRMED'),3) AS conf_retained,
  SUM(CASE WHEN verdict='CONFIRMED' AND NOT pass THEN 1 ELSE 0 END) AS conf_lost,
  ROUND(SUM(CASE WHEN sub='WRONG_TRANCHE' AND NOT pass THEN 1 ELSE 0 END)*1.0/SUM(sub='WRONG_TRANCHE'),3) AS tranche_rejected,
  ROUND(SUM(CASE WHEN sub='WRONG_BORROWER' AND NOT pass THEN 1 ELSE 0 END)*1.0/SUM(sub='WRONG_BORROWER'),3) AS borrower_rejected
FROM (
  SELECT verdict, sub, 'mat_strict' AS rule, r_mat_strict AS pass FROM e5 UNION ALL
  SELECT verdict, sub, 'mat_amend', r_mat_amend FROM e5 UNION ALL
  SELECT verdict, sub, 'spread_exact', r_spr FROM e5 UNION ALL
  SELECT verdict, sub, 'spread_50bp', r_spr_loose FROM e5 UNION ALL
  SELECT verdict, sub, 'subtype', r_sub FROM e5 UNION ALL
  SELECT verdict, sub, 'lien', r_lien FROM e5 UNION ALL
  SELECT verdict, sub, 'pa_wide(4x/10x)', r_pa_wide FROM e5 UNION ALL
  SELECT verdict, sub, 'pa_mid(2x/4x)', r_pa_mid FROM e5)
GROUP BY 1 ORDER BY 1""", save="e5_single_rules.csv")
show("E5: combined veto sets", """
SELECT combo,
  ROUND(SUM(CASE WHEN verdict='CONFIRMED' AND pass THEN 1 ELSE 0 END)*1.0/SUM(verdict='CONFIRMED'),3) AS conf_retained,
  SUM(CASE WHEN verdict='CONFIRMED' AND NOT pass THEN 1 ELSE 0 END) AS conf_lost,
  SUM(CASE WHEN verdict='WRONG' AND pass THEN 1 ELSE 0 END) AS wrong_survive,
  ROUND(SUM(CASE WHEN sub='WRONG_TRANCHE' AND NOT pass THEN 1 ELSE 0 END)*1.0/SUM(sub='WRONG_TRANCHE'),3) AS tranche_rejected,
  ROUND(SUM(CASE WHEN sub='WRONG_BORROWER' AND NOT pass THEN 1 ELSE 0 END)*1.0/SUM(sub='WRONG_BORROWER'),3) AS borrower_rejected,
  ROUND(SUM(CASE WHEN verdict='CONFIRMED' AND pass THEN 1 ELSE 0 END)*1.0/NULLIF(SUM(CASE WHEN pass THEN 1 ELSE 0 END),0),3) AS precision_after
FROM (
  SELECT verdict, sub, 'A: mat_amend' AS combo, r_mat_amend AS pass FROM e5 UNION ALL
  SELECT verdict, sub, 'B: mat_amend+spread_50bp', r_mat_amend AND r_spr_loose FROM e5 UNION ALL
  SELECT verdict, sub, 'C: B+subtype+lien', r_mat_amend AND r_spr_loose AND r_sub AND r_lien FROM e5 UNION ALL
  SELECT verdict, sub, 'D: C+pa_wide', r_mat_amend AND r_spr_loose AND r_sub AND r_lien AND r_pa_wide FROM e5 UNION ALL
  SELECT verdict, sub, 'E: C+pa_mid', r_mat_amend AND r_spr_loose AND r_sub AND r_lien AND r_pa_mid FROM e5 UNION ALL
  SELECT verdict, sub, 'F: strict all', r_mat_strict AND r_spr AND r_sub AND r_lien AND r_pa_mid FROM e5)
GROUP BY 1 ORDER BY 1""", save="e5_combos.csv")
show("E5: WRONG edges surviving combo D", """
SELECT sub, tier, cik, b_name, e_name, b_mat, e_mat, b_spr, e_spr, b_pa, e_pa, b_sub, e_sub
FROM e5 WHERE verdict='WRONG' AND r_mat_amend AND r_spr_loose AND r_sub AND r_lien AND r_pa_wide ORDER BY sub, cik""",
     save="e5_survivors_D.csv")
show("E5: CONFIRMED edges lost under combo D", """
SELECT tier, cik, b_name, b_mat, e_mat, b_spr, e_spr, b_pa, e_pa, b_sub, e_sub,
  CASE WHEN NOT r_mat_amend THEN 'mat ' ELSE '' END || CASE WHEN NOT r_spr_loose THEN 'spr ' ELSE '' END
  || CASE WHEN NOT r_sub THEN 'sub ' ELSE '' END || CASE WHEN NOT r_lien THEN 'lien ' ELSE '' END || CASE WHEN NOT r_pa_wide THEN 'pa' ELSE '' END AS failed
FROM e5 WHERE verdict='CONFIRMED' AND NOT (r_mat_amend AND r_spr_loose AND r_sub AND r_lien AND r_pa_wide) ORDER BY failed, cik""",
     save="e5_lost_D.csv")
show("E5: per-CIK stability of combo D (CIKs with >=10 scored edges)", """
SELECT cik, COUNT(*) AS n, SUM(verdict='WRONG') AS wrong,
  SUM(CASE WHEN verdict='CONFIRMED' AND NOT (r_mat_amend AND r_spr_loose AND r_sub AND r_lien AND r_pa_wide) THEN 1 ELSE 0 END) AS conf_lost,
  SUM(CASE WHEN verdict='WRONG' AND (r_mat_amend AND r_spr_loose AND r_sub AND r_lien AND r_pa_wide) THEN 1 ELSE 0 END) AS wrong_survive
FROM e5 GROUP BY 1 HAVING COUNT(*)>=10 ORDER BY wrong_survive DESC, conf_lost DESC""", save="e5_per_cik_D.csv")
show("E4b: null issuer_name rows by CIK (all quarters) -- unchainable by any name tier", """
SELECT cik, COUNT(*) AS null_rows, SUM(fv>0) AS fv_pos, ROUND(SUM(fv)/1e6,1) AS fv_musd,
  SUM(q=(SELECT MAX(q) FROM h)) AS in_latest_q, SUM(position_id IS NULL) AS pid_null
FROM h WHERE name_key IS NULL OR name_key='' GROUP BY 1 ORDER BY null_rows DESC LIMIT 12""", save="e4b_null_names.csv")
show("E4b: sample GSBD null-name rows, latest quarter", """
SELECT bdc_investment_identifier, instrument_description, mat, spread, pa, fv, position_id
FROM h WHERE cik='0001572694' AND (name_key IS NULL OR name_key='') AND q=(SELECT MAX(q) FROM h) LIMIT 6""")
# ---------------------------------------------------------------- E5b: count-based veto + lot ambiguity classes
show("E5b: veto when >=k hard fields disagree (mat, spread>50bp, subtype, lien)", """
WITH d AS (SELECT verdict, sub,
   (CASE WHEN NOT r_mat_amend THEN 1 ELSE 0 END + CASE WHEN NOT r_spr_loose THEN 1 ELSE 0 END
    + CASE WHEN NOT r_sub THEN 1 ELSE 0 END + CASE WHEN NOT r_lien THEN 1 ELSE 0 END) AS n_dis FROM e5)
SELECT k, ROUND(SUM(CASE WHEN verdict='CONFIRMED' AND n_dis<k THEN 1 ELSE 0 END)*1.0/SUM(verdict='CONFIRMED'),3) AS conf_retained,
  SUM(CASE WHEN verdict='CONFIRMED' AND n_dis>=k THEN 1 ELSE 0 END) AS conf_lost,
  SUM(CASE WHEN verdict='WRONG' AND n_dis<k THEN 1 ELSE 0 END) AS wrong_survive,
  ROUND(SUM(CASE WHEN sub='WRONG_TRANCHE' AND n_dis>=k THEN 1 ELSE 0 END)*1.0/SUM(sub='WRONG_TRANCHE'),3) AS tranche_rejected,
  ROUND(SUM(CASE WHEN sub='WRONG_BORROWER' AND n_dis>=k THEN 1 ELSE 0 END)*1.0/SUM(sub='WRONG_BORROWER'),3) AS borrower_rejected
FROM d, (SELECT UNNEST([1,2]) AS k) GROUP BY 1 ORDER BY 1""")
con.execute("""
CREATE TABLE lot AS
SELECT e5.packet_id, e5.edge_index, e5.verdict, e5.sub, e5.tier, e5.cik, e5.b_name,
  (SELECT COUNT(*) FROM h x WHERE x.cik=e5.cik AND x.q=e5.b_q AND x.name_key=e5.b_key) AS blk_name,
  (SELECT COUNT(*) FROM h x WHERE x.cik=e5.cik AND x.q=e5.b_q AND x.name_key=e5.b_key
     AND x.mat IS NOT DISTINCT FROM e5.b_mat AND x.subtype IS NOT DISTINCT FROM e5.b_sub
     AND (x.spread IS NULL OR e5.b_spr IS NULL OR ABS(x.spread-e5.b_spr)<=0.51)) AS blk_hard,
  (SELECT COUNT(*) FROM h x WHERE x.cik=e5.cik AND x.q=e5.b_q AND x.name_key=e5.b_key
     AND x.mat IS NOT DISTINCT FROM e5.b_mat AND x.subtype IS NOT DISTINCT FROM e5.b_sub
     AND (x.spread IS NULL OR e5.b_spr IS NULL OR ABS(x.spread-e5.b_spr)<=0.51)
     AND x.pa>0 AND e5.b_pa>0 AND ABS(LN(x.pa/e5.b_pa))<=LN(1.05)) AS blk_lot
FROM e5""")
show("E5b: WRONG_TRANCHE edges by begin-side block ambiguity class", """
SELECT CASE WHEN blk_hard<=1 THEN 'A: unique on hard key (assignment picked another hard key -> veto fixes)'
            WHEN blk_lot<=1 THEN 'B: hard-key siblings, principal separates (>5%) -> assignment cost fixes'
            ELSE 'C: identical lots (hard key + principal within 5%) -> undecidable from fields' END AS cls,
       COUNT(*) AS n
FROM lot WHERE sub='WRONG_TRANCHE' GROUP BY 1 ORDER BY 1""", save="e5b_lot_classes.csv")
show("E5b: same classes for CONFIRMED edges (how often the matcher already got ambiguous blocks right)", """
SELECT CASE WHEN blk_hard<=1 THEN 'A: unique on hard key' WHEN blk_lot<=1 THEN 'B: principal separates' ELSE 'C: identical lots' END AS cls,
       COUNT(*) AS n_confirmed FROM lot WHERE verdict='CONFIRMED' GROUP BY 1 ORDER BY 1""")
show("E5b: identical-lot WRONG edges -- filers", """
SELECT cik, COUNT(*) AS n, MIN(b_name) AS example FROM lot WHERE sub='WRONG_TRANCHE' AND blk_lot>1 GROUP BY 1 ORDER BY n DESC""")

# ---------------------------------------------------------------- E6b/E7b: completeness decomposition
con.execute(f"""
CREATE TABLE cont AS
WITH lastq AS (SELECT cik, MAX(q) AS last_q FROM h GROUP BY 1),
     nq AS (SELECT DISTINCT cik, q FROM h)
SELECT a.cik, a.q, a.row_id, a.name_key, a.fv, a.position_id,
  EXISTS (SELECT 1 FROM h b WHERE b.cik=a.cik AND b.position_id=a.position_id AND b.q={_next_quarter_sql('a.q')}) AS continued,
  EXISTS (SELECT 1 FROM h b WHERE b.cik=a.cik AND b.name_key=a.name_key AND b.q={_next_quarter_sql('a.q')}) AS name_next,
  EXISTS (SELECT 1 FROM h b WHERE b.cik=a.cik AND b.name_key=a.name_key AND b.q={_next_quarter_sql('a.q')}
            AND b.mat IS NOT DISTINCT FROM a.mat AND (b.spread IS NULL OR a.spread IS NULL OR ABS(b.spread-a.spread)<=0.51)) AS hardkey_next,
  (SELECT COUNT(*) FROM h c WHERE c.cik=a.cik AND c.position_id=a.position_id) AS chain_len,
  a.q = (SELECT MIN(q) FROM h m WHERE m.cik=a.cik) AS first_q
FROM h a JOIN lastq l ON l.cik=a.cik AND a.q < l.last_q
JOIN nq ON nq.cik=a.cik AND nq.q={_next_quarter_sql('a.q')}
WHERE a.fv > 0 AND a.name_key IS NOT NULL AND a.name_key <> ''""")
show("E7b: what happens to a live row at the next quarter (cohort, next quarter filed, FV>0)", """
SELECT CASE WHEN continued THEN 'continued'
            WHEN hardkey_next THEN 'BREAK: same name+maturity+spread exists next quarter (likely missed link)'
            WHEN name_next THEN 'BREAK: same name exists, hard key differs (refi/amend/extraction)'
            ELSE 'exit: name absent next quarter' END AS outcome,
       COUNT(*) AS rows, ROUND(COUNT(*)*1.0/(SELECT COUNT(*) FROM cont),3) AS share, ROUND(SUM(fv)/1e9,1) AS fv_busd
FROM cont GROUP BY 1 ORDER BY rows DESC""", save="e7b_outcomes.csv")
show("E7b: per-CIK likely-missed-link share (worst 15, >=500 rows)", """
SELECT cik, COUNT(*) AS rows, ROUND(avgb(continued),3) AS continued,
  ROUND(avgb(NOT continued AND hardkey_next),3) AS likely_missed, ROUND(avgb(NOT continued AND NOT name_next),3) AS exit
FROM cont GROUP BY 1 HAVING COUNT(*)>=500 ORDER BY likely_missed DESC LIMIT 15""", save="e7b_per_cik.csv")
show("E7b: interior singletons (chain_len=1, not first quarter) -- the recall stratum size", """
SELECT COUNT(*) AS interior_singletons, ROUND(SUM(fv)/1e9,1) AS fv_busd,
  SUM(hardkey_next) AS hardkey_present_next, ROUND(avgb(hardkey_next),3) AS share_hardkey_next
FROM cont WHERE chain_len=1 AND NOT first_q""")
show("E6b: adjacent-quarter block shapes excluding each CIK's last quarter", f"""
WITH lastq AS (SELECT cik, MAX(q) AS last_q FROM h GROUP BY 1),
     e AS (SELECT e6.* FROM e6 JOIN lastq USING (cik) WHERE e6.q < lastq.last_q)
SELECT CASE WHEN n_end=0 THEN 'exit/key-change' WHEN n_begin=1 AND n_end=1 THEN '1:1'
            WHEN n_begin=1 AND n_end>1 THEN '1:N' WHEN n_begin>1 AND n_end=1 THEN 'N:1'
            WHEN n_begin=n_end THEN 'N:N equal' ELSE 'N:M unequal' END AS shape,
       COUNT(*) AS blocks, SUM(n_begin) AS begin_rows, ROUND(SUM(n_begin)*1.0/(SELECT SUM(n_begin) FROM e),3) AS row_share
FROM e GROUP BY 1 ORDER BY begin_rows DESC""")
print(f"\ndone in {time.time()-t0:.0f}s")
