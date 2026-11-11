"""Read-only: production holdings vs each cohort fund's registered sandbox, per quarter (fold-back check).

    python scripts/v05_evidence/sandbox_parity.py [--quarters 2026-03-31 2026-06-30] [--out DIR]

Published basis on both sides (rows with accounting_record_class = 'underlying_schedule' left out).
Sandbox = the fund's entry in docs/investigations/v05_readings/accepted_sandboxes.json. A quarter the
sandbox does not hold is UNCHECKED, not a pass. With --prod-ledger, also diffs finding ids: an id
outstanding in production but not in the fund's sandbox ledger is NEW_OUTSTANDING_IN_PRODUCTION (finding
ids are per fund, rule and period, so the same finding has the same id on both sides). Production computes
cross-fund values (entity ids, industry labels) on all funds, so a new id needs reading before it is
called a regression. Exit 1 when any fund differs, is unchecked, or has a new outstanding id.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline.cohort_guard import load_cohort_ciks  # noqa: E402

SQL = """
SELECT count(*), sum(TRY_CAST(fair_value AS DOUBLE)) FROM read_parquet(?)
WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
  AND coalesce(CAST(accounting_record_class AS VARCHAR),'') <> 'underlying_schedule'
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarters", nargs="+", default=["2026-03-31", "2026-06-30"])
    ap.add_argument("--out", default="scratch/sandbox_parity")
    ap.add_argument("--prod-ledger", help="production ledger CSV (e.g. data/output/quarter_pass/<id>/findings_ledger_pre.csv)")
    args = ap.parse_args()
    acc = json.loads((REPO / "docs/investigations/v05_readings/accepted_sandboxes.json").read_text(encoding="utf-8"))
    prod = (REPO / "data/output/private_markets_holdings.parquet").as_posix()
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    bad = 0
    for q in args.quarters:
        rows = []
        for cik in sorted(c.zfill(10) for c in load_cohort_ciks()):
            label = (acc.get(cik) or {}).get("label")
            sb = REPO / "scratch/fund_sandbox" / str(label) / "output/private_markets_holdings.parquet"
            pn, pf = con.execute(SQL, [prod, cik, q]).fetchone()
            if not label or not sb.exists():
                status, sn, sf = "UNCHECKED_no_sandbox", None, None
            else:
                sn, sf = con.execute(SQL, [sb.as_posix(), cik, q]).fetchone()
                if not sn:
                    status = "UNCHECKED_quarter_not_in_sandbox"
                elif pn == sn and abs((pf or 0) - (sf or 0)) <= 0.5:
                    status = "EQUAL"
                else:
                    status = "DIFFERS"
            bad += status != "EQUAL"
            rows.append({"cik": cik, "label": label, "status": status, "prod_rows": pn, "sb_rows": sn,
                         "prod_fv": pf, "sb_fv": sf, "fv_diff": None if sf is None or pf is None else pf - sf})
        path = out / ("sandbox_parity_%s.csv" % q)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        counts = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(q, counts, "->", path.relative_to(REPO).as_posix())
        for r in rows:
            if r["status"] != "EQUAL":
                print("   ", r["cik"], r["label"], r["status"], "rows", r["prod_rows"], "vs", r["sb_rows"], "fv diff", r["fv_diff"])
    if args.prod_ledger:
        bad += ledger_diff(acc, REPO / args.prod_ledger, out)
    return 1 if bad else 0


def ledger_diff(acc: dict, prod_ledger: Path, out: Path) -> int:
    """Finding ids: production outstanding vs each fund's registered sandbox ledger. New outstanding ids fail."""
    from pipeline.quarter_acceptance import RESOLVED_FINDING_STATES

    def read(path: Path, cik: str) -> dict[str, dict]:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return {r["review_id"]: r for r in csv.DictReader(fh)
                    if r["cik"].zfill(10) == cik and r["report_date"][:10] >= "2022-01-01"}

    rows, new_total = [], 0
    for cik in sorted(c.zfill(10) for c in load_cohort_ciks()):
        label = (acc.get(cik) or {}).get("label")
        sb_path = REPO / "scratch/fund_sandbox" / str(label) / "findings_ledger.csv"
        if not label or not sb_path.exists():
            rows.append({"cik": cik, "label": label, "review_id": "", "rule_name": "", "report_date": "",
                         "change": "UNCHECKED_no_sandbox_ledger", "prod_state": "", "sb_state": ""})
            new_total += 1
            continue
        prod, sb = read(prod_ledger, cik), read(sb_path, cik)
        for rid in sorted(set(prod) | set(sb)):
            p, s = prod.get(rid), sb.get(rid)
            p_open = p is not None and p["state"] not in RESOLVED_FINDING_STATES
            s_open = s is not None and s["state"] not in RESOLVED_FINDING_STATES
            if p_open and not s_open:
                change = "NEW_OUTSTANDING_IN_PRODUCTION"
                new_total += 1
            elif s_open and not p_open:
                change = "closed_in_production"
            elif p and s and p["state"] != s["state"]:
                change = "state_changed"
            else:
                continue
            r = p or s
            rows.append({"cik": cik, "label": label, "review_id": rid, "rule_name": r["rule_name"],
                         "report_date": r["report_date"][:10], "change": change,
                         "prod_state": p["state"] if p else "", "sb_state": s["state"] if s else ""})
    path = out / "ledger_diff.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["cik", "label", "review_id", "rule_name", "report_date", "change", "prod_state", "sb_state"])
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["change"]] = counts.get(r["change"], 0) + 1
    print("ledger diff vs registered sandboxes:", counts, "->", path.relative_to(REPO).as_posix())
    return new_total


if __name__ == "__main__":
    raise SystemExit(main())
