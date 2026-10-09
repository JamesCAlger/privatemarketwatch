"""Dispositions by check for any batch of funds, from a sandbox ledger.

    python scripts/v05_evidence/make_batch_dispositions.py <sandbox label> <batch name> <cik> [<cik> ...] [--write]

Owner standing instruction 2026-10-09 (decision D-073): "a disposition i already accepted may be
accepted by its check". This applies exactly that and nothing else: the reasons the owner accepted
for the first five funds that have a deterministic row-by-row test (C107, C103, X06, X02 through
pipeline/disposition_validity.py, and F28 for quarters before the fund's first schedule). A
fund-quarter where the test passes gets an entry; one where it fails stays open. A finding that
carries an earlier reviewer's 'real error' verdict is not closed by these entries (the ledger
keeps the verdict standing). Every other outstanding finding is listed as needing a reading.

With --write the entries go to data/overrides/finding_dispositions/<batch name>_accepted_by_check.json
(merged by id with what the file already holds). Without it nothing is written.
"""
import csv
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from pipeline import disposition_validity as dv  # noqa: E402
from pipeline import finding_dispositions as fd  # noqa: E402

args = [a for a in sys.argv[1:] if a != "--write"]
label, batch, ciks = args[0], args[1], [c.zfill(10) for c in args[2:]]
SANDBOX = REPO / "scratch/fund_sandbox" / label
S = "python scripts/v05_evidence/"
OUTSTANDING = {"open", "needs_human", "evidence_backlog", "real_error_unremediated", "remediation_pulled", "remediation_staged"}
_FILED = lambda *fields: {"from": "2022-01-01", "check": "values_as_filed", "params": {"fields": list(fields)}}
CHECKED = {
    ("row_validation", "C107"): ("as_filed", "Negative cost on undrawn revolvers and delayed draws, filed net of fees.",
                                 _FILED("cost"), S + "issue_shape.py %s C107 3" % label),
    ("row_validation", "C103"): ("as_filed", "Small negative fair values on undrawn lines, as tagged.",
                                 _FILED("fair_value"), S + "issue_shape.py %s C103 3" % label),
    ("row_validation", "X06"): ("as_filed", "Principal far above fair value on partly drawn commitments (principal is the "
                                "commitment) and on positions the fund has marked down, as filed.",
                                _FILED("principal_amount", "fair_value"), S + "issue_shape.py %s X06 3" % label),
    ("row_validation", "X02"): ("as_filed", "Credit rows with no rate and no spread because no rate or spread fact is tagged "
                                "for them: undrawn lines, non-accrual loans, and loans whose only rate tag is a PIK rate.",
                                {"from": "2022-01-01", "check": "no_rate_in_source", "params": {}},
                                S + "x02_page_read.py %s <cik>" % label),
}
BY_CHECK = "check passed on sandbox %s; accepted under the owner's standing instruction of 2026-10-09 (D-073)" % label

csv.field_size_limit(10 ** 9)
open_by, names = defaultdict(set), {}
with open(SANDBOX / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        cik = row["cik"].zfill(10)
        if cik in ciks and row["state"] in OUTSTANDING and row["report_date"][:10] >= "2022-01-01":
            open_by[(row["engine"], row["rule_name"], cik)].add(row["report_date"][:10])

import duckdb  # noqa: E402
holdings = (SANDBOX / "output" / "private_markets_holdings.parquet").as_posix()
for cik, name, first in duckdb.connect().execute(
        "SELECT lpad(CAST(cik AS VARCHAR),10,'0'), any_value(entity_name), min(CAST(report_date AS VARCHAR)[:10]) "
        "FROM read_parquet('%s') GROUP BY 1" % holdings).fetchall():
    names[cik] = (str(name), first)

entries, held = [], []
for (engine, rule, cik), quarters in sorted(open_by.items()):
    if (engine, rule) in CHECKED:
        kind, statement, check, rerun = CHECKED[(engine, rule)]
        probe = {"disposition_id": "probe", "class": kind, "engine": engine, "rule_name": rule, "ciks": [cik],
                 "quarters": ["2021-12-31"], "carry_forward": check}
        results = {r["report_date"][:10]: r for r in dv.evaluate([probe], SANDBOX / "output")}
        passed = sorted(q for q in quarters if str(results.get(q, {}).get("passed")).lower() == "true")
        held += [(cik, engine, rule, q, "check failed") for q in sorted(quarters - set(passed))]
        if passed:
            tested = sum(int(results[q]["rows_tested"]) for q in passed)
            entries.append({"disposition_id": "DS-%s-%s-%s" % (batch.upper(), rule, cik[-7:]), "class": kind, "engine": engine,
                            "rule_name": rule, "ciks": [cik], "quarters": passed, "statement": statement,
                            "evidence": [{"source": "query", "quote": "Check %s passed on sandbox %s for each quarter listed: %d "
                                          "flagged rows tested, none failing." % (check["check"], label, tested)}],
                            "rerun": rerun.replace("<cik>", cik), "decided_by": BY_CHECK, "decided_on": "2026-10-09"})
    elif (engine, rule) == ("fund_financials", "F28") and cik in names:
        early = sorted(q for q in quarters if q < names[cik][1])
        held += [(cik, engine, rule, q, "needs a reading") for q in sorted(quarters - set(early))]
        if early:
            entries.append({"disposition_id": "DS-%s-F28-%s" % (batch.upper(), cik[-7:]), "class": "not_applicable", "engine": engine,
                            "rule_name": rule, "ciks": [cik], "quarters": early,
                            "statement": "Fund-level figures exist for these quarters but the cache holds no position schedule "
                                         "before the fund's first structured filing, so there are no holdings to compare.",
                            "evidence": [{"source": "query", "quote": "Sandbox %s: the fund's first quarter with published "
                                          "holdings is %s; each quarter listed is earlier." % (label, names[cik][1])}],
                            "rerun": S + "cohort_by_size.py", "decided_by": BY_CHECK, "decided_on": "2026-10-09"})
    else:
        held += [(cik, engine, rule, q, "needs a reading") for q in sorted(quarters)]

for entry in entries:
    problems = fd.validate(entry)
    assert not problems, (entry["disposition_id"], problems)

live = fd.default_dir() / ("%s_accepted_by_check.json" % batch)
kept = {e["disposition_id"]: e for e in (json.loads(live.read_text(encoding="utf-8"))["dispositions"] if live.exists() else [])}
for e in entries:
    quarters = sorted(set(e["quarters"]) | set(kept.get(e["disposition_id"], {}).get("quarters", [])))
    kept[e["disposition_id"]] = {**e, "quarters": quarters}
merged = [kept[k] for k in sorted(kept)]

import findings_ledger  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "store"
    shutil.copytree(fd.default_dir(), store)
    (store / live.name).write_text(json.dumps({"dispositions": merged}), encoding="utf-8")
    ledger = findings_ledger.build_ledger(queue_path=SANDBOX / "output" / "review_queue" / "review_queue.csv", dispositions_dir=store,
                                          validity_path=SANDBOX / "disposition_validity.csv")
left, by_rule = defaultdict(int), defaultdict(int)
for row in ledger:
    cik = str(row["cik"]).zfill(10)
    if cik in ciks and row["state"] in OUTSTANDING and str(row["report_date"])[:10] >= "2022-01-01":
        left[cik] += 1
        by_rule[(cik, row["engine"], row["rule_name"])] += 1
now = defaultdict(int)
for (engine, rule, cik), quarters in open_by.items():
    now[cik] += len(quarters)
print("fund | outstanding in the sandbox ledger | outstanding with the check-accepted entries")
for cik in ciks:
    print("   %s %-44s | %4d | %4d" % (cik, names.get(cik, ("?", ""))[0][:44], now[cik], left[cik]))
print("   total | %d | %d | entries by check: %d" % (sum(now.values()), sum(left.values()), len(entries)))
print("left, by fund and rule:")
for (cik, engine, rule), n in sorted(by_rule.items(), key=lambda kv: (kv[0][0], -kv[1])):
    print("   %s | %s/%s | %d" % (cik, engine, rule, n))
if "--write" in sys.argv:
    live.write_text(json.dumps({"dispositions": merged}, indent=1) + "\n", encoding="utf-8")
    print("wrote", live.relative_to(REPO))
