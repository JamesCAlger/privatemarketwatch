"""Proposed dispositions for the next five funds, from a sandbox ledger. Nothing here is accepted.

    python scripts/v05_evidence/make_proposed_dispositions.py <sandbox label> [--write]

The first five funds' dispositions (make_dispositions.py) were accepted by the owner. These are
proposals for Ares Strategic Income, Goldman Sachs Private Credit, Golub Capital Private Credit,
Sixth Street Lending Partners and Oaktree Strategic Credit. They are written to
data/overrides/finding_dispositions_proposed/, which the findings ledger does not read, and to a
readable list in docs/investigations/. The owner accepts by moving entries into the live store.

Two kinds of proposal:

  checked   the first five's reason, restated as a deterministic test of every flagged row
            (pipeline/disposition_validity.py). Only fund-quarters where the test passes on this
            sandbox are proposed; a failing quarter stays open and is listed with its rows.
  read      a reason found in this session on the page or in the tags, with the evidence quoted.

Every other outstanding finding is listed as not read. The script also reports what the ledger
would show if every proposal were accepted, using a temporary copy of the store.
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

label = sys.argv[1]
ASIF, GS, GOLUB, SIXTH, OAKTREE = "0001918712", "0001920145", "0001930087", "0001925309", "0001872371"
NAMES = {ASIF: "Ares Strategic Income", GS: "Goldman Sachs Private Credit", GOLUB: "Golub Capital Private Credit",
         SIXTH: "Sixth Street Lending Partners", OAKTREE: "Oaktree Strategic Credit"}
WHO, WHEN = "PROPOSED by agent 2026-10-08; not accepted by the owner", "2026-10-08"
S = "python scripts/v05_evidence/"
SANDBOX = REPO / "scratch/fund_sandbox" / label
OUTSTANDING = {"open", "needs_human", "evidence_backlog", "real_error_unremediated", "remediation_pulled", "remediation_staged"}
_FILED = lambda *fields: {"from": "2022-01-01", "check": "values_as_filed", "params": {"fields": list(fields)}}
_NO_RATE = {"from": "2022-01-01", "check": "no_rate_in_source", "params": {}}

# (engine, rule) -> class, statement, check, rerun. The first five's reasons, tested row by row here.
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
                                _NO_RATE, S + "x02_page_read.py %s <cik>" % label),
}

# (engine, rule, cik) -> quarters read, class, statement, [(source, quote)], rerun. Only the quarters named:
# the rows of each were read on the page. Other open quarters of the same rule stay open.
READ_QUARTERS = {
    ("row_validation", "X02", ASIF): (
        {"2025-06-30", "2025-09-30"}, "as_filed",
        "Rows printed with no rate: one private asset-backed investment and the lowest tranche of three collateralized loan "
        "obligations. No rate is tagged or printed.",
        [("filing", "0001918712-25-000065 (10-Q, 2025-06-30): 'Quintain Investments Holdings Limited (11) Private asset-backed "
                    "investment 08/2031 32,775.6 42,469.6 48,861.1'; 'STKPK 2022-1 ... Collaterized loan obligation 10/2037 "
                    "20,240.0 194.4 602.8'; 'CLRMPK 2025-1 ... Collaterized loan obligation 04/2038 15,725.0 - 573.5'; 'BERRY "
                    "2024-1 ... Collaterized loan obligation 10/2037 2,610.0 - 154.4'. The tranches above each print a rate."),
         ("query", "Check no_rate_in_source on sandbox n5d names these rows and no others in the two quarters. Not covered: "
                   "2025-12-31 and 2026-03-31, where Steward Partners prints '9.08 % SOFR (Q) 4.75 %' and publishes no rate "
                   "(a real gap), and 2026-06-30, not read.")],
        S + "filing_grep.py 1918712 000191871225000065 html \"STKPK 2022-1\" 8 330"),
    ("row_validation", "SRC_BDC01", SIXTH): (
        {"2024-12-31", "2025-09-30"}, "not_applicable",
        "The source row read as a missing position is a prior-period value the filer tagged on a current-period context. "
        "The page prints one row for the loan; a rule excludes the stray member.",
        [("filing", "0000950170-25-021144 (10-K, 2024-12-31): the 2024 schedule prints 'Artisan Bidco, Inc. (3) First-lien loan "
                    "($ 114,848 par, due 11/2029) ... 112,663 114,848'; the 2023 schedule prints '($ 141,889 par ...) 138,686 "
                    "139,850'. The member '$141,889 par' carries a 2024-12-31 value of 139,850 and no principal."),
         ("filing", "0001193125-25-266848 (10-Q, 2025-09-30): Green Shoot BidCo, the same pattern (D-062).")],
        S + "filing_grep.py 1925309 000095017025021144 html \"Artisan Bidco, Inc. (\" 3 420"),
    ("source_recon", "blocking_source_pct_leaf_parser_mismatch", SIXTH): (
        {"2024-12-31", "2025-09-30"}, "not_applicable",
        "The same two stray prior-period members as SRC_BDC01, reported by the reconciliation's second engine.",
        [("filing", "See PD-SRC_BDC01 for Sixth Street: Artisan Bidco 139,850 at 2024-12-31 and Green Shoot BidCo 5,246 at "
                    "2025-09-30, each the comparative row's value on a current-period context.")],
        S + "filing_grep.py 1925309 000119312525266848 html \"EUR 5,107\" 12"),
}

# (engine, rule, cik) -> class, statement, [(source, quote)], rerun. Read in this session.
READ = {
    ("conservation", "fv_conservation", GS): (
        "not_applicable",
        "The fund's affiliated money market fund is published as a cash row. The filed investments total excludes it, and "
        "the fund files no cash-equivalents figure outside the schedule, so the check compares rows including the fund "
        "with a total that leaves it out. Without that row the published total equals the filed total.",
        [("filing", "0000950170-25-107338 (10-Q, 2025-06-30) balance sheet: 'Investments, at fair value (cost of $ 9,644,562 "
                    "...) $ 9,630,944 ... Investments in affiliated money market fund (cost of $ 233,261 ...) 233,261'."),
         ("query", "Sandbox n5c: the residual is the money market row in each failing quarter (233.3M of 9,630.9M is 2.42 pct "
                   "at 2025-06-30; 518.2M, 273.7M and 156.6M at the next three). Published excluding that row equals the "
                   "filed total within 0.5M in all 13 quarters.")],
        "python scratch/2026-10-07_printed_rates/q.py %s scratch/2026-10-07_printed_rates/n5_tot.sql" % label),
    ("conservation", "fv_conservation", OAKTREE): (
        "not_applicable",
        "In the two quarters where the schedule lists a short-term investment fund, the check adds the filed cash-equivalents "
        "figure to the filed investments. That figure is larger than the schedule row, so the comparison cannot close. "
        "Published investments equal filed investments in every quarter.",
        [("query", "Sandbox n5d, published investments / filed investments / published cash rows / filed cash equivalents ($M): "
                   "2025-06-30 6,362.9 / 6,362.9 / 100.7 / 471.3 (residual -5.42 pct); 2025-09-30 6,899.0 / 6,899.0 / 210.6 / "
                   "260.4 (-0.70 pct). In the four quarters with no cash row the check uses investments alone and passes.")],
        "python scratch/2026-10-07_printed_rates/q.py %s scratch/2026-10-07_printed_rates/oak1.sql" % label),
    ("row_validation", "PP02", GS): (
        "as_filed",
        "Pairs of tranches the filer prints as two rows with equal figures and tags on members ending 'One' / 'Two'. Both "
        "are positions; the filed total needs both (D-063).",
        [("filing", "0001193125-26-340582 (10-Q, 2026-06-30): two rows 'Airwavz Solutions, Inc. Wireless Telecommunication "
                    "Services 9.07 % S + 5.25 % 03/31/27 5,817 5,793 5,759'."),
         ("query", "Before the fix one row of each pair was dropped and published was 4.3M to 5.8M under the filed total in "
                   "six quarters; with both rows it equals the filed total.")],
        S + "issues.py %s PP02 1920145" % label),
    ("conservation", "fv_conservation", GOLUB): (
        "as_filed",
        "At 2023-12-31 the filer's printed subtotal includes a position its schedule neither prints nor tags (D-064).",
        [("filing", "0001930087-24-000010 (10-Q, 2023-12-31), Containers and Packaging: the seven printed rows sum to 32,366; "
                    "the printed subtotal is 35,834. Principal and cost are short by 3,482 and 3,450. The prior quarter "
                    "lists an eighth row, WP Deluxe Merger Sub (par 3,491)."),
         ("query", "Every tagged row is published: 256 rows, 1,400.4M, against the filed 1,403.9M.")],
        S + "page_block_sums.py 1930087 000193008724000010 2023-12-31"),
    ("identity", "pct_of_net_assets_identity", GOLUB): (
        "as_filed",
        "One to thirteen rows a quarter, out of 170 to 580, carry a filed percent that disagrees with their fair value. The "
        "published percent is the tagged fact, printed to one decimal.",
        [("query", "Sandbox n5b: failing rows per quarter 1, 5, 3, 1, 6, 4, 4, 3, 6, 8, 6, 13; the median implied net assets "
                   "is within 1 pct of the filed figure in every quarter (4,448M against 4,475M at 2026-06-30).")],
        S + "ident_left.py %s" % label),
    ("identity", "pct_of_net_assets_identity", SIXTH): (
        "as_filed",
        "One to seven rows a quarter, out of 38 to 108, carry a filed percent that disagrees with their fair value. The "
        "published percent is the tagged fact, printed to one decimal.",
        [("query", "Sandbox n5b: failing rows per quarter 1, 1, 2, 1, 5, 2, 7, 7, 1; the median implied net assets is within "
                   "0.5 pct of the filed figure in every quarter (4,527M against 4,530M at 2026-06-30).")],
        S + "ident_left.py %s" % label),
    ("oracle", "B01", SIXTH): (
        "as_filed",
        "Position contexts with no fair value fact: members the filer defines for rate and period facts or under an earlier "
        "spelling. No value is filed on them; the positions with values tie to the filed total.",
        [("query", "Sandbox n5c: 52 to 107 such contexts a quarter, none with a cost and at most two with a principal; "
                   "published equals the filed investments total within 0.5M in all 14 quarters.")],
        S + "b01.py %s 1925309" % label),
    ("oracle", "B01", GS): (
        "as_filed",
        "Position contexts with no fair value fact: undrawn commitments printed with a par amount and no cost or value, and "
        "members the filer defines for other facts. No value is filed on them.",
        [("query", "Sandbox n5c: 7 to 90 such contexts a quarter; 8 to 34 carry a principal and at most six a cost. Published "
                   "excluding the money market fund equals the filed total within 0.5M in all 13 quarters."),
         ("filing", "The pulled rule of D-059 had read two such rows (Auctane, Tiger Acquisition) as positions and invented "
                    "349.4M; the page prints them with a par amount only.")],
        S + "b01.py %s 1920145" % label),
}

csv.field_size_limit(10 ** 9)
open_by = defaultdict(set)
with open(SANDBOX / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        cik = row["cik"].zfill(10)
        if cik in NAMES and row["state"] in OUTSTANDING and row["report_date"][:10] >= "2022-01-01":
            open_by[(row["engine"], row["rule_name"], cik)].add(row["report_date"][:10])

import duckdb  # noqa: E402
first_schedule = dict(duckdb.connect().execute(
    "SELECT lpad(CAST(cik AS VARCHAR),10,'0'), min(CAST(report_date AS VARCHAR)[:10]) FROM read_parquet('%s') GROUP BY 1"
    % (SANDBOX / "output" / "private_markets_holdings.parquet").as_posix()).fetchall())
entries, held = [], []
for (engine, rule, cik), quarters in sorted(open_by.items()):
    if (engine, rule) in CHECKED:
        kind, statement, check, rerun = CHECKED[(engine, rule)]
        probe = {"disposition_id": "PD-%s-%s-%s" % (rule, cik[-7:], "probe"), "class": kind, "engine": engine, "rule_name": rule,
                 "ciks": [cik], "quarters": ["2021-12-31"], "carry_forward": check}
        results = {r["report_date"][:10]: r for r in dv.evaluate([probe], SANDBOX / "output")}
        passed = sorted(q for q in quarters if str(results.get(q, {}).get("passed")).lower() == "true")
        for q in sorted(quarters - set(passed)):
            r = results.get(q)
            held.append((cik, engine, rule, q, "check failed: %s of %s rows; %s" % (r["rows_failing"], r["rows_tested"], str(r["detail"])[:160])
                         if r else "check gave no result"))
        if passed:
            tested = sum(int(results[q]["rows_tested"]) for q in passed)
            entries.append({"disposition_id": "PD-%s-%s" % (rule, cik[-7:]), "class": kind, "engine": engine, "rule_name": rule,
                            "ciks": [cik], "quarters": passed, "statement": statement, "basis": "checked",
                            "evidence": [{"source": "query", "quote": "Check %s passed on sandbox %s for each quarter listed: %d flagged "
                                          "rows tested, none failing." % (check["check"], label, tested)}],
                            "rerun": rerun, "decided_by": WHO, "decided_on": WHEN})
    elif (engine, rule) == ("fund_financials", "F28") and first_schedule.get(cik):
        early = sorted(q for q in quarters if q < first_schedule[cik])
        for q in sorted(quarters - set(early)):
            held.append((cik, engine, rule, q, "not read"))
        if early:
            entries.append({"disposition_id": "PD-F28-%s" % cik[-7:], "class": "not_applicable", "engine": engine, "rule_name": rule,
                            "ciks": [cik], "quarters": early, "basis": "checked",
                            "statement": "Fund-level figures exist for these quarters but the cache holds no position schedule "
                                         "before the fund's first structured filing, so there are no holdings to compare.",
                            "evidence": [{"source": "query", "quote": "Sandbox %s: the fund's first quarter with published "
                                          "holdings is %s; each quarter listed is earlier." % (label, first_schedule[cik])}],
                            "rerun": "python scratch/2026-10-07_printed_rates/q.py %s scratch/2026-10-07_printed_rates/n5_tot.sql" % label,
                            "decided_by": WHO, "decided_on": WHEN})
    elif (engine, rule, cik) in READ:
        kind, statement, evidence, rerun = READ[(engine, rule, cik)]
        entries.append({"disposition_id": "PD-%s-%s" % (rule, cik[-7:]), "class": kind, "engine": engine, "rule_name": rule,
                        "ciks": [cik], "quarters": sorted(quarters), "statement": statement, "basis": "read",
                        "evidence": [{"source": s, "quote": q} for s, q in evidence], "rerun": rerun,
                        "decided_by": WHO, "decided_on": WHEN})
    else:
        for q in sorted(quarters):
            held.append((cik, engine, rule, q, "not read"))

for (engine, rule, cik), (read, kind, statement, evidence, rerun) in READ_QUARTERS.items():
    mine = sorted({q for (c, e, r, q, why) in held if (c, e, r) == (cik, engine, rule) and q in read})
    if not mine:
        continue
    held = [h for h in held if not (h[:3] == (cik, engine, rule) and h[3] in mine)]
    entries.append({"disposition_id": "PD-%s-%s-READ" % (rule, cik[-7:]), "class": kind, "engine": engine, "rule_name": rule,
                    "ciks": [cik], "quarters": mine, "statement": statement, "basis": "read",
                    "evidence": [{"source": s, "quote": q} for s, q in evidence], "rerun": rerun,
                    "decided_by": WHO, "decided_on": WHEN})

for entry in entries:
    problems = fd.validate({k: v for k, v in entry.items() if k != "basis"})
    assert not problems, (entry["disposition_id"], problems)

# What the ledger would show if every proposal were accepted: a temporary store, nothing live is touched.
import findings_ledger  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "store"
    shutil.copytree(fd.default_dir(), store)
    (store / "proposed.json").write_text(json.dumps({"dispositions": [{k: v for k, v in e.items() if k != "basis"} for e in entries]}), encoding="utf-8")
    ledger = findings_ledger.build_ledger(queue_path=SANDBOX / "output" / "review_queue" / "review_queue.csv", dispositions_dir=store,
                                          validity_path=SANDBOX / "disposition_validity.csv")
left = defaultdict(int)
for row in ledger:
    cik = str(row["cik"]).zfill(10)
    if cik in NAMES and row["state"] in OUTSTANDING and str(row["report_date"])[:10] >= "2022-01-01":
        left[cik] += 1
now = defaultdict(int)
for (engine, rule, cik), quarters in open_by.items():
    now[cik] += len(quarters)
proposed = defaultdict(int)
for entry in entries:
    proposed[entry["ciks"][0]] += len(entry["quarters"])
print("fund | outstanding now | covered by a proposal | outstanding if all accepted")
for cik in NAMES:
    print("   %s %s | %d | %d | %d" % (cik, NAMES[cik], now[cik], proposed[cik], left[cik]))
print("   total | %d | %d | %d" % (sum(now.values()), sum(proposed.values()), sum(left.values())))
print("proposals: %d (checked %d, read %d) | findings left open: %d" % (
    len(entries), sum(e["basis"] == "checked" for e in entries), sum(e["basis"] == "read" for e in entries), len(held)))
groups = defaultdict(list)
for cik, engine, rule, quarter, why in held:
    groups[(cik, engine, rule, why if why == "not read" else "check failed")].append(quarter)
for (cik, engine, rule, why), quarters in sorted(groups.items()):
    print("   open | %s | %s/%s | %d | %s" % (NAMES[cik], engine, rule, len(quarters), why))

if "--write" in sys.argv:
    target = REPO / "data/overrides/finding_dispositions_proposed/next5_2026-10-08.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"status": "PROPOSED, not accepted. The findings ledger does not read this directory.",
                                  "sandbox": label, "dispositions": entries}, indent=1) + "\n", encoding="utf-8")
    lines = ["# Next five funds: proposed dispositions (not accepted)", "",
             "Generated by `scripts/v05_evidence/make_proposed_dispositions.py %s --write` on 2026-10-08." % label,
             "Nothing here is in force. `checked` means the first five's reason passed its row-by-row test on these",
             "funds; `read` means the reason was found on the page or in the tags this session.", "",
             "| Fund | Outstanding now | Covered by a proposal | Outstanding if all accepted |", "|---|---|---|---|"]
    lines += ["| %s | %d | %d | %d |" % (NAMES[c], now[c], proposed[c], left[c]) for c in NAMES]
    lines += ["| **Total** | **%d** | **%d** | **%d** |" % (sum(now.values()), sum(proposed.values()), sum(left.values())), "",
              "## Proposals", "", "| Fund | Rule | Class | Basis | Quarters | Reason |", "|---|---|---|---|---|---|"]
    lines += ["| %s | %s | %s | %s | %d | %s |" % (NAMES[e["ciks"][0]], e["rule_name"], e["class"], e["basis"], len(e["quarters"]), e["statement"])
              for e in sorted(entries, key=lambda e: (e["ciks"][0], e["rule_name"]))]
    lines += ["", "## Left open", "", "| Fund | Rule | Findings | Why |", "|---|---|---|---|"]
    lines += ["| %s | %s/%s | %d | %s |" % (NAMES[cik], engine, rule, len(quarters), why) for (cik, engine, rule, why), quarters in sorted(groups.items())]
    doc = REPO / "docs/investigations/next5_proposed_dispositions.md"
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", target.relative_to(REPO), "and", doc.relative_to(REPO))
