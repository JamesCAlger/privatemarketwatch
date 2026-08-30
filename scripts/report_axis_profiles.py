"""Axis-profile layer report (row-provenance spec step 2, 2026-08-30).

For each requested CIK-quarter, summarize unified BDC holdings by axis_profile:
row count, FV sum, and share of the quarter. This is the deterministic
replacement for the hand forensics that diagnosed 1812554/1838126 -- and the
validation gate for the staging enrichment (the known funds must reproduce the
hand-measured numbers before any layer_exclusion leaf is authored).

Cache-only, read-only. ASCII-only output.

Usage:
  python scripts/report_axis_profiles.py --cik 0001838126 --quarter 2026-03-31
  python scripts/report_axis_profiles.py --validate-known
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config

HOLDINGS = config.OUTPUT_DIR / "private_markets_holdings.parquet"

# Spec section-1 hand-measured expectations (2026-08-30 forensics). Bare-axis
# bucket = axis_profile exactly 'investmentidentifieraxis'.
KNOWN = [
    # cik, quarter, expected bare rows, expected bare FV (dollars), abs tolerance
    ("0001838126", "2026-03-31", 23, 1.611219e9, 0.01e9),
    ("0001812554", "2026-03-31", 14, 1.364937e9, 0.01e9),
]


def profile_report(cik: str, quarter: str) -> list[tuple]:
    con = duckdb.connect()
    return con.execute(
        f"""
        SELECT axis_profile, COUNT(*) n,
               SUM(TRY_CAST(fair_value AS DOUBLE)) fv,
               ROUND(100.0 * SUM(TRY_CAST(fair_value AS DOUBLE))
                     / SUM(SUM(TRY_CAST(fair_value AS DOUBLE))) OVER (), 2) fv_pct
        FROM read_parquet('{HOLDINGS.as_posix()}')
        WHERE lpad(CAST(cik AS VARCHAR), 10, '0') = ?
          AND CAST(report_date AS VARCHAR) = ?
          AND bdc_dimensions_raw IS NOT NULL
        GROUP BY 1 ORDER BY 3 DESC
        """, [cik, quarter]).fetchall()


def validate_known() -> int:
    failures = 0
    for cik, quarter, exp_n, exp_fv, tol in KNOWN:
        rows = profile_report(cik, quarter)
        bare = next(((n, fv) for p, n, fv, _ in rows if p == "investmentidentifieraxis"),
                    (0, 0.0))
        ok = bare[0] == exp_n and abs(float(bare[1] or 0) - exp_fv) <= tol
        status = "OK " if ok else "FAIL"
        print(f"[{status}] {cik} {quarter} bare-axis: {bare[0]} rows "
              f"fv={float(bare[1] or 0):,.0f} (expected {exp_n} rows ~{exp_fv:,.0f})")
        failures += 0 if ok else 1
    return failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Axis-profile layer report.")
    ap.add_argument("--cik")
    ap.add_argument("--quarter")
    ap.add_argument("--validate-known", action="store_true")
    args = ap.parse_args(argv)
    if args.validate_known:
        n = validate_known()
        print("VALIDATION", "PASS" if n == 0 else f"FAIL ({n})")
        return 0 if n == 0 else 1
    if not (args.cik and args.quarter):
        ap.error("--cik and --quarter required (or --validate-known)")
    cik = args.cik.zfill(10)
    for p, n, fv, pct in profile_report(cik, args.quarter):
        print(f"{n:5d}  {float(fv or 0):>16,.0f}  {pct:6.2f}%  {p[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
