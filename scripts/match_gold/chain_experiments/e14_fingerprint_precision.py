"""E14: precision control for the terms-fingerprint mechanism proposed in E13.

The control: take pairs the matcher already chained with a STRONG name tier
(B2_exact_name / B1b_position_key / A_within_filing).  Those are the closest thing to
ground truth available without adjudication (mg3 scores them at ~0.97+).  For each such
begin row, ignore the known answer and ask what the terms fingerprint alone would pick
among every row in the next quarter of the same CIK.  Agreement rate = the fingerprint
rule's precision where it fires; "abstain" = the block was not unique.

Also breaks the E13 candidate pool into diagnostic classes and reports agreement on
fields the fingerprint does NOT key on (interest rate, cost, lien, instrument type).

Read-only over data/output; writes to chain_experiments/out/e14/.

Usage: python scripts/match_gold/chain_experiments/e14_fingerprint_precision.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
HOLD = (REPO / "data/output/private_markets_holdings.csv").as_posix()
EDGES = (REPO / "data/output/position_id_edges.csv").as_posix()  # kept for reference; not used
OUT = Path(__file__).resolve().parent / "out" / "e14"
OUT.mkdir(parents=True, exist_ok=True)

PA_BAND = 1.05
SPREAD_TOL = 0.05
STRONG_TIERS = ("B2_exact_name", "B1b_position_key", "A_within_filing",
                "SUPP_B2_unique_exact_name", "SUPP_B1b_unique_position_key")

ciks = ",".join("'%s'" % e["cik"] for e in json.load(open(MAN))["entries"])
strong = ",".join("'%s'" % t for t in STRONG_TIERS)
con = duckdb.connect()
con.execute("PRAGMA threads=4")

con.execute(f"""
CREATE TABLE base AS
SELECT cik, row_id, position_id, report_date,
       (CAST(EXTRACT(year FROM TRY_CAST(report_date AS DATE)) AS INT) * 4
        + CAST(EXTRACT(quarter FROM TRY_CAST(report_date AS DATE)) AS INT)) AS qi,
       issuer_name, LOWER(TRIM(COALESCE(issuer_name, ''))) AS nm,
       TRY_CAST(fair_value AS DOUBLE) AS fv,
       TRY_CAST(cost AS DOUBLE) AS cost,
       TRY_CAST(principal_amount AS DOUBLE) AS pa,
       TRY_CAST(basis_spread AS DOUBLE) AS bs,
       TRY_CAST(interest_rate AS DOUBLE) AS ir,
       TRY_CAST(maturity_date AS DATE) AS mat,
       index_classification AS ic, instrument_type AS itype,
       lien_position AS lien, extracted_industry AS ind
FROM read_csv_auto('{HOLD}', all_varchar=true, sample_size=-1)
WHERE LOWER(source) = 'bdc' AND cik IN ({ciks})
""")

# --------------------------------------------------------------- control set
# position_id_edges.csv carries no row ids, so truth is defined structurally: a pair of
# rows sharing a position_id in adjacent quarters WITH an identical non-empty issuer
# name.  That is the B2_exact_name condition, the tier mg3 scores highest.  Caveat: the
# control is therefore drawn from name-stable positions; it measures the fingerprint's
# ability to pick the right row among same-terms rivals, not its behaviour on drift.
con.execute("""
CREATE TABLE ctl AS
SELECT b.row_id AS b_row, e.row_id AS e_row, 'exact_name_chained' AS tier,
       b.cik AS cik, b.qi AS qi
FROM base b JOIN base e
  ON e.cik = b.cik AND e.position_id = b.position_id AND e.qi = b.qi + 1
WHERE b.nm <> '' AND b.nm = e.nm
""")
n_ctl = con.execute("SELECT COUNT(*) FROM ctl").fetchone()[0]
print("control pairs (strong-tier, adjacent quarter): %d" % n_ctl, flush=True)

# what the fingerprint alone would pick for each control begin row
con.execute(f"""
CREATE TABLE fp AS
SELECT c.b_row, c.e_row AS truth_row, c.tier, c.cik,
       e.row_id AS fp_row
FROM ctl c
JOIN base b ON b.row_id = c.b_row
JOIN base e ON e.cik = b.cik AND e.qi = b.qi + 1
 AND b.mat IS NOT NULL AND e.mat = b.mat
 AND e.ic = b.ic
 AND b.pa IS NOT NULL AND e.pa IS NOT NULL AND b.pa > 0 AND e.pa > 0
 AND b.pa / e.pa BETWEEN 1.0/{PA_BAND} AND {PA_BAND}
 AND (b.bs IS NULL OR e.bs IS NULL OR ABS(b.bs - e.bs) <= {SPREAD_TOL})
""")
con.execute("""
CREATE TABLE fp_agg AS
SELECT b_row, ANY_VALUE(truth_row) AS truth_row, ANY_VALUE(tier) AS tier,
       COUNT(*) AS n_cand, ANY_VALUE(fp_row) AS only_row,
       MAX(CASE WHEN fp_row = truth_row THEN 1 ELSE 0 END) AS truth_in_cand
FROM fp GROUP BY b_row
""")
r = con.execute("""
SELECT COUNT(*) AS with_cand,
       SUM(CASE WHEN n_cand = 1 THEN 1 ELSE 0 END) AS unique_cand,
       SUM(CASE WHEN n_cand = 1 AND only_row = truth_row THEN 1 ELSE 0 END) AS unique_right,
       SUM(CASE WHEN n_cand = 1 AND only_row <> truth_row THEN 1 ELSE 0 END) AS unique_wrong,
       SUM(CASE WHEN n_cand > 1 THEN 1 ELSE 0 END) AS ambiguous,
       SUM(CASE WHEN n_cand > 1 AND truth_in_cand = 0 THEN 1 ELSE 0 END) AS amb_truth_absent
FROM fp_agg""").fetchone()
no_cand = n_ctl - r[0]
print("\nfingerprint replayed on the control set:")
print("  begin rows with no fingerprint candidate at all : %d (%.1f%%)"
      % (no_cand, 100.0 * no_cand / max(n_ctl, 1)))
print("  exactly one candidate (rule would fire)         : %d (%.1f%% of control)"
      % (r[1], 100.0 * r[1] / max(n_ctl, 1)))
print("     of those, it picks the strong-tier answer    : %d  (%.3f)"
      % (r[2], r[2] / max(r[1], 1)))
print("     of those, it picks a DIFFERENT row           : %d  (%.3f)"
      % (r[3], r[3] / max(r[1], 1)))
print("  more than one candidate (rule abstains)         : %d, truth not among them: %d"
      % (r[4], r[5]))

con.execute(f"""COPY (
  SELECT f.b_row, f.truth_row, f.only_row, f.tier, b.cik, b.issuer_name AS b_name,
         t.issuer_name AS truth_name, o.issuer_name AS fp_name,
         b.fv AS b_fv, t.fv AS truth_fv, o.fv AS fp_fv,
         b.pa AS b_pa, t.pa AS truth_pa, o.pa AS fp_pa, b.mat AS mat
  FROM fp_agg f JOIN base b ON b.row_id = f.b_row
  LEFT JOIN base t ON t.row_id = f.truth_row
  LEFT JOIN base o ON o.row_id = f.only_row
  WHERE f.n_cand = 1 AND f.only_row <> f.truth_row
) TO '{(OUT / "e14_fp_disagreements.csv").as_posix()}' (HEADER)""")

# precision by whether the fingerprint pick shares the name (the drift question)
r2 = con.execute("""
SELECT
  SUM(CASE WHEN nm_same AND is_right THEN 1 ELSE 0 END) AS same_right,
  SUM(CASE WHEN nm_same AND NOT is_right THEN 1 ELSE 0 END) AS same_wrong,
  SUM(CASE WHEN NOT nm_same AND is_right THEN 1 ELSE 0 END) AS diff_right,
  SUM(CASE WHEN NOT nm_same AND NOT is_right THEN 1 ELSE 0 END) AS diff_wrong
FROM (
  SELECT (b.nm = o.nm) AS nm_same, (f.only_row = f.truth_row) AS is_right
  FROM fp_agg f JOIN base b ON b.row_id = f.b_row JOIN base o ON o.row_id = f.only_row
  WHERE f.n_cand = 1)""").fetchone()
print("\n  split by whether the fingerprint pick has the same issuer name as the begin row:")
print("     same name : %d right / %d wrong (%.3f)"
      % (r2[0], r2[1], r2[0] / max(r2[0] + r2[1], 1)))
print("     diff name : %d right / %d wrong (%.3f)"
      % (r2[2], r2[3], r2[2] / max(r2[2] + r2[3], 1)))
print("     (the control's truth IS a same-name pair, so every different-name pick is")
print("      wrong by construction.  The number that matters is how often such a pick")
print("      happens at all, and whether an availability gate would suppress it.)")

# Availability gate: the proposed tier only runs on rows with NO same-name counterpart in
# the next quarter.  Re-score the control under that restriction.
con.execute("""
CREATE TABLE avail AS
SELECT f.b_row, f.n_cand, f.only_row, f.truth_row,
       (SELECT COUNT(*) FROM base e
        WHERE e.cik = b.cik AND e.qi = b.qi + 1 AND e.nm <> '' AND e.nm = b.nm) AS n_same_name
FROM fp_agg f JOIN base b ON b.row_id = f.b_row
""")
r3 = con.execute("""
SELECT SUM(CASE WHEN n_cand = 1 AND n_same_name = 0 THEN 1 ELSE 0 END) AS fires,
       SUM(CASE WHEN n_cand = 1 AND n_same_name = 0 AND only_row = truth_row THEN 1 ELSE 0 END) AS ok,
       SUM(CASE WHEN n_cand = 1 AND n_same_name > 0 AND only_row <> truth_row THEN 1 ELSE 0 END) AS supp
FROM avail""").fetchone()
print("\n  under the availability gate (fire only when the begin row has no same-name row")
print("  in the next quarter at all):")
print("     control rows where the tier would still fire : %d" % r3[0])
print("     of those, it picks the strong-tier answer    : %d (%.3f)"
      % (r3[1], r3[1] / max(r3[0], 1)))
print("     false positives suppressed by the gate       : %d of %d"
      % (r3[2], r2[1] + r2[3]))

# --------------------------------------------------------------- E13 pool classes
PAIRS = Path(__file__).resolve().parent / "out" / "e13" / "e13a_pairs.csv"
if PAIRS.exists():
    con.execute(f"""CREATE TABLE pool AS SELECT * FROM
        read_csv_auto('{PAIRS.as_posix()}', header=true, sample_size=-1)""")
    con.execute("""
    CREATE TABLE pool_cls AS
    SELECT p.*,
      CASE WHEN COALESCE(TRIM(p.b_nm), '') = '' OR COALESCE(TRIM(p.e_nm), '') = ''
             THEN 'null_issuer_name'
           WHEN p.name_same AND COALESCE(p.b_fv, 0) <= 0 THEN 'same_name_zero_or_neg_begin_fv'
           WHEN p.name_same THEN 'same_name_other'
           WHEN p.name_contained THEN 'wrapper_containment'
           ELSE 'unrelated_names' END AS cls,
      (b.ir IS NOT NULL AND e.ir IS NOT NULL AND ABS(b.ir - e.ir) <= 0.25) AS ir_agree,
      (b.lien IS NOT DISTINCT FROM e.lien) AS lien_agree,
      (b.itype IS NOT DISTINCT FROM e.itype) AS itype_agree,
      (b.ind IS NOT DISTINCT FROM e.ind) AS ind_agree
    FROM pool p JOIN base b ON b.row_id = p.b_row JOIN base e ON e.row_id = p.e_row
    """)
    print("\nE13 candidate pool by class (fields below are NOT part of the fingerprint):")
    print("  %-32s %7s %10s %7s %7s %7s %7s" %
          ("class", "pairs", "fv_$B", "rate", "lien", "itype", "industry"))
    for row in con.execute("""
        SELECT cls, COUNT(*) AS n, ROUND(SUM(e_fv)/1e9, 2) AS fv,
               ROUND(AVG(CASE WHEN ir_agree THEN 1.0 ELSE 0 END), 3) AS ir,
               ROUND(AVG(CASE WHEN lien_agree THEN 1.0 ELSE 0 END), 3) AS lien,
               ROUND(AVG(CASE WHEN itype_agree THEN 1.0 ELSE 0 END), 3) AS it,
               ROUND(AVG(CASE WHEN ind_agree THEN 1.0 ELSE 0 END), 3) AS ind
        FROM pool_cls GROUP BY 1 ORDER BY n DESC""").fetchall():
        print("  %-32s %7d %10s %7s %7s %7s %7s" % row)
    con.execute(f"""COPY (SELECT * FROM pool_cls ORDER BY e_fv DESC)
                    TO '{(OUT / "e14_pool_classified.csv").as_posix()}' (HEADER)""")

print("\nwrote %s" % OUT)
