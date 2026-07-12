"""Wave-1 per-CIK parity check (gap 1, spec section 8.1).

For each promoted CIK, the trial's corrected output
(data/output/agent_investigate/<cik>/corrected_holdings.<cik>.csv -- the frame B3
gate-PASSed) must equal the post-rebuild PRODUCTION unified holdings for that CIK,
measured in gate-counted conservation terms per quarter: row count and fair-value sum
over rows with bdc_dimensions_raw present, excluding CASH (the exact quantity the gate
certifies). FV tolerance $1 (CSV float round-trip); row counts exact.

Run AFTER promoting rules and rebuilding production. Writes
data/output/agent_investigate/wave1_parity.csv; exit 0 iff every checked CIK matches.
Read-only; cache-only; ASCII-only.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from pipeline.agent_promoted import normalize_cik10

INVESTIGATE_BASE = config.OUTPUT_DIR / "agent_investigate"
OUT_FILE = INVESTIGATE_BASE / "wave1_parity.csv"
FV_TOL = 1.0

COLUMNS = ["cik", "report_date", "trial_rows", "prod_rows", "trial_fv", "prod_fv",
           "fv_delta", "status"]


def _gate_counted(df: pd.DataFrame) -> pd.DataFrame:
    """(report_date, rows, fv) per quarter under conservation gate semantics."""
    sub = df[df["bdc_dimensions_raw"].notna()] if "bdc_dimensions_raw" in df.columns else df
    if "asset_category" in sub.columns:
        sub = sub[sub["asset_category"].astype(str).str.upper() != "CASH"]
    fv = pd.to_numeric(sub["fair_value"], errors="coerce").fillna(0)
    g = pd.DataFrame({"report_date": sub["report_date"].astype(str), "fv": fv})
    out = g.groupby("report_date").agg(rows=("fv", "size"), fv=("fv", "sum")).reset_index()
    return out


def production_by_quarter(ciks: list[str]) -> dict[tuple[str, str], tuple[int, float]]:
    """{(cik10, report_date): (rows, fv)} for the promoted CIKs from production."""
    p = (config.UNIFIED_HOLDINGS_PARQUET_FILE
         if config.UNIFIED_HOLDINGS_PARQUET_FILE.exists() else config.UNIFIED_HOLDINGS_FILE)
    read = "read_parquet" if str(p).endswith(".parquet") else "read_csv_auto"
    cik_list = ",".join(f"'{c}'" for c in ciks)
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
               CAST(report_date AS VARCHAR) AS report_date,
               COUNT(*) AS n, SUM(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0)) AS fv
        FROM {read}('{p.as_posix()}')
        WHERE bdc_dimensions_raw IS NOT NULL
          AND upper(COALESCE(CAST(asset_category AS VARCHAR), '')) <> 'CASH'
          AND LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')
              IN ({cik_list})
        GROUP BY 1, 2
    """).fetchall()
    con.close()
    return {(r[0], r[1]): (int(r[2]), float(r[3])) for r in rows}


def main(argv: list[str] | None = None) -> int:
    ciks = sorted(argv or [])
    if not ciks:
        # default: every CIK with a promoted rules dir
        base = config.AGENT_INVESTIGATE_RULES_DIR
        ciks = sorted(normalize_cik10(d.name) for d in base.glob("*") if d.is_dir()) \
            if base.exists() else []
    if not ciks:
        print("no promoted CIKs to check")
        return 1

    prod = production_by_quarter(ciks)
    results: list[dict] = []
    n_mismatch = 0
    for cik in ciks:
        trial_path = INVESTIGATE_BASE / str(int(cik)) / f"corrected_holdings.{int(cik)}.csv"
        if not trial_path.exists():
            results.append({"cik": cik, "report_date": "", "trial_rows": "", "prod_rows": "",
                            "trial_fv": "", "prod_fv": "", "fv_delta": "",
                            "status": "no_trial_corrected_holdings"})
            n_mismatch += 1
            continue
        trial = _gate_counted(pd.read_csv(trial_path, low_memory=False))
        seen = set()
        for _, t in trial.iterrows():
            rd = str(t["report_date"])
            seen.add(rd)
            pn, pfv = prod.get((cik, rd), (0, 0.0))
            delta = float(t["fv"]) - pfv
            ok = (int(t["rows"]) == pn) and (abs(delta) <= FV_TOL)
            if not ok:
                n_mismatch += 1
            results.append({"cik": cik, "report_date": rd, "trial_rows": int(t["rows"]),
                            "prod_rows": pn, "trial_fv": round(float(t["fv"]), 2),
                            "prod_fv": round(pfv, 2), "fv_delta": round(delta, 2),
                            "status": "match" if ok else "MISMATCH"})
        # quarters present in production but absent from the trial frame
        for (c, rd), (pn, pfv) in sorted(prod.items()):
            if c == cik and rd not in seen:
                n_mismatch += 1
                results.append({"cik": cik, "report_date": rd, "trial_rows": 0,
                                "prod_rows": pn, "trial_fv": 0.0, "prod_fv": round(pfv, 2),
                                "fv_delta": round(-pfv, 2), "status": "MISMATCH"})

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(results)

    n_quarters = sum(1 for r in results if r["report_date"])
    print(f"parity: {len(ciks)} CIKs, {n_quarters} CIK-quarters checked, "
          f"{n_mismatch} mismatches -> {OUT_FILE}")
    for r in results:
        if r["status"] != "match":
            print(f"  {r['status']}: {r['cik']} {r['report_date']} "
                  f"rows {r['trial_rows']}/{r['prod_rows']} fv_delta {r['fv_delta']}")
    return 0 if n_mismatch == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
