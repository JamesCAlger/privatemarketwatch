"""Wave-1 promotion driver (gap 1, spec section 8.1).

For every inventory row with wave1_action in {promote_rules, hold_no_gate_record},
call run_investigation.promote(cik, target_quarter). promote() re-runs the B3
held-out gate LIVE against current production holdings and REFUSES on anything but
PASS -- the gate, not the stale batch record, is the promotion bar (this also gives
1743415 its missing gate run). Gate-FAIL inventory rows are never attempted.

Writes data/output/agent_investigate/wave1_promotion_results.csv. Rules land in
data/overrides/agent_investigate_rules/<cik>/ (consumed by build_unified_holdings,
Layer C). Rerunnable: promotion is a copy, re-promotion overwrites identically.
ASCII-only.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config

INVENTORY = config.OUTPUT_DIR / "agent_investigate" / "wave1_inventory.csv"
OUT_FILE = config.OUTPUT_DIR / "agent_investigate" / "wave1_promotion_results.csv"

ATTEMPT_ACTIONS = {"promote_rules", "hold_no_gate_record"}
COLUMNS = ["cik", "target_quarter", "inventory_action", "status", "gate", "n_rules",
           "elapsed_s", "detail"]


def main() -> int:
    from scripts.agent_investigate.run_investigation import promote

    if not INVENTORY.exists():
        print(f"inventory not found: {INVENTORY} (run scripts/wave1_inventory.py first)")
        return 1
    with open(INVENTORY, newline="", encoding="utf-8-sig") as f:
        targets = [r for r in csv.DictReader(f) if r.get("wave1_action") in ATTEMPT_ACTIONS]
    print(f"wave-1 promotion: attempting {len(targets)} CIKs (gate-live, refuse on non-PASS)")

    results: list[dict] = []
    for i, t in enumerate(targets, 1):
        cik, q = t["cik"], t["target_quarter"]
        t0 = time.time()
        try:
            res = promote(cik, q)
        except Exception as exc:
            res = {"status": "error", "gate": "", "detail": str(exc)}
        elapsed = round(time.time() - t0, 1)
        row = {"cik": cik, "target_quarter": q, "inventory_action": t["wave1_action"],
               "status": res.get("status", "error"), "gate": res.get("gate", ""),
               "n_rules": res.get("n_rules", ""), "elapsed_s": elapsed,
               "detail": json.dumps(res.get("reasons") or res.get("detail") or "")[:400]}
        results.append(row)
        print(f"  [{i}/{len(targets)}] {cik} {q}: {row['status']}"
              f"{(' gate=' + str(row['gate'])) if row['gate'] else ''} ({elapsed}s)")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(results)

    n_prom = sum(1 for r in results if r["status"] == "promoted")
    n_ref = sum(1 for r in results if r["status"] == "refused")
    n_err = len(results) - n_prom - n_ref
    print(f"promoted {n_prom}, refused {n_ref}, errors {n_err} -> {OUT_FILE}")
    for r in results:
        if r["status"] != "promoted":
            print(f"  {r['status']}: {r['cik']} {r['target_quarter']} {r['detail'][:200]}")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
