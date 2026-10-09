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
LIVE_NAME = "next5_owner_accepted.json"
LIVE = ("accepted", "accepted by check")
ASIF, GS, GOLUB, SIXTH, OAKTREE = "0001918712", "0001920145", "0001930087", "0001925309", "0001872371"
NAMES = {ASIF: "Ares Strategic Income", GS: "Goldman Sachs Private Credit", GOLUB: "Golub Capital Private Credit",
         SIXTH: "Sixth Street Lending Partners", OAKTREE: "Oaktree Strategic Credit"}
WHO, WHEN = "PROPOSED by agent 2026-10-08; not accepted by the owner", "2026-10-08"
S = "python scripts/v05_evidence/"
SANDBOX = REPO / "scratch/fund_sandbox" / label
OUTSTANDING = {"open", "needs_human", "evidence_backlog", "real_error_unremediated", "remediation_pulled", "remediation_staged"}
_FILED = lambda *fields: {"from": "2022-01-01", "check": "values_as_filed", "params": {"fields": list(fields)}}
_NO_RATE = {"from": "2022-01-01", "check": "no_rate_in_source", "params": {}}

# Entries the owner accepted by name. They go to the live store; everything else stays a proposal.
# 2026-10-09, on the Goldman Sachs members with no value: "keep the undrawn lines".
OWNER_ACCEPTED = {("oracle", "B01", GS): ("owner, in session 2026-10-09", "2026-10-09")}

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
        {"2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"}, "as_filed",
        "Rows printed with no rate: private asset-backed investments, the lowest tranche of collateralized loan "
        "obligations, and (2026-03-31) three loans of one issuer marked down and printed with no rate.",
        [("filing", "0001918712-25-000065 (10-Q, 2025-06-30): 'Quintain Investments Holdings Limited (11) Private asset-backed "
                    "investment 08/2031 32,775.6 42,469.6 48,861.1'; 'STKPK 2022-1 ... Collaterized loan obligation 10/2037 "
                    "20,240.0 194.4 602.8'; 'CLRMPK 2025-1 ... Collaterized loan obligation 04/2038 15,725.0 - 573.5'; 'BERRY "
                    "2024-1 ... Collaterized loan obligation 10/2037 2,610.0 - 154.4'. The tranches above each print a rate."),
         ("filing", "0001628280-26-034133 (2026-03-31): 'Avalign Holdings, Inc. and Avalign Technologies, Inc. First lien "
                    "senior secured revolving loan 12/2028 2,344.9 2,283.2 1,373.3 ... First lien senior secured loan 12/2028 "
                    "16,873.3 16,684.3 12,108.3'; 'Kohlberg Private Credit Investors Rated Feeder-L ... Private asset-backed "
                    "investment 12/2036 513.8 513.8 513.8'."),
         ("query", "The Steward Partners row flagged at 2025-12-31 and 2026-03-31 is a warrant tagged on a member that names "
                   "a loan; it is corrected from the page (D-074). Not covered: 2026-06-30, not read.")],
        S + "filing_grep.py 1918712 000191871225000065 html \"STKPK 2022-1\" 8 330"),
    ("row_validation", "X02", OAKTREE): (
        {"2023-03-31", "2023-06-30", "2023-09-30", "2024-09-30"}, "as_filed",
        "Loans printed with no rate. No rate is tagged or printed for them.",
        [("filing", "0001872371-23-000008 (2023-03-31): 'Impel Neuropharma, Inc. Health Care Technology First Lien Term Loan "
                    "2/15/2031 5,408 5,408 5,284'. 0001872371-23-000017 (2023-09-30): 'BioXcel Therapeutics, Inc. "
                    "Pharmaceuticals First Lien Term Loan 9/30/2032 1,580 1,580 1,510'. 0001872371-24-000014 (2024-09-30): "
                    "'Verona Pharma, Inc. Pharmaceuticals First Lien Term Loan 5/9/2029 $ 9,177 $ 9,177 $ 9,269'. The other "
                    "tranches of each issuer print a rate."),
         ("query", "The one row in these quarters that does print a rate (Impel, 2023-09-30, 'SOFR+ 10.75 % 16.06 %') is "
                   "corrected from the page (D-074). Not covered: 2024-06-30, not read.")],
        S + "filing_grep.py 1872371 000187237123000017 html \"BioXcel Therapeutics, Inc.\" 20 330"),
    ("row_validation", "FX03", OAKTREE): (
        {"2026-06-30"}, "not_applicable",
        "The two rows belong to the joint venture's own schedule, which is kept but not published. The page prints their "
        "cost and value in euros and the tags say euros.",
        [("filing", "0001872371-26-000013 (2026-06-30), joint venture schedule: 'ACESO Holding 4 S.A.R.L. ... 9/27/2031 "
                    "EUR 890 EUR 882 EUR 882'; 'Empire Bidco AB ... 9/22/2032 GBP 2,279 EUR 2,596 EUR 2,599'."),
         ("query", "Sandbox n5e: 47 rows on contexts c-1400 and above, 107.1M, all classed underlying_schedule. The "
                   "published rows of the same two issuers are in dollars and equal the printed schedule.")],
        "python scratch/2026-10-07_printed_rates/q.py %s scratch/2026-10-07_printed_rates/oak5.sql" % label),
    ("row_validation", "SRC_BDC03", OAKTREE): (
        {"2026-06-30"}, "not_applicable", "The same two joint-venture rows as FX03: the source value is in euros.",
        [("filing", "See the FX03 entry for Oaktree: the joint venture schedule prints both rows in euros.")],
        "python scratch/2026-10-07_printed_rates/q.py %s scratch/2026-10-07_printed_rates/oak4.sql" % label),
    ("source_recon", "blocking_fair_value_disagreement", OAKTREE): (
        {"2026-06-30"}, "not_applicable", "The same two joint-venture rows as FX03, reported by the reconciliation's second engine.",
        [("filing", "See the FX03 entry for Oaktree: the joint venture schedule prints both rows in euros.")],
        "python scratch/2026-10-07_printed_rates/q.py %s scratch/2026-10-07_printed_rates/oak4.sql" % label),
    ("row_validation", "X07", GS): (
        {"2024-03-31"}, "as_filed", "One loan is printed and tagged with a cost of 1 against a fair value of 166 (thousands).",
        [("filing", "0000950170-24-056854 (2024-03-31): 'LCG Vardiman Black, LLC (dba Specialty Dental Brands) Health Care "
                    "Providers & Services 12.43 % S + 7.00 % 03/18/27 $ 2,439 $ 1 $ 166'.")],
        S + "filing_grep.py 1920145 000095017024056854 html \"LCG Vardiman Black\" 12 200"),
    ("oracle", "A04", SIXTH): (
        {"2023-06-30", "2023-09-30"}, "not_applicable",
        "The fund-level data holds no filed investments figure for these two quarters, so the check compared the holdings "
        "with total assets. The holdings equal the printed schedule total.",
        [("filing", "0000950170-23-038548 (2023-06-30): 'Total Investments $ 1,744,507 $ 1,758,911'. 0000950170-23-058792 "
                    "(2023-09-30): 'Total Investments $ 2,007,948 $ 2,048,389'."),
         ("query", "Published: 1,758,911 thousand and 2,048,389 thousand. Open defect, not closed by this entry: the "
                   "investments figure is missing from fund_financials for both quarters.")],
        S + "filing_grep.py 1925309 000095017023058792 html \"Total Investments\" 12 110"),
    ("oracle", "E01", SIXTH): (
        {"2023-06-30", "2023-09-30"}, "not_applicable", "The same comparison with total assets as A04.",
        [("filing", "See the A04 entry for Sixth Street: published equals the printed 'Total Investments' in both quarters.")],
        S + "filing_grep.py 1925309 000095017023058792 html \"Total Investments\" 12 110"),
    ("oracle", "B07", GOLUB): (
        {"2025-09-30"}, "as_filed", "The year-end has two filings, a 10-K and a 10-K/A. Their schedules are identical.",
        [("query", "Sandbox n3a flat file: 0001930087-25-000070 (10-K) and 0001930087-26-000078 (10-K/A), 909 rows and "
                   "8,555.3M each at 2025-09-30. One is published.")],
        "python scratch/2026-10-07_printed_rates/q.py %s scratch/2026-10-07_printed_rates/gol6.sql" % label),
    ("fund_financials", "F33", SIXTH): (
        {"2024-12-31"}, "as_filed",
        "The quarter's distribution per share is the filed year figure less the filed nine-month figure.",
        [("query", "Company facts, InvestmentCompanyDistributionToShareholdersPerShare: 2.01 for 2024-01-01 to 2024-09-30 "
                   "(10-Q) and 4.54 for the year (10-K). The fourth quarter is 2.53, on a net asset value of 28.79."),
         ("filing", "0000950170-25-021144 (10-K): 'Dividends declared during the period $ 478,109' for 2024.")],
        S + "companyfacts_concept.py 1925309 DistributionToShareholdersPerShare 2024"),
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
        [("filing", "Every failing row read on its filing page (2026-10-09): 60 rows in 12 filings, each published with the "
                    "percent and the fair value the page prints. Examples: 2023-12-31 Bleriot US Bidco, printed '0.5' on 3,001 "
                    "(the value implies 0.44); 2025-12-31 AQA Acquisition Holding, printed '0.6' on 24,058 (implies 0.54)."),
         ("query", "The median implied net assets is within 1 pct of the filed figure in every quarter (4,448M against 4,475M "
                   "at 2026-06-30), so the percents are read at the right scale.")],
        S + "pct_rows_on_page.py %s 1930087" % label),
    ("identity", "pct_of_net_assets_identity", SIXTH): (
        "as_filed",
        "One to seven rows a quarter, out of 38 to 108, carry a filed percent that disagrees with their fair value. The "
        "published percent is the tagged fact, printed to one decimal.",
        [("filing", "Every failing row read on its filing page (2026-10-09): 27 rows in 9 filings, each published with the "
                    "percent and the fair value the page prints. Examples: 2024-12-31 Erling Lux Bidco, printed '0.3' on 7,650 "
                    "(the value implies 0.19); 2026-03-31 Shiftmove GMBH, printed '0.3' on 18,435 (implies 0.44)."),
         ("query", "The median implied net assets is within 0.5 pct of the filed figure in every quarter (4,527M against "
                   "4,530M at 2026-06-30), so the percents are read at the right scale.")],
        S + "pct_rows_on_page.py %s 1925309" % label),
    ("oracle", "C04", GOLUB): (
        "as_filed",
        "A few equity rows are printed with a dash in the share column, or have their unit count tagged as a principal "
        "amount. Most equity rows carry units.",
        [("filing", "0001930087-25-000030 (2025-03-31): 'Eclipse Buyer, Inc. Preferred stock N/A 12.50 % Non-Cash 09/2024 N/A "
                    "- 3,543 0.1 3,607' (no units printed); 'PB Group Holdings, LLC LP units N/A N/A 08/2024 N/A 113 262 - 330' "
                    "(the 113 is tagged as a principal amount)."),
         ("query", "Sandbox n5f, 2025-03-31: 25 of 28 equity rows publish a unit count.")],
        "python scratch/2026-10-07_printed_rates/q.py %s scratch/2026-10-07_printed_rates/gol12.sql" % label),
    ("weak", "fmt_interest_rate", ASIF): (
        "as_filed", "One collateralized loan obligation is printed with a rate of 27.20 %.",
        [("filing", "0001918712-25-000065 (2025-06-30): 'Riviera Loan Funding Warehouse 72, Ltd. Collaterized loan obligation "
                    "27.20 % 03/2035 1,519.0 1,519.0 1,519.0'.")],
        S + "filing_grep.py 1918712 000191871225000065 html \"Riviera Loan Funding Warehouse 72\" 12 260"),
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

# Owner standing instruction 2026-10-09 (decision D-073): "a disposition i already accepted may be
# accepted by its check". The reasons in CHECKED, and the F28 reason, are the first five's accepted
# entries DS-003 to DS-007; a fund-quarter where the row-by-row check passes is accepted by that check.
BY_CHECK = "check passed on sandbox %s; accepted under the owner's standing instruction of 2026-10-09 (D-073)" % label
for entry in entries:
    accepted = OWNER_ACCEPTED.get((entry["engine"], entry["rule_name"], entry["ciks"][0]))
    if accepted:
        entry["decided_by"], entry["decided_on"], entry["basis"] = accepted[0], accepted[1], "accepted"
    elif entry["basis"] == "checked":
        entry["decided_by"], entry["decided_on"], entry["basis"] = BY_CHECK, "2026-10-09", "accepted by check"
    if entry["basis"] in LIVE:
        entry["disposition_id"] = entry["disposition_id"].replace("PD-", "DS-N5-")

for entry in entries:
    problems = fd.validate({k: v for k, v in entry.items() if k != "basis"})
    assert not problems, (entry["disposition_id"], problems)

# What the ledger would show if every proposal were accepted: a temporary store, nothing live is touched.
import findings_ledger  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "store"
    shutil.copytree(fd.default_dir(), store)
    # the live file already holds what the owner accepted; add only what is still a proposal
    (store / "proposed.json").write_text(json.dumps({"dispositions": [{k: v for k, v in e.items() if k != "basis"}
                                                                      for e in entries if e["basis"] not in LIVE]}), encoding="utf-8")
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
print("entries: %d (accepted by the owner %d, accepted by a check %d, proposed on a reading %d) | findings left open: %d" % (
    len(entries), sum(e["basis"] == "accepted" for e in entries), sum(e["basis"] == "accepted by check" for e in entries),
    sum(e["basis"] == "read" for e in entries), len(held)))
groups = defaultdict(list)
for cik, engine, rule, quarter, why in held:
    groups[(cik, engine, rule, why if why == "not read" else "check failed")].append(quarter)
for (cik, engine, rule, why), quarters in sorted(groups.items()):
    print("   open | %s | %s/%s | %d | %s" % (NAMES[cik], engine, rule, len(quarters), why))

if "--write" in sys.argv:
    target = REPO / "data/overrides/finding_dispositions_proposed/next5_2026-10-08.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"status": "PROPOSED, not accepted. The findings ledger does not read this directory.",
                                  "sandbox": label, "dispositions": [e for e in entries if e["basis"] not in LIVE]},
                                 indent=1) + "\n", encoding="utf-8")
    # An accepted entry closes its findings, so a later run no longer sees them as open and would
    # not produce the entry again: keep what the live file already holds, replace only by id.
    live = fd.default_dir() / LIVE_NAME
    kept = {e["disposition_id"]: e for e in (json.loads(live.read_text(encoding="utf-8"))["dispositions"] if live.exists() else [])}
    for e in entries:
        if e["basis"] in LIVE:
            quarters = sorted(set(e["quarters"]) | set(kept.get(e["disposition_id"], {}).get("quarters", [])))
            kept[e["disposition_id"]] = {**{k: v for k, v in e.items() if k != "basis"}, "quarters": quarters}
    live.write_text(json.dumps({"dispositions": [kept[k] for k in sorted(kept)]}, indent=1) + "\n", encoding="utf-8")
    lines = ["# Next five funds: proposed dispositions (not accepted)", "",
             "Generated by `scripts/v05_evidence/make_proposed_dispositions.py %s --write` on 2026-10-08." % label,
             "`accepted` entries are in force (the owner accepted them by name; live store, `%s`). The rest are not." % LIVE_NAME,
             "`accepted by check` means a reason the owner accepted for the first five passed its row-by-row test on",
             "this fund-quarter (standing instruction, D-073); those are in force too. `read` means the reason was",
             "found on the page or in the tags and is still a proposal.", "",
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
