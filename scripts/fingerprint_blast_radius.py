"""Temp (delete after): post fingerprint + blast-radius diff vs baseline."""
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output" / "b2_expansion_exp_20260813"
P = (ROOT / "data" / "output" / "private_markets_holdings.parquet").as_posix()

con = duckdb.connect()
con.execute(
    f"""
    COPY (
      SELECT
        lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') AS cik,
        CAST(report_date AS VARCHAR) AS report_date,
        COUNT(*) AS n_rows,
        ROUND(SUM(TRY_CAST(fair_value AS DOUBLE)), 2) AS fv_sum,
        ROUND(SUM(TRY_CAST(cost AS DOUBLE)), 2) AS cost_sum,
        ROUND(SUM(TRY_CAST(principal_amount AS DOUBLE)), 2) AS principal_sum,
        ROUND(SUM(TRY_CAST(interest_rate AS DOUBLE)), 4) AS rate_sum,
        ROUND(SUM(TRY_CAST(pik_rate AS DOUBLE)), 4) AS pik_sum,
        ROUND(SUM(TRY_CAST(basis_spread AS DOUBLE)), 4) AS spread_sum,
        SUM(CASE WHEN asset_class IS NULL THEN 1 ELSE 0 END) AS n_null_asset_class,
        COUNT(DISTINCT asset_class) AS n_asset_classes,
        COUNT(DISTINCT index_classification) AS n_index_classes
      FROM read_parquet('{P}')
      GROUP BY 1, 2
    ) TO '{(OUT / "fingerprint_post.csv").as_posix()}' (FORMAT CSV, HEADER)
    """
)
con.close()

base = pd.read_csv(OUT / "fingerprint_baseline.csv", dtype={"cik": str})
post = pd.read_csv(OUT / "fingerprint_post.csv", dtype={"cik": str})
m = base.merge(post, on=["cik", "report_date"], how="outer",
               suffixes=("_b", "_p"), indicator=True)
print(f"cells: baseline {len(base)}, post {len(post)}, only-one-side: "
      f"{int((m['_merge'] != 'both').sum())}")

metrics = ["n_rows", "fv_sum", "cost_sum", "principal_sum", "rate_sum", "pik_sum",
           "spread_sum", "n_null_asset_class", "n_asset_classes", "n_index_classes"]
changed_cells = set()
for met in metrics:
    a = pd.to_numeric(m[f"{met}_b"], errors="coerce")
    b = pd.to_numeric(m[f"{met}_p"], errors="coerce")
    tol = 0.01 if met.endswith("_sum") else 0
    neq = (~(a.isna() & b.isna())) & ((a - b).abs().fillna(1e18) > tol)
    n = int(neq.sum())
    if n:
        ciks = sorted(m.loc[neq, "cik"].unique())
        print(f"{met}: {n} changed CIK-quarter cells across {len(ciks)} CIKs")
        for _, r in m.loc[neq].head(4).iterrows():
            print(f"    {r['cik']} {r['report_date']}: {r[f'{met}_b']} -> {r[f'{met}_p']}")
        changed_cells |= set(m.loc[neq, "cik"].unique())

promoted = {p.parent.name for p in
            (ROOT / "data" / "overrides" / "agent_b2_corrections").glob("*/*.json")}
unexpected = changed_cells - promoted
print(f"\nCIKs with ANY metric change: {len(changed_cells)}")
print(f"CIKs with promoted corrections: {len(promoted)}")
print(f"CHANGED CIKS WITHOUT A PROMOTED CORRECTION (blast radius): {sorted(unexpected)}")
fvb = pd.to_numeric(m["fv_sum_b"], errors="coerce").fillna(0).sum()
fvp = pd.to_numeric(m["fv_sum_p"], errors="coerce").fillna(0).sum()
print(f"total FV: baseline {fvb:,.0f} vs post {fvp:,.0f} (delta {fvp - fvb:,.0f})")
