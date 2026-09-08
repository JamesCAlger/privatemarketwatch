"""E15: two guard-level diagnostics behind the remaining completeness gap.

(1) Match universe.  `match_positions` builds its universe with
    `fair_value IS NOT NULL AND fair_value != 0`, so a row carrying zero fair value
    can never be chained -- it is a singleton by construction, not by matcher failure.
    Size that population, and the negative-fair-value population that IS in the universe
    but is vetoed by the signed FV-ratio guard `b.fv / e.fv BETWEEN 1/50 AND 50`.

(2) The CONFIRMED gold pairs that the contested promotion lost (linked with the flag
    off, not linked with it on).  Print the field deltas that the new vetoes key on, to
    say whether the amendment escape is too tight.

Read-only over data/output; writes to chain_experiments/out/e15/.

Usage: python scripts/match_gold/chain_experiments/e15_guards.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
HOLD = (REPO / "data/output/private_markets_holdings.csv").as_posix()
AB = REPO / "scratch/2026-09-07_chain_experiments/ab_new/ab_pairs.csv"
OUT = Path(__file__).resolve().parent / "out" / "e15"
OUT.mkdir(parents=True, exist_ok=True)

ciks = ",".join("'%s'" % e["cik"] for e in json.load(open(MAN))["entries"])
con = duckdb.connect()
con.execute("PRAGMA threads=4")

con.execute(f"""
CREATE TABLE b AS
SELECT cik, row_id, position_id, report_date, issuer_name,
       LOWER(TRIM(COALESCE(issuer_name, ''))) AS nm,
       TRY_CAST(fair_value AS DOUBLE) AS fv,
       TRY_CAST(principal_amount AS DOUBLE) AS pa,
       TRY_CAST(basis_spread AS DOUBLE) AS bs,
       TRY_CAST(maturity_date AS DATE) AS mat,
       COALESCE(asset_class, '') AS ac,
       COALESCE(index_classification, '') AS ic,
       instrument_type AS itype,
       (CAST(EXTRACT(year FROM TRY_CAST(report_date AS DATE)) AS INT) * 4
        + CAST(EXTRACT(quarter FROM TRY_CAST(report_date AS DATE)) AS INT)) AS qi
FROM read_csv_auto('{HOLD}', all_varchar=true, sample_size=-1)
WHERE LOWER(source) = 'bdc' AND cik IN ({ciks})
""")

print("=" * 78)
print("(1) MATCH UNIVERSE")
print("=" * 78)
r = con.execute("""
SELECT COUNT(*) AS rows,
  SUM(CASE WHEN fv IS NULL THEN 1 ELSE 0 END) AS fv_null,
  SUM(CASE WHEN fv = 0 THEN 1 ELSE 0 END) AS fv_zero,
  SUM(CASE WHEN fv < 0 THEN 1 ELSE 0 END) AS fv_neg,
  SUM(CASE WHEN ac IN ('CASH','DERIVATIVE') OR ic = 'CASH' THEN 1 ELSE 0 END) AS cash_deriv
FROM b""").fetchone()
import inspect  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, str(REPO))
from pipeline import position_matching as _pm  # noqa: E402

_ZERO_FV_EXCLUDED = ("TRY_CAST(fair_value AS DOUBLE) != 0"
                     in inspect.getsource(_pm.match_positions))
# The universe rule is read from the module rather than hard-coded, so this
# report cannot keep describing an exclusion the matcher no longer applies.
excl_sql = ("ac IN ('CASH','DERIVATIVE') OR ic = 'CASH' OR fv IS NULL"
            + (" OR fv = 0" if _ZERO_FV_EXCLUDED else ""))
excl = con.execute(f"SELECT COUNT(*) FROM b WHERE {excl_sql}").fetchone()[0]
print("cohort BDC rows                     : %d" % r[0])
print("  fair value NULL                   : %d" % r[1])
print("  fair value exactly 0              : %d  (%.1f%% of rows)" % (r[2], 100.0 * r[2] / r[0]))
print("  fair value negative               : %d" % r[3])
print("  cash / derivative                 : %d" % r[4])
print("excluded from the match universe    : %d  (%.1f%%)  [zero-FV excluded: %s]"
      % (excl, 100.0 * excl / r[0], _ZERO_FV_EXCLUDED))

sing = con.execute(f"""
WITH c AS (SELECT position_id, COUNT(*) AS n FROM b GROUP BY 1)
SELECT SUM(CASE WHEN c.n = 1 THEN 1 ELSE 0 END) AS singletons,
       SUM(CASE WHEN c.n = 1 AND ({excl_sql.replace('ac ', 'b.ac ').replace('ic ', 'b.ic ').replace('fv ', 'b.fv ')})
           THEN 1 ELSE 0 END) AS forced,
       COUNT(*) AS rows
FROM b JOIN c USING (position_id)""").fetchone()
print("\nsingleton rows                      : %d (%.1f%% of cohort rows)"
      % (sing[0], 100.0 * sing[0] / sing[2]))
print("  of which cannot chain by design   : %d (%.1f%% of singletons)"
      % (sing[1], 100.0 * sing[1] / max(sing[0], 1)))
print("  remaining, matcher-attributable   : %d (%.1f%% of cohort rows)"
      % (sing[0] - sing[1], 100.0 * (sing[0] - sing[1]) / sing[2]))
zs = con.execute("""
WITH c AS (SELECT position_id, COUNT(*) AS n FROM b GROUP BY 1)
SELECT SUM(CASE WHEN b.fv = 0 THEN 1 ELSE 0 END) AS zero_rows,
       SUM(CASE WHEN b.fv = 0 AND c.n > 1 THEN 1 ELSE 0 END) AS zero_chained
FROM b JOIN c USING (position_id)""").fetchone()
print("  zero-FV rows now chained          : %d of %d (%.1f%%)"
      % (zs[1], zs[0], 100.0 * zs[1] / max(zs[0], 1)))

# how many zero-FV rows have an obvious same-name continuation next quarter?
z = con.execute("""
SELECT COUNT(*) AS zero_rows_with_named_twin,
       COUNT(DISTINCT x.cik) AS ciks
FROM b x
WHERE x.fv = 0 AND x.nm <> ''
  AND EXISTS (SELECT 1 FROM b y
              WHERE y.cik = x.cik AND y.qi = x.qi + 1 AND y.nm = x.nm
                AND y.fv IS NOT NULL AND y.fv <> 0)""").fetchone()
print("\nzero-FV rows with a same-name, non-zero-FV row in the next quarter: %d "
      "across %d CIKs" % z)

# sign-flip pairs: in the universe, but vetoed by the signed FV ratio guard
sf = con.execute("""
SELECT COUNT(*) AS pairs, ROUND(SUM(ABS(e.fv))/1e9, 2) AS fv_busd
FROM b bb JOIN b e
  ON e.cik = bb.cik AND e.qi = bb.qi + 1 AND e.nm = bb.nm AND bb.nm <> ''
 AND bb.fv IS NOT NULL AND e.fv IS NOT NULL AND bb.fv <> 0 AND e.fv <> 0
 AND (bb.fv / e.fv) < 0
 AND bb.position_id <> e.position_id""").fetchone()
print("same-name adjacent-quarter pairs with opposite FV signs, not chained: %d ($%sB)" % sf)

con.execute(f"""COPY (
  SELECT cik, COUNT(*) AS zero_fv_rows, COUNT(DISTINCT report_date) AS quarters
  FROM b WHERE fv = 0 GROUP BY 1 ORDER BY zero_fv_rows DESC
) TO '{(OUT / "e15_zero_fv_per_cik.csv").as_posix()}' (HEADER)""")
print("\ntop CIKs by zero-FV rows:")
for row in con.execute("""SELECT cik, COUNT(*) AS n, COUNT(DISTINCT report_date) AS q
                          FROM b WHERE fv = 0 GROUP BY 1 ORDER BY n DESC LIMIT 8""").fetchall():
    print("    %s rows=%5d quarters=%d" % row)

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("(2) CONFIRMED GOLD PAIRS LOST BY THE CONTESTED PROMOTION")
print("=" * 78)
if not AB.exists():
    print("missing %s -- run ab_gold_percik.py first" % AB)
    raise SystemExit(0)

con.execute(f"""CREATE TABLE ab AS SELECT * FROM
    read_csv_auto('{AB.as_posix()}', all_varchar=true, sample_size=-1)""")
lost = con.execute("""
SELECT a.batch, a.tier, a.cik, a.row_a, a.row_b,
       x.issuer_name AS a_name, y.issuer_name AS b_name,
       x.fv AS a_fv, y.fv AS b_fv, x.pa AS a_pa, y.pa AS b_pa,
       x.bs AS a_bs, y.bs AS b_bs, x.mat AS a_mat, y.mat AS b_mat,
       CASE WHEN x.pa > 0 AND y.pa > 0 THEN ROUND(x.pa / y.pa, 4) END AS pa_ratio,
       CASE WHEN x.mat IS NULL OR y.mat IS NULL THEN NULL
            ELSE ABS(DATEDIFF('day', x.mat, y.mat)) END AS mat_gap_days
FROM ab a LEFT JOIN b x ON x.row_id = a.row_a LEFT JOIN b y ON y.row_id = a.row_b
WHERE a.kind = 'CONFIRMED' AND LOWER(a.linked_A) = 'true' AND LOWER(a.linked_B) = 'false'
ORDER BY a.tier, a.cik""").fetchdf()
print("lost CONFIRMED pairs: %d" % len(lost))
if len(lost):
    con.register("lost", lost)
    print("\nwhy the new rules would reject them:")
    print(con.execute("""
      SELECT
        SUM(CASE WHEN mat_gap_days > 0 THEN 1 ELSE 0 END) AS maturity_changed,
        SUM(CASE WHEN mat_gap_days > 0 AND (pa_ratio IS NULL
             OR pa_ratio NOT BETWEEN 1/1.02 AND 1.02) THEN 1 ELSE 0 END) AS mat_and_pa_moved,
        SUM(CASE WHEN mat_gap_days > 0 AND a_bs IS NOT NULL AND b_bs IS NOT NULL
             AND ABS(a_bs - b_bs) > 0.01 THEN 1 ELSE 0 END) AS mat_and_spread_moved,
        SUM(CASE WHEN mat_gap_days = 0 OR mat_gap_days IS NULL THEN 1 ELSE 0 END)
             AS maturity_not_the_cause
      FROM lost""").fetchdf().to_string(index=False))
    print("\nper tier: " + ", ".join(
        "%s=%d" % (k, v) for k, v in lost["tier"].value_counts().items()))
    cols = ["batch", "tier", "cik", "a_name", "b_name", "a_fv", "b_fv",
            "pa_ratio", "a_bs", "b_bs", "mat_gap_days"]
    print("\n" + lost[cols].head(20).to_string(index=False))
    lost.to_csv(OUT / "e15_lost_confirmed.csv", index=False)
print("\nwrote %s" % OUT)
