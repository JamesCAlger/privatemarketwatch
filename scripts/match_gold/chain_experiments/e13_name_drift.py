"""E13: size the two remaining completeness mechanisms on the current production build.

  (a) terms-fingerprint links -- adjacent-quarter break/new row pairs inside a CIK that
      agree on maturity + classification + principal band + spread and are unique on both
      sides of the block, but which no name-keyed tier can see.
  (b) gap-quarter links -- a position absent for one filing and present again after.
  (c) how many of the mg5 pairs that no tier admits today each mechanism would catch.

Read-only over data/output; writes CSV/markdown to chain_experiments/out/e13/.

Usage: python scripts/match_gold/chain_experiments/e13_name_drift.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
HOLD = (REPO / "data/output/private_markets_holdings.csv").as_posix()
OUT = Path(__file__).resolve().parent / "out" / "e13"
OUT.mkdir(parents=True, exist_ok=True)

PA_BAND = 1.05          # principal ratio tolerance
SPREAD_TOL = 0.05       # percentage points

ciks = ",".join("'%s'" % e["cik"] for e in json.load(open(MAN))["entries"])
con = duckdb.connect()
con.execute("PRAGMA threads=4")

con.execute(f"""
CREATE TABLE base AS
SELECT cik, row_id, position_id, report_date,
       (CAST(EXTRACT(year FROM TRY_CAST(report_date AS DATE)) AS INT) * 4
        + CAST(EXTRACT(quarter FROM TRY_CAST(report_date AS DATE)) AS INT)) AS qi,
       issuer_name,
       LOWER(TRIM(COALESCE(issuer_name, ''))) AS nm,
       TRY_CAST(fair_value AS DOUBLE) AS fv,
       TRY_CAST(principal_amount AS DOUBLE) AS pa,
       TRY_CAST(basis_spread AS DOUBLE) AS bs,
       TRY_CAST(maturity_date AS DATE) AS mat,
       index_classification AS ic,
       instrument_type AS itype,
       lien_position AS lien
FROM read_csv_auto('{HOLD}', all_varchar=true, sample_size=-1)
WHERE LOWER(source) = 'bdc' AND cik IN ({ciks})
""")

con.execute("CREATE TABLE cq AS SELECT DISTINCT cik, qi FROM base")
con.execute("CREATE TABLE pq AS SELECT DISTINCT cik, position_id, qi FROM base")
con.execute("""
CREATE TABLE flags AS
SELECT b.*,
       (n.position_id IS NOT NULL) AS has_next,
       (p.position_id IS NOT NULL) AS has_prev,
       (cn.qi IS NOT NULL) AS cik_files_next,
       (cp.qi IS NOT NULL) AS cik_files_prev
FROM base b
LEFT JOIN pq n  ON n.cik = b.cik AND n.position_id = b.position_id AND n.qi = b.qi + 1
LEFT JOIN pq p  ON p.cik = b.cik AND p.position_id = b.position_id AND p.qi = b.qi - 1
LEFT JOIN cq cn ON cn.cik = b.cik AND cn.qi = b.qi + 1
LEFT JOIN cq cp ON cp.cik = b.cik AND cp.qi = b.qi - 1
""")

tot = con.execute("""SELECT COUNT(*), ROUND(SUM(fv)/1e9,1),
  SUM(CASE WHEN cik_files_next AND NOT has_next THEN 1 ELSE 0 END),
  ROUND(SUM(CASE WHEN cik_files_next AND NOT has_next THEN fv END)/1e9,1)
  FROM flags""").fetchone()
print("cohort BDC rows=%s fv=$%sB | break rows (CIK files next quarter, position does not "
      "continue)=%s fv=$%sB" % tot, flush=True)

# ---------------------------------------------------------------- (a) fingerprint
con.execute(f"""
CREATE TABLE cand AS
WITH b AS (SELECT * FROM flags WHERE cik_files_next AND NOT has_next AND mat IS NOT NULL),
     e AS (SELECT * FROM flags WHERE cik_files_prev AND NOT has_prev AND mat IS NOT NULL)
SELECT b.cik AS cik, b.qi AS qi,
       b.row_id AS b_row, e.row_id AS e_row,
       b.issuer_name AS b_name, e.issuer_name AS e_name,
       b.nm AS b_nm, e.nm AS e_nm,
       b.fv AS b_fv, e.fv AS e_fv, b.pa AS b_pa, e.pa AS e_pa,
       b.bs AS b_bs, e.bs AS e_bs, b.mat AS mat, b.ic AS ic,
       b.itype AS b_itype, e.itype AS e_itype, b.lien AS b_lien, e.lien AS e_lien
FROM b JOIN e
  ON e.cik = b.cik AND e.qi = b.qi + 1
 AND e.mat = b.mat
 AND e.ic  = b.ic
 AND b.pa IS NOT NULL AND e.pa IS NOT NULL AND b.pa > 0 AND e.pa > 0
 AND b.pa / e.pa BETWEEN 1.0/{PA_BAND} AND {PA_BAND}
 AND (b.bs IS NULL OR e.bs IS NULL OR ABS(b.bs - e.bs) <= {SPREAD_TOL})
""")

con.execute("""
CREATE TABLE uniq AS
WITH nb AS (SELECT b_row, COUNT(*) AS n FROM cand GROUP BY 1),
     ne AS (SELECT e_row, COUNT(*) AS n FROM cand GROUP BY 1)
SELECT c.*,
       (c.b_nm = c.e_nm) AS name_same,
       (c.b_nm <> c.e_nm AND (contains(c.b_nm, c.e_nm) OR contains(c.e_nm, c.b_nm)))
         AS name_contained
FROM cand c JOIN nb ON nb.b_row = c.b_row JOIN ne ON ne.e_row = c.e_row
WHERE nb.n = 1 AND ne.n = 1
""")

r = con.execute("""SELECT
  (SELECT COUNT(*) FROM cand), (SELECT COUNT(*) FROM uniq),
  SUM(CASE WHEN name_same THEN 1 ELSE 0 END),
  SUM(CASE WHEN name_contained THEN 1 ELSE 0 END),
  SUM(CASE WHEN NOT name_same AND NOT name_contained THEN 1 ELSE 0 END),
  ROUND(SUM(e_fv)/1e9, 2),
  ROUND(SUM(CASE WHEN name_contained THEN e_fv END)/1e9, 2),
  ROUND(SUM(CASE WHEN NOT name_same AND NOT name_contained THEN e_fv END)/1e9, 2)
  FROM uniq""").fetchone()
print("\n(a) fingerprint candidates: raw pairs=%s unique-both-sides=%s (fv $%sB)"
      "\n    name identical=%s  one name contains the other=%s ($%sB)  names unrelated=%s ($%sB)"
      % (r[0], r[1], r[5], r[2], r[3], r[6], r[4], r[7]), flush=True)

con.execute(f"""COPY (
  SELECT cik, COUNT(*) AS pairs,
         SUM(CASE WHEN name_contained THEN 1 ELSE 0 END) AS contained,
         SUM(CASE WHEN NOT name_same AND NOT name_contained THEN 1 ELSE 0 END) AS unrelated,
         ROUND(SUM(e_fv)/1e9, 3) AS fv_busd
  FROM uniq GROUP BY 1 ORDER BY pairs DESC
) TO '{(OUT / "e13a_per_cik.csv").as_posix()}' (HEADER)""")
con.execute(f"""COPY (SELECT * FROM uniq ORDER BY e_fv DESC)
                TO '{(OUT / "e13a_pairs.csv").as_posix()}' (HEADER)""")

print("\n  top CIKs by fingerprint pairs:")
for row in con.execute("""SELECT cik, COUNT(*) AS n,
                            SUM(CASE WHEN name_contained THEN 1 ELSE 0 END) AS c,
                            SUM(CASE WHEN name_same THEN 1 ELSE 0 END) AS s,
                            ROUND(SUM(e_fv)/1e9,2) AS fv
                          FROM uniq GROUP BY 1 ORDER BY n DESC LIMIT 12""").fetchall():
    print("    %s pairs=%5d contained=%5d same=%5d fv=$%sB" % row)

amb = con.execute("""WITH nb AS (SELECT b_row, COUNT(*) AS n FROM cand GROUP BY 1)
                     SELECT SUM(CASE WHEN n = 1 THEN 1 ELSE 0 END), COUNT(*) FROM nb""").fetchone()
print("\n  begin rows with a fingerprint candidate: %s, of which unique: %s (%.1f%%)"
      % (amb[1], amb[0], 100.0 * amb[0] / max(amb[1], 1)))

# ---------------------------------------------------------------- (b) gap quarter
con.execute(f"""
CREATE TABLE gap AS
WITH b AS (SELECT * FROM flags WHERE cik_files_next AND NOT has_next AND mat IS NOT NULL),
     e AS (SELECT * FROM flags WHERE NOT has_prev AND mat IS NOT NULL),
     j AS (
       SELECT b.cik AS cik, b.qi AS qi, b.row_id AS b_row, e.row_id AS e_row,
              b.nm AS b_nm, e.nm AS e_nm,
              b.fv AS b_fv, e.fv AS e_fv, b.pa AS b_pa, e.pa AS e_pa, b.mat AS mat
       FROM b JOIN e
         ON e.cik = b.cik AND e.qi = b.qi + 2
        AND e.mat = b.mat AND e.ic = b.ic AND e.nm = b.nm
        AND b.pa IS NOT NULL AND e.pa IS NOT NULL AND b.pa > 0 AND e.pa > 0
        AND b.pa / e.pa BETWEEN 1.0/{PA_BAND} AND {PA_BAND}
       WHERE EXISTS (SELECT 1 FROM cq WHERE cq.cik = b.cik AND cq.qi = b.qi + 1)
     ),
     nb AS (SELECT b_row, COUNT(*) AS n FROM j GROUP BY 1),
     ne AS (SELECT e_row, COUNT(*) AS n FROM j GROUP BY 1)
SELECT j.* FROM j JOIN nb ON nb.b_row = j.b_row JOIN ne ON ne.e_row = j.e_row
WHERE nb.n = 1 AND ne.n = 1
  AND NOT EXISTS (SELECT 1 FROM flags m
                  WHERE m.cik = j.cik AND m.qi = j.qi + 1 AND m.nm = j.b_nm)
""")
g = con.execute("SELECT COUNT(*), ROUND(SUM(e_fv)/1e9,2), COUNT(DISTINCT cik) FROM gap").fetchone()
print("\n(b) gap-quarter (span-2) links: pairs=%s fv=$%sB across %s CIKs "
      "(same name, same maturity, principal band, absent in the intervening filing)" % g)
con.execute(f"""COPY (SELECT * FROM gap ORDER BY e_fv DESC)
                TO '{(OUT / "e13b_gap_pairs.csv").as_posix()}' (HEADER)""")
for row in con.execute("""SELECT cik, COUNT(*) AS n, ROUND(SUM(e_fv)/1e9,2) AS fv FROM gap
                          GROUP BY 1 ORDER BY n DESC LIMIT 8""").fetchall():
    print("    %s pairs=%5d fv=$%sB" % row)

# ---------------------------------------------------------------- (c) mg5 blocked pairs
REPLAY = REPO / "scratch/2026-09-07_chain_experiments/replay_mg5.csv"
if REPLAY.exists():
    con.execute(f"""CREATE TABLE mg5 AS SELECT * FROM
        read_csv_auto('{REPLAY.as_posix()}', all_varchar=true, sample_size=-1)""")
    m = con.execute("""
      SELECT COUNT(*) AS blocked,
        SUM(CASE WHEN u.b_row IS NOT NULL THEN 1 ELSE 0 END) AS caught_fp,
        SUM(CASE WHEN gp.b_row IS NOT NULL THEN 1 ELSE 0 END) AS caught_gap
      FROM mg5 t
      LEFT JOIN uniq u ON u.b_row = t.row_a AND u.e_row = t.row_b
      LEFT JOIN gap gp ON gp.b_row = t.row_a AND gp.e_row = t.row_b
      WHERE LOWER(t.any_admit) = 'false'""").fetchone()
    print("\n(c) mg5 pairs no tier admits today: %s | caught by fingerprint: %s | "
          "caught by gap-quarter: %s" % m)
print("\nwrote %s" % OUT)
