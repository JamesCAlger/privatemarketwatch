"""Read-only: run one disposition check on a sandbox for a rule and a fund, quarter by quarter.

    python scripts/v05_evidence/check_probe.py <label> <rule> <cik> <check kind> [json params]

Shows what a check would accept before any entry relies on it, with the rows that fail and why.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import disposition_validity as dv  # noqa: E402

label, rule, cik, kind = sys.argv[1], sys.argv[2], sys.argv[3].zfill(10), sys.argv[4]
params = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
probe = {"disposition_id": "probe", "ciks": [cik], "rule_name": rule,
         "carry_forward": {"from": "2022-01-01", "check": kind, "params": params}}
problems = dv.validate_carry_forward(probe["carry_forward"])
if problems:
    raise SystemExit("; ".join(problems))
for result in dv.evaluate([probe], REPO / "scratch/fund_sandbox" / label / "output"):
    print("%s %s  %s  tested %s  failing %s  %s" % (result["cik"], result["report_date"], "PASS" if result["passed"] else "fail",
                                                    result["rows_tested"], result["rows_failing"], result["detail"][:260]))
