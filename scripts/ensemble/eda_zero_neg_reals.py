"""Read-only deep-dive: dump FULL verdict leaves for every adjudicated
real_error on C103/C104/C404 in ens2, then pull the matching extracted holdings
rows (and their cross-quarter neighbors) to look for a data-visible trace of
the defect. ASCII, no network, no writes.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.config import (  # noqa: E402
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
)

BATCH = Path("data/output/ensemble/ens2")
VER = Path("data/output/review_queue/verdicts")
TARGETS = {"C103", "C104", "C404"}


def _unified_rel() -> str:
    if UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{UNIFIED_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def main() -> int:
    meta = {r["review_id"]: r
            for r in csv.DictReader(open(BATCH / "review_ids.csv", encoding="utf-8"))}
    reals = []
    for rid, m in meta.items():
        if m["rule_name"] not in TARGETS:
            continue
        p = VER / f"{rid}.json"
        if not p.exists():
            continue
        try:
            v = json.load(open(p, encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if (v.get("verdict") or "").lower() == "real_error":
            reals.append((rid, m, v))

    con = duckdb.connect()
    con.execute(f"CREATE VIEW u AS SELECT * FROM {_unified_rel()}")

    print(f"real_error verdicts on C103/C104/C404: {len(reals)}\n")
    for rid, m, v in reals:
        print("=" * 76)
        print(f"{rid}  rule={m['rule_name']}  cik={m['cik']}  {m['report_date']}")
        for k in ("observed_value", "anchor_value", "mechanism", "confidence",
                  "localized", "anchor_used", "escalate"):
            print(f"  {k}: {v.get(k)!r}")
        cc = v.get("culprit_citations")
        print(f"  culprit_citations: {json.dumps(cc)[:700] if cc else None}")
        print(f"  rationale: {(v.get('rationale') or '')}")
        print()
    # ---- trace the culprit issuers across quarters -------------------------
    TRACE = [
        ("0001715933", "Navistar Defense"),
        ("0001930087", "Morgan Stanley Institutional Liquidity"),
        ("0001825265", "HydroSource"),
        ("0001860424", "SPLAT"),
        ("0002012139", "FR Refuel"),
        ("0001950803", "Echo Purchaser"),
        ("0001950803", "PracticeTek"),
    ]
    for cik, frag in TRACE:
        rows = con.execute(
            f"""
            SELECT report_date, issuer_name, asset_class,
                   fair_value, cost, pct_of_net_assets
            FROM u
            WHERE LPAD(CAST(cik AS VARCHAR), 10, '0') = '{cik}'
              AND (issuer_name ILIKE '%{frag}%'
                   OR bdc_investment_identifier ILIKE '%{frag}%')
            ORDER BY report_date, issuer_name
            LIMIT 16
            """
        ).fetchall()
        print(f"-- {cik} rows matching '{frag}' across quarters --")
        for r in rows:
            print(f"   {r[0]} | {str(r[1])[:52]:52s} | cls={str(r[2]):16s} "
                  f"fv={r[3]} cost={r[4]} pct={r[5]}")
        print()

    # ---- NAV context for the C404 rows (XBRL-rounding hypothesis) ----------
    from pipeline.config import FUND_FINANCIALS_FILE  # noqa: E402
    for cik, rdate, fv_th in (("0001860424", "2025-12-31", -5878),
                              ("0002012139", "2026-03-31", -9),
                              ("0001950803", "2023-12-31", -189)):
        nav = con.execute(
            f"""
            SELECT MEDIAN(TRY_CAST(net_assets AS DOUBLE))
            FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
            WHERE LPAD(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = '{cik}'
              AND CAST(report_date AS VARCHAR) = '{rdate}'
              AND TRY_CAST(net_assets AS DOUBLE) > 0
            """
        ).fetchone()[0]
        if nav:
            print(f"C404 check {cik} {rdate}: NAV={nav:,.0f}  "
                  f"FV({fv_th}k)/NAV*100 = {fv_th * 1000 / nav * 100:.4f} pct")
        else:
            print(f"C404 check {cik} {rdate}: no NAV in fund_financials")

    # ---- does the C103 real (MS Liquidity -18000) still exist? -------------
    rows = con.execute(
        """
        SELECT report_date, issuer_name, fair_value, cost,
               substr(COALESCE(bdc_investment_identifier, ''), 1, 60)
        FROM u
        WHERE LPAD(CAST(cik AS VARCHAR), 10, '0') = '0001930087'
          AND TRY_CAST(fair_value AS DOUBLE) < 0
          AND CAST(report_date AS VARCHAR) = '2023-09-30'
        ORDER BY fair_value
        """
    ).fetchall()
    print(f"\n0001930087 2023-09-30 negative-FV rows in current holdings: {len(rows)}")
    for r in rows:
        print(f"   fv={r[2]} cost={r[3]} | {str(r[1])[:40]} | {r[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
