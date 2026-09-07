"""Production chain metrics: current build vs the active baseline snapshot (cohort BDC rows)."""
import json, sys
from pathlib import Path
import duckdb
REPO = Path(__file__).resolve().parents[3]
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
ciks = ",".join(f"'{e['cik']}'" for e in json.load(open(MAN))["entries"])
con = duckdb.connect()
con.execute("CREATE MACRO avgb(x) AS AVG(CASE WHEN x THEN 1 ELSE 0 END)")
for tag, root in [("baseline", REPO / "data/snapshots/baseline/data/output"), ("current", REPO / "data/output")]:
    h = (root / "private_markets_holdings.csv").as_posix(); e = (root / "position_id_edges.csv").as_posix()
    r = con.execute(f"""
      WITH h AS (SELECT cik, position_id, TRY_CAST(fair_value AS DOUBLE) AS fv, report_date
                 FROM read_csv_auto('{h}', all_varchar=true, sample_size=-1) WHERE LOWER(source)='bdc' AND cik IN ({ciks})),
           c AS (SELECT position_id, COUNT(*) AS n FROM h GROUP BY 1)
      SELECT COUNT(*) AS rows, ROUND(SUM(fv)/1e9,3) AS fv_busd, ROUND(avgb(c.n=1),4) AS singleton_share,
             ROUND(SUM(CASE WHEN c.n=1 THEN fv END)/SUM(fv),4) AS singleton_fv_share
      FROM h JOIN c USING (position_id)""").fetchone()
    print(f"{tag}: rows={r[0]} fv_busd={r[1]} singleton_share={r[2]} singleton_fv_share={r[3]}")
    mix = con.execute(f"""SELECT match_method, COUNT(*) FROM read_csv_auto('{e}', all_varchar=true, sample_size=-1)
                          WHERE cik IN ({ciks}) GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    print(f"  edges(cohort)={sum(n for _, n in mix)} mix={dict(mix)}")
