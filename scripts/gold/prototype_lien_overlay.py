"""PROTOTYPE (read-only): contextRef/raw-member-anchored overlay of the iXBRL
field-status artifact onto production, scoped to BCRED 2025-12-31.

Shows that the bridge already captured lien/maturity for ~2,800 positions, and that
the only reason production has ~709 is the overlay joins on the STRIPPED
bdc_investment_identifier. Re-joining on the FULL XBRL member -- which both sides
preserve (production in bdc_dimensions_raw, the artifact in raw_id_lower) -- recovers
the rest. No writes; measures before/after fill.
"""
from __future__ import annotations
import duckdb

CIK = "0001803498"   # BCRED
RD = "2025-12-31"
P = "data/output/private_markets_holdings.parquet"
F = "data/output/bdc_ixbrl_field_status.csv"

con = duckdb.connect()

# Production BCRED positions. Two candidate join keys:
#   id_key  = _raw_id_lower(bdc_investment_identifier)         <- what the CURRENT overlay uses (stripped)
#   mem_key = _raw_id_lower(member from bdc_dimensions_raw)    <- the FULL XBRL member (the fix)
con.execute(f"""
CREATE TEMP VIEW prod AS
SELECT
  trim(regexp_replace(lower(coalesce(bdc_investment_identifier,'')), '\\s+', ' ', 'g')) AS id_key,
  trim(regexp_replace(lower(regexp_replace(coalesce(bdc_dimensions_raw,''),
       '^[^=]*=', '')), '\\s+', ' ', 'g')) AS mem_key,
  lien_position, maturity_date, bdc_investment_identifier AS ident,
  try_cast(fair_value AS DOUBLE) AS fv
FROM read_parquet('{P}')
WHERE upper(source) LIKE 'BDC%' AND report_date='{RD}'
  AND lpad(cast(cast(cik AS BIGINT) AS VARCHAR),10,'0')='{CIK}'
""")

# Artifact (current-period rows only), one row per key, value-status only.
con.execute(f"""
CREATE TEMP VIEW art AS
SELECT * FROM (
  SELECT trim(regexp_replace(lower(coalesce(raw_id_lower,'')), '\\s+', ' ', 'g')) AS key,
         CASE WHEN lien_status='value' THEN lien_position END AS br_lien,
         CASE WHEN maturity_status='value' THEN maturity_date END AS br_mat,
         row_number() OVER (PARTITION BY trim(regexp_replace(lower(coalesce(raw_id_lower,'')), '\\s+', ' ', 'g'))
             ORDER BY (lien_status='value') DESC, (maturity_status='value') DESC) rn
  FROM read_csv_auto('{F}', all_varchar=true)
  WHERE lpad(cast(try_cast(cik AS BIGINT) AS VARCHAR),10,'0')='{CIK}' AND report_date='{RD}'
    AND coalesce(anchor_class,'') <> 'comparative'
) WHERE rn=1
""")

n_prod = con.execute("SELECT count(*) FROM prod").fetchone()[0]


def fill(joincol: str) -> dict:
    r = con.execute(f"""
      WITH j AS (
        SELECT p.*, a.br_lien, a.br_mat,
               (a.key IS NOT NULL) AS matched
        FROM prod p LEFT JOIN art a ON p.{joincol}=a.key)
      SELECT
        count(*) FILTER (WHERE matched) AS matched,
        count(*) FILTER (WHERE lien_position IS NOT NULL AND lien_position<>'') AS lien_before,
        count(*) FILTER (WHERE (lien_position IS NOT NULL AND lien_position<>'')
                              OR br_lien IS NOT NULL) AS lien_after,
        count(*) FILTER (WHERE maturity_date IS NOT NULL AND maturity_date<>'') AS mat_before,
        count(*) FILTER (WHERE (maturity_date IS NOT NULL AND maturity_date<>'')
                              OR br_mat IS NOT NULL) AS mat_after
      FROM j""").fetchone()
    return dict(matched=r[0], lien_before=r[1], lien_after=r[2], mat_before=r[3], mat_after=r[4])


cur = fill("id_key")    # current overlay key (stripped identifier)
fix = fill("mem_key")   # proposed key (full XBRL member)

print(f"BCRED {RD}: {n_prod} production positions\n")
print(f"{'join key':28s} {'matched':>8s} {'lien':>14s} {'maturity':>14s}")
print(f"{'-'*28} {'-'*8} {'-'*14} {'-'*14}")
print(f"{'(current) stripped identifier':28s} {cur['matched']:>8d} "
      f"{cur['lien_before']:>5d}->{cur['lien_after']:<7d} {cur['mat_before']:>5d}->{cur['mat_after']:<7d}")
print(f"{'(fix) full XBRL member':28s} {fix['matched']:>8d} "
      f"{fix['lien_before']:>5d}->{fix['lien_after']:<7d} {fix['mat_before']:>5d}->{fix['mat_after']:<7d}")
print(f"\nmatch rate: current {100*cur['matched']/n_prod:.0f}%  ->  fix {100*fix['matched']/n_prod:.0f}%")
print(f"lien recovered:     {fix['lien_after']-cur['lien_before']:+d}  "
      f"({100*cur['lien_before']/n_prod:.0f}% -> {100*fix['lien_after']/n_prod:.0f}% of positions)")
print(f"maturity recovered: {fix['mat_after']-cur['mat_before']:+d}  "
      f"({100*cur['mat_before']/n_prod:.0f}% -> {100*fix['mat_after']/n_prod:.0f}% of positions)")
