"""Read-only: for given funds, the newest sandbox whose holdings contain the fund, and its ledger counts.

    python scripts/v05_evidence/fund_ledger_latest.py <cik> [<cik> ...] [--rules]
"""
import csv
import sys
import time
from collections import Counter
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "scratch/fund_sandbox"
RESOLVED = {"adjudicated_false_alarm", "remediated_promoted", "resolved_upstream", "gone_unadjudicated"}
ciks = [a.zfill(10) for a in sys.argv[1:] if not a.startswith("--")]
show_rules = "--rules" in sys.argv
csv.field_size_limit(10**9)
con = duckdb.connect()
boxes = sorted((p for p in ROOT.iterdir() if (p / "findings_ledger.csv").exists() and (p / "output/private_markets_holdings.parquet").exists()),
               key=lambda p: (p / "findings_ledger.csv").stat().st_mtime, reverse=True)
found = {}
for box in boxes:
    if len(found) == len(ciks):
        break
    held = {r[0] for r in con.execute("SELECT DISTINCT lpad(CAST(cik AS VARCHAR),10,'0') FROM read_parquet('%s')"
                                      % (box / "output/private_markets_holdings.parquet").as_posix()).fetchall()}
    for cik in ciks:
        if cik in held and cik not in found:
            found[cik] = box
for cik in ciks:
    box = found.get(cik)
    if box is None:
        print(cik, "no sandbox")
        continue
    ledger = box / "findings_ledger.csv"
    with open(ledger, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r["cik"].zfill(10) == cik and r["report_date"][:10] >= "2022-01-01"]
    live = [r for r in rows if r["state"] not in RESOLVED]
    out = [r for r in live if not r["state"].startswith("dispositioned")]
    quarters = sorted({r["report_date"][:10] for r in rows})
    print("%s  sandbox %-6s ledger %s  findings %4d  dispositioned %4d  outstanding %4d  quarters %s to %s" % (
        cik, box.name, time.strftime("%Y-%m-%d %H:%M", time.localtime(ledger.stat().st_mtime)), len(live), len(live) - len(out), len(out),
        quarters[0] if quarters else "-", quarters[-1] if quarters else "-"))
    if show_rules:
        for (engine, rule), n in Counter((r["engine"], r["rule_name"]) for r in out).most_common():
            print("      %-20s %-48s %3d" % (engine, rule, n))
