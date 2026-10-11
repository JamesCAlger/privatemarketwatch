"""Proposed dispositions for one fund, from a reading spec and a sandbox ledger. Nothing here is accepted.

    python scripts/v05_evidence/make_fund_proposals.py <sandbox label> <cik> [--write]

Reads docs/investigations/v05_readings/proposals/<cik10>_reading.json:

    {"decision": "D-099", "date": "2026-10-11", "report": "docs/investigations/v05_readings/<cik10>.md",
     "groups": [{"engine": "oracle", "rule_name": "C04", "class": "as_filed", "statement": "...",
                 "evidence": [{"source": "filing", "quote": "..."}], "quarters": ["2025-03-31"] (optional)}]}

For each group the quarters are the fund's outstanding findings of that rule in the sandbox ledger
(or the listed subset of them). With --write the entries go to
data/overrides/finding_dispositions_proposed/fund_<cik10>.json, which the findings ledger does not
read. The owner accepts by moving entries into the live store. Findings no group covers are listed
as left open.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
args = [a for a in sys.argv[1:] if a != "--write"]
label, cik = args[0], args[1].zfill(10)
OUTSTANDING = {"open", "needs_human", "evidence_backlog", "real_error_unremediated", "remediation_pulled", "remediation_staged"}
spec = json.loads((REPO / "docs/investigations/v05_readings/proposals" / (cik + "_reading.json")).read_text(encoding="utf-8"))

csv.field_size_limit(10 ** 9)
open_by = defaultdict(set)
with open(REPO / "scratch/fund_sandbox" / label / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        if row["cik"].zfill(10) == cik and row["state"] in OUTSTANDING and row["report_date"][:10] >= "2022-01-01":
            open_by[(row["engine"], row["rule_name"])].add(row["report_date"][:10])

entries, covered = [], defaultdict(set)
for number, group in enumerate(spec["groups"], 1):
    key = (group["engine"], group["rule_name"])
    quarters = sorted(open_by.get(key, set()) & set(group.get("quarters") or open_by.get(key, set())))
    if not quarters:
        print("  no outstanding finding for", key, "- group skipped")
        continue
    covered[key] |= set(quarters)
    entries.append({
        "disposition_id": "PD-%s-%s-%d" % (group["rule_name"], cik.lstrip("0"), number),
        "class": group["class"], "engine": group["engine"], "rule_name": group["rule_name"],
        "ciks": [cik], "quarters": quarters, "statement": group["statement"], "basis": "read",
        "evidence": group["evidence"], "rerun": "see " + spec["report"],
        "decided_by": "PROPOSED by agent %s (%s); not accepted by the owner" % (spec["date"], spec["decision"]),
        "decided_on": spec["date"],
    })
    print("  %-16s %-48s %-12s %d quarters" % (key[0], key[1], group["class"], len(quarters)))
left = {key: sorted(quarters - covered[key]) for key, quarters in open_by.items() if quarters - covered[key]}
total = sum(len(q) for q in open_by.values())
print("outstanding %d, proposed %d, left open %d" % (total, sum(len(e["quarters"]) for e in entries), sum(map(len, left.values()))))
for key, quarters in sorted(left.items()):
    print("  left open: %s/%s %s" % (key[0], key[1], ", ".join(quarters)))
if "--write" in sys.argv:
    target = REPO / "data/overrides/finding_dispositions_proposed" / ("fund_%s.json" % cik)
    target.write_text(json.dumps({"status": "PROPOSED, not accepted. The findings ledger does not read this directory.",
                                  "sandbox": label, "dispositions": entries}, indent=1) + "\n", encoding="utf-8")
    print("wrote", target.relative_to(REPO))
