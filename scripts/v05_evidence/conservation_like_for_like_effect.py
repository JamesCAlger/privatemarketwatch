"""Read-only: what the like-for-like fair-value conservation comparison changes, fund-quarter by fund-quarter.

    python scripts/v05_evidence/conservation_like_for_like_effect.py <path to the previous engine file> [sandbox label]

Runs the fair-value rule of the previous engine and of the current one in memory, on the published
outputs (or on a fund sandbox when a label is given), and prints every fund-quarter whose status
differs, plus the cash rows that have no filed figure to be checked against. Writes nothing.
Get the previous engine with: git show <commit>:scripts/shadow_conservation_engine.py > <file>
"""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if len(sys.argv) > 2:
    os.environ["PM_OUTPUT_DIR"] = str(REPO / "scratch/fund_sandbox" / sys.argv[2] / "output")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import duckdb  # noqa: E402


def run(path):
    spec = importlib.util.spec_from_file_location("engine_" + Path(path).stem, path)
    engine = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = engine
    spec.loader.exec_module(engine)
    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'")
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in engine.wrapped_ciks()])
    engine.ensure_anchor_overrides(con)
    rule = next(r for r in engine.RULES if r.name == "fv_conservation")
    engine.run_rule(con, rule)
    cols = [r[0] for r in con.execute("DESCRIBE result_fv_conservation").fetchall()]
    extra = ", cash_sum, filed_cash, cash_status" if "cash_status" in cols else ", NULL, NULL, ''"
    return {(r[0], r[1]): r[2:] for r in con.execute(
        "SELECT cik, report_date, status, anchor_used, residual_pct, value_sum" + extra + " FROM result_fv_conservation").fetchall()}


before, after = run(sys.argv[1]), run(REPO / "scripts/shadow_conservation_engine.py")
print("fund-quarters: %d | status before: %s" % (len(after), {s: sum(v[0] == s for v in before.values()) for s in {v[0] for v in before.values()}}))
print("                      status after : %s" % {s: sum(v[0] == s for v in after.values()) for s in {v[0] for v in after.values()}})
changed = sorted(k for k in after if k in before and before[k][0] != after[k][0])
print("changed: %d (cik | quarter | before -> after | anchor before -> after | residual before -> after | cash rows $M | filed cash $M | cash check)" % len(changed))
for key in changed:
    b, a = before[key], after[key]
    print("   %s | %s | %s -> %s | %s -> %s | %s -> %s | %.1f | %s | %s" % (
        key[0], key[1], b[0], a[0], b[1], a[1], b[2], a[2], (a[4] or 0) / 1e6, "-" if a[5] is None else "%.1f" % (a[5] / 1e6), a[6]))
unanchored = sorted(k for k, v in after.items() if v[6] == "no_filed_figure")
print("cash rows with no filed figure to check against: %d fund-quarters in %d funds, %.1fM in total" % (
    len(unanchored), len({k[0] for k in unanchored}), sum(after[k][4] or 0 for k in unanchored) / 1e6))
