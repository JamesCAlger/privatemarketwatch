"""Target list: findings reopened as real_error_check_silent (prod ledger + accepted sandboxes).
Writes targets.csv (review_id, cik, rule, report_date, engine, src, v05, cohort, priority). Read-only on inputs."""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
M = Path("C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl")
SRC = M / ".claude/worktrees/agent-a16aeddf49bfe8fc9/scratch/2026-11-10_verdicts"
V05 = {"0001803498", "0001812554", "0001287750", "0001838126", "0001837532"}
cohort = {x.strip().zfill(10) for x in (M / "scratch/2026-11-10_rebuild/fieldstatus/cohort_ciks.txt").read_text().split() if x.strip()}

p = pd.read_csv(SRC / "prod_changes.csv", dtype=str).fillna("")
p = p[p.after.eq("real_error_check_silent")][["review_id", "cik", "rule", "report_date", "engine"]].assign(src="prod")
s = pd.read_csv(SRC / "newly_outstanding_C.csv", dtype=str).fillna("")
s = s[s.after.eq("real_error_check_silent")][["review_id", "cik", "rule", "report_date"]].assign(engine="", src="sandbox")
both = pd.concat([p, s])
t = both.groupby("review_id", as_index=False).agg(
    cik=("cik", "first"), rule=("rule", "first"), report_date=("report_date", "first"),
    src=("src", lambda x: "+".join(sorted(set(x)))))
# engine: from the prod ledger row; else the rule's single engine in the full prod ledger
allp = pd.read_csv(SRC / "prod_changes.csv", dtype=str).fillna("")
eng_by_id = dict(zip(allp.review_id, allp.engine))
rule_eng = allp[allp.engine.ne("")].groupby("rule").engine.agg(lambda x: "|".join(sorted(set(x))))
t["engine"] = [eng_by_id.get(r) or (rule_eng.get(u, "") if "|" not in rule_eng.get(u, "") else "")
               for r, u in zip(t.review_id, t.rule)]
t["cik"] = t.cik.str.zfill(10)
t["v05"] = t.cik.isin(V05)
t["cohort"] = t.cik.isin(cohort)
t["priority"] = 9
t.loc[t.v05 & t.report_date.eq("2026-03-31"), "priority"] = 1
t.loc[t.v05 & t.report_date.eq("2025-12-31"), "priority"] = 2
t.loc[~t.v05 & t.cohort & t.report_date.isin(["2026-03-31", "2025-12-31"]), "priority"] = 3
t.loc[t.priority.eq(9) & t.v05, "priority"] = 4
t.loc[t.priority.eq(9) & t.cohort, "priority"] = 5
t = t.sort_values(["priority", "cik", "report_date", "rule"])
t.to_csv(HERE / "targets.csv", index=False)
print(len(t), "cohort size", len(cohort))
print(t.groupby(["priority"]).size().to_string())
for pr in (1, 2, 3):
    (HERE / f"ids_p{pr}.txt").write_text("\n".join(t[t.priority.eq(pr)].review_id) + "\n")
