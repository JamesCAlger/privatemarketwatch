"""Measure the worst-case position_key churn a ``canonical_strip_re`` edit
causes (Q2 gate for the stable position_id registry).

``canonical_strip_re`` is the only wrapper rule that rewrites the identifier
feeding ``position_key`` (pipeline/bdc_xbrl_wrapper.py:365-366: it is applied as
``re.sub("", identifier)``).  So the count of current rows whose identifier the
rule *moves* is exactly the number of ``position_key`` values that would differ
if the rule were added/removed -- i.e. the chain-membership perturbation a
wrapper edit on that CIK would cause.

Read-only: reads the current holdings + wrapper JSONs.  No writes, no network.

Usage:  python scripts/measure_position_key_drift.py
"""

from __future__ import annotations

import glob
import json
import os
import re

import duckdb

HOLDINGS = "data/output/private_markets_holdings.csv"
WRAPPER_DIR = "data/overrides/bdc_xbrl_wrappers"


def main() -> None:
    # Load canonical_strip_re per CIK.
    rules: dict[str, str] = {}
    for f in glob.glob(os.path.join(WRAPPER_DIR, "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        canon = (d.get("dispatch") or {}).get("canonical_strip_re")
        if canon:
            cik = str(d.get("cik", os.path.basename(f)[:-5])).zfill(10)
            rules[cik] = canon
    print(f"wrappers with canonical_strip_re: {len(rules)}")

    con = duckdb.connect()
    con.execute(
        f"""CREATE VIEW h AS SELECT
          LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') AS cik,
          CAST(bdc_investment_identifier AS VARCHAR) AS rawid
        FROM read_csv_auto('{HOLDINGS}', header=true, all_varchar=true)
        WHERE source='bdc' AND report_date >= '2022-10-01'
          AND TRIM(CAST(bdc_investment_identifier AS VARCHAR)) <> ''"""
    )
    total_bdc = con.execute("SELECT COUNT(*) FROM h").fetchone()[0]

    grand_rows = 0
    grand_moved = 0
    per_cik: list[tuple[str, int, int]] = []
    for cik, canon in sorted(rules.items()):
        try:
            rx = re.compile(canon)
        except re.error:
            continue
        ids = con.execute(
            "SELECT rawid FROM h WHERE cik = ?", [cik]
        ).fetchdf()["rawid"].tolist()
        if not ids:
            continue
        moved = sum(1 for s in ids if rx.sub("", s).strip() != s.strip())
        grand_rows += len(ids)
        grand_moved += moved
        if moved:
            per_cik.append((cik, len(ids), moved))

    con.close()

    print(f"\nBDC rows (Q4-2022+): {total_bdc}")
    print(f"rows under a canonical_strip_re CIK: {grand_rows}")
    print(
        f"rows the rule MOVES (position_key churn if toggled): {grand_moved} "
        f"({100*grand_moved/max(grand_rows,1):.2f}% of cohort, "
        f"{100*grand_moved/max(total_bdc,1):.3f}% of all BDC)"
    )
    print("\nper-CIK (rows_affected / cohort_rows):")
    for cik, n, moved in sorted(per_cik, key=lambda t: -t[2]):
        print(f"  {cik}  {moved:>6} / {n:>6}  ({100*moved/n:.1f}%)")


if __name__ == "__main__":
    main()
