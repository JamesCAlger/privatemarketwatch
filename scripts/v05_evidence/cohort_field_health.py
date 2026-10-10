"""Read-only: per fund, field defects no finding rule reports, from the latest sandbox that holds the fund.

    python scripts/v05_evidence/cohort_field_health.py [label ...]

Labels are read latest first; a fund is taken from the first label that has it. Columns, for
published loan rows (asset_category LOAN, not underlying_schedule), all quarters and the latest:
  ref_guess   share of rows whose reference rate is inferred from the report date
  no_rate     share of rows with no interest_rate
  pik_only    rows with a PIK rate and no interest_rate
  no_mat      share of rows with no maturity date
  names       quarters where distinct issuers exceed 90 pct of rows (issuer not split from the label), of all quarters
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
LABELS = sys.argv[1:] or ["k1b", "l13a", "l12a", "l11a", "l10b", "l9b", "l8b", "l7b", "l6b", "l5b", "l4c", "l3d",
                           "n5j", "final5", "s2a", "s1c"]
con = duckdb.connect(config={"threads": 2, "memory_limit": "3GB"})
seen: set[str] = set()
print("cik | label | rows | ref_guess all | ref_guess latest | no_rate all | no_rate latest | pik_only latest | no_mat all | no_mat latest | names bad/quarters | fund")
for label in LABELS:
    path = REPO / "scratch/fund_sandbox" / label / "output/private_markets_holdings.parquet"
    if not path.exists():
        continue
    con.execute(f"""CREATE OR REPLACE TEMP TABLE h AS SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS q,
            asset_category AS cat, issuer_name, entity_name, coalesce(CAST(reference_rate_source AS VARCHAR),'') AS ref_src,
            TRY_CAST(interest_rate AS DOUBLE) AS rate, TRY_CAST(pik_rate AS DOUBLE) AS pik, CAST(maturity_date AS VARCHAR) AS mat
        FROM read_parquet('{path.as_posix()}') WHERE coalesce(accounting_record_class,'') <> 'underlying_schedule' AND source = 'bdc'""")
    rows = con.execute("""
        WITH latest AS (SELECT cik, max(q) AS q FROM h GROUP BY 1),
        names AS (SELECT cik, count(*) FILTER (WHERE issuers > 0.9 * n AND n >= 20) AS bad, count(*) AS quarters
                  FROM (SELECT cik, q, count(*) AS n, count(DISTINCT issuer_name) AS issuers FROM h GROUP BY 1, 2) GROUP BY 1),
        loans AS (SELECT h.*, (h.q = latest.q) AS is_latest FROM h JOIN latest USING (cik) WHERE cat = 'LOAN')
        SELECT cik, count(*),
               round(100.0 * count(*) FILTER (WHERE ref_src LIKE 'inferred_%') / count(*), 0),
               round(100.0 * count(*) FILTER (WHERE ref_src LIKE 'inferred_%' AND is_latest) / greatest(count(*) FILTER (WHERE is_latest), 1), 0),
               round(100.0 * count(*) FILTER (WHERE rate IS NULL) / count(*), 0),
               round(100.0 * count(*) FILTER (WHERE rate IS NULL AND is_latest) / greatest(count(*) FILTER (WHERE is_latest), 1), 0),
               count(*) FILTER (WHERE rate IS NULL AND pik > 0 AND is_latest),
               round(100.0 * count(*) FILTER (WHERE mat IS NULL OR mat = '') / count(*), 0),
               round(100.0 * count(*) FILTER (WHERE (mat IS NULL OR mat = '') AND is_latest) / greatest(count(*) FILTER (WHERE is_latest), 1), 0),
               any_value(names.bad) || '/' || any_value(names.quarters), any_value(entity_name)[:34]
        FROM loans JOIN names USING (cik) GROUP BY cik ORDER BY cik""").fetchall()
    for row in rows:
        if row[0] in seen:
            continue
        seen.add(row[0])
        print("   " + " | ".join([row[0], label] + [str(v) for v in row[1:]]))
print("funds:", len(seen))
