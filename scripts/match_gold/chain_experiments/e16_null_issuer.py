"""E16: scope the null-issuer-name wrapper defect.

A row with no issuer name cannot be reached by any name-keyed tier, and every
null name collides into one multiplicity bucket, so these rows are structurally
unchainable (E14: 1,472 candidate pairs, $6.6B).  The fix belongs in
data/overrides/bdc_xbrl_wrappers/, not in the matcher.  This script says which
CIKs are affected, whether the raw identifier still carries a recoverable name,
and how much fair value rides on it.

Read-only over data/output; writes to chain_experiments/out/e16/.

Usage: python scripts/match_gold/chain_experiments/e16_null_issuer.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
HOLD = (REPO / "data/output/private_markets_holdings.csv").as_posix()
OUT = Path(__file__).resolve().parent / "out" / "e16"
OUT.mkdir(parents=True, exist_ok=True)

ciks = ",".join("'%s'" % e["cik"] for e in json.load(open(MAN))["entries"])
con = duckdb.connect()
con.execute("PRAGMA threads=4")
con.execute(f"""
CREATE TABLE b AS
SELECT cik, entity_name, row_id, report_date, issuer_name,
       bdc_investment_identifier AS raw_id,
       instrument_description AS descr,
       TRY_CAST(fair_value AS DOUBLE) AS fv,
       position_id
FROM read_csv_auto('{HOLD}', all_varchar=true, sample_size=-1)
WHERE LOWER(source) = 'bdc' AND cik IN ({ciks})
""")

tot = con.execute("""
SELECT COUNT(*),
       SUM(CASE WHEN COALESCE(TRIM(issuer_name), '') = '' THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN COALESCE(TRIM(issuer_name), '') = '' THEN ABS(fv) END)/1e9, 2)
FROM b""").fetchone()
print("cohort BDC rows=%s | rows with no issuer name=%s (abs fv $%sB)" % tot)

print("\nper CIK:")
print("  %-12s %-34s %7s %9s %9s %8s" %
      ("cik", "entity", "rows", "quarters", "fv_$B", "raw_id?"))
rows = con.execute("""
SELECT cik, ANY_VALUE(entity_name) AS entity, COUNT(*) AS n,
       COUNT(DISTINCT report_date) AS q,
       ROUND(SUM(ABS(fv))/1e9, 3) AS fv,
       ROUND(AVG(CASE WHEN COALESCE(TRIM(raw_id), '') <> '' THEN 1.0 ELSE 0 END), 2) AS has_raw
FROM b WHERE COALESCE(TRIM(issuer_name), '') = ''
GROUP BY cik ORDER BY n DESC""").fetchall()
for r in rows:
    print("  %-12s %-34s %7d %9d %9s %8s" % (r[0], str(r[1])[:34], r[2], r[3], r[4], r[5]))

print("\nis the name recoverable from the raw identifier or description?")
for r in con.execute("""
SELECT cik, raw_id, descr, report_date, ABS(fv) AS fv
FROM b WHERE COALESCE(TRIM(issuer_name), '') = ''
ORDER BY ABS(fv) DESC NULLS LAST LIMIT 12""").fetchall():
    print("  %s %s fv=%s\n     raw=%s\n     descr=%s"
          % (r[0], r[3], r[4], str(r[1])[:150], str(r[2])[:110]))

# Does the same fund report named rows in the same quarter?  If so the wrapper
# is dropping the name on a subset, which is a per-CIK parse gap rather than a
# filer that never discloses one.
print("\nnull-name rows vs named rows in the same CIK-quarter:")
for r in con.execute("""
SELECT cik, report_date,
       SUM(CASE WHEN COALESCE(TRIM(issuer_name), '') = '' THEN 1 ELSE 0 END) AS nulls,
       SUM(CASE WHEN COALESCE(TRIM(issuer_name), '') <> '' THEN 1 ELSE 0 END) AS named
FROM b GROUP BY cik, report_date
HAVING nulls > 0 ORDER BY nulls DESC LIMIT 12""").fetchall():
    print("  %s %s nulls=%d named=%d" % r)

con.execute(f"""COPY (
  SELECT cik, entity_name, report_date, row_id, raw_id, descr, fv, position_id
  FROM b WHERE COALESCE(TRIM(issuer_name), '') = '' ORDER BY cik, report_date
) TO '{(OUT / "e16_null_issuer_rows.csv").as_posix()}' (HEADER)""")
print("\nwrote %s" % OUT)
