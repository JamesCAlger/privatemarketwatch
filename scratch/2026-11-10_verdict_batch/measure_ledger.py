"""Ledger before/after the standing-rule retirements, on the production inputs (main checkout, read-only).

    python scratch/2026-11-10_verdict_batch/measure_ledger.py

before = retirements store with only owner_2026-11-10.json (the merged state)
after  = + standing_rule_2026-11-10.json (this branch)
Writes ledger_changes.csv and ledger_after.csv here (scratch, not data/output).
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WT = HERE.parents[1]
MAIN = Path("C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl")
sys.path.insert(0, str(WT))
from scripts import findings_ledger as fl  # noqa: E402
from pipeline.quarter_acceptance import RESOLVED_FINDING_STATES  # noqa: E402

STORES = dict(
    queue_path=MAIN / "data/output/review_queue/review_queue.csv",
    staged_dir=MAIN / "data/output/agent_b2/corrections",
    promoted_dir=MAIN / "data/overrides/agent_b2_corrections",
    archive_dir=MAIN / "data/output/agent_b2/corrections_archive",
    wrapper_dir=MAIN / "data/overrides/bdc_xbrl_wrappers",
    verdict_dirs=(MAIN / "data/output/review_queue/verdicts", MAIN / "data/output/bdc_cik_review/verdicts"),
    dispositions_dir=MAIN / "data/overrides/finding_dispositions",
)
RET = WT / "data/overrides/verdict_retirements"
V05 = {str(c).zfill(10) for c in json.loads((WT / "data/reference/quarter_acceptance_thresholds.json")
                                            .read_text(encoding="utf-8"))["findings_scope"]["ciks"]}
with tempfile.TemporaryDirectory() as td:
    shutil.copy(RET / "owner_2026-11-10.json", td)
    before = {r["review_id"]: r for r in fl.build_ledger(retirements_dir=Path(td), **STORES)}
after = fl.build_ledger(retirements_dir=RET, **STORES)
a = pd.DataFrame(after)
a["cik"] = a.cik.astype(str).str.zfill(10)
a["before"] = a.review_id.map(lambda r: before.get(r, {}).get("state", "(absent)"))
a.to_csv(HERE / "ledger_after.csv", index=False)
ch = a[a.before.ne(a.state)]
ch[["review_id", "cik", "rule_name", "report_date", "engine", "before", "state", "retirement_id"]].to_csv(
    HERE / "ledger_changes.csv", index=False)
print("findings", len(a), "changed", len(ch))
print(ch.groupby(["before", "state"]).size().to_string())
for q in ("2026-03-31", "2025-12-31"):
    for label, mask in (("v0.5", a.cik.isin(V05)), ("all", a.cik.ne(""))):
        sub = a[mask & a.report_date.astype(str).str[:10].eq(q)]
        ob = int((~sub.before.isin(RESOLVED_FINDING_STATES)).sum())
        oa = int((~sub.state.isin(RESOLVED_FINDING_STATES)).sum())
        print(f"{q} {label}: outstanding before {ob} after {oa} (closed {ob - oa})")
        if label == "v0.5":
            print("   after by state:", sub[~sub.state.isin(RESOLVED_FINDING_STATES)].state.value_counts().to_dict())
