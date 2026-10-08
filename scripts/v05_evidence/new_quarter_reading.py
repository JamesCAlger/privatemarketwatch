"""Read-only: first reading of a new quarter in a sandbox, against the sandbox without it.

    python scripts/v05_evidence/new_quarter_reading.py <label with the quarter> <label without> <quarter>

1. published against filed investments per fund at the quarter (cash equivalents shown apart: the
   filed figure is investments before cash equivalents);
2. findings at the quarter by state, and the outstanding ones by fund and rule;
3. whether earlier quarters moved: findings and published rows / fair value before the quarter, both sandboxes.
"""
import csv
import sys
from collections import Counter
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
new, old, quarter = sys.argv[1], sys.argv[2], sys.argv[3]
FUNDS = {"0001803498": "BCRED", "0001812554": "Blue Owl", "0001287750": "Ares", "0001838126": "HPS", "0001837532": "Apollo"}
RESOLVED = {"adjudicated_false_alarm", "remediated_promoted", "resolved_upstream", "gone_unadjudicated",
            "dispositioned_informational", "dispositioned_as_filed", "dispositioned_not_applicable"}


def out(name):
    return (REPO / "scratch/fund_sandbox" / name / "output").as_posix()


def ledger(name):
    csv.field_size_limit(10**9)
    with open(REPO / "scratch/fund_sandbox" / name / "findings_ledger.csv", newline="", encoding="utf-8-sig") as handle:
        return [r for r in csv.DictReader(handle) if r["report_date"][:10] >= "2022-01-01"]


con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
print("1. %s: fund | published excluding cash equivalents $M | rows | filed investments $M | difference $M | cash equivalents published $M" % quarter)
for r in con.execute(f"""WITH h AS (SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, sum(TRY_CAST(fair_value AS DOUBLE)) FILTER (WHERE coalesce(index_classification,'')<>'CASH')/1e6 AS fv, count(*) AS n, coalesce(sum(TRY_CAST(fair_value AS DOUBLE)) FILTER (WHERE index_classification='CASH'),0)/1e6 AS cash
        FROM read_parquet('{out(new)}/private_markets_holdings.parquet')
        WHERE CAST(report_date AS VARCHAR)[:10]='{quarter}' AND coalesce(accounting_record_class,'')<>'underlying_schedule' GROUP BY 1),
    f AS (SELECT lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0') AS cik, max(TRY_CAST(investments_at_fair_value AS DOUBLE))/1e6 AS filed
        FROM read_csv('{out(new)}/fund_financials.csv', header=true, all_varchar=true, sample_size=-1)
        WHERE CAST(report_date AS VARCHAR)[:10]='{quarter}' GROUP BY 1)
    SELECT cik, round(fv,1), n, round(filed,1), round(fv-filed,1), round(cash,1) FROM h FULL JOIN f USING (cik) ORDER BY 1""").fetchall():
    print("   %s %s" % (FUNDS.get(r[0], r[0]), " | ".join(str(v) for v in r[1:])))

rows = ledger(new)
at = [r for r in rows if r["report_date"][:10] == quarter]
print("2. findings at %s: %d; by state:" % (quarter, len(at)))
for state, n in Counter(r["state"] for r in at).most_common():
    print("   %s | %d%s" % (state, n, "" if state in RESOLVED else "   <- outstanding"))
print("   outstanding at the quarter: fund | engine | rule | findings")
for (cik, engine, rule), n in sorted(Counter((r["cik"].zfill(10), r["engine"], r["rule_name"]) for r in at if r["state"] not in RESOLVED).items()):
    print("   %s | %s | %s | %d" % (FUNDS.get(cik, cik), engine, rule, n))

before_new = [r for r in rows if r["report_date"][:10] < quarter]
before_old = [r for r in ledger(old) if r["report_date"][:10] < quarter]
print("3. before %s: findings %d (was %d), outstanding %d (was %d)" % (
    quarter, len(before_new), len(before_old), sum(r["state"] not in RESOLVED for r in before_new),
    sum(r["state"] not in RESOLVED for r in before_old)))
key = lambda r: (r["cik"].zfill(10), r["engine"], r["rule_name"], r["report_date"][:10])
gained = Counter(key(r) for r in before_new) - Counter(key(r) for r in before_old)
lost = Counter(key(r) for r in before_old) - Counter(key(r) for r in before_new)
for name, bag in (("new in earlier quarters", gained), ("gone from earlier quarters", lost)):
    for k, n in sorted(bag.items()):
        print("   %s: %s | %s | %s | %s | %d" % (name, FUNDS.get(k[0], k[0]), k[1], k[2], k[3], n))
print("   published rows and fair value before the quarter: fund | rows here | rows there | $M here | $M there | quarters that differ")
for r in con.execute(f"""WITH a AS (SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS q, count(*) AS n, sum(TRY_CAST(fair_value AS DOUBLE))/1e6 AS fv
        FROM read_parquet('{out(new)}/private_markets_holdings.parquet') WHERE coalesce(accounting_record_class,'')<>'underlying_schedule' GROUP BY 1,2),
    b AS (SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS q, count(*) AS n, sum(TRY_CAST(fair_value AS DOUBLE))/1e6 AS fv
        FROM read_parquet('{out(old)}/private_markets_holdings.parquet') WHERE coalesce(accounting_record_class,'')<>'underlying_schedule' GROUP BY 1,2)
    SELECT coalesce(a.cik,b.cik), sum(a.n), sum(b.n), round(sum(a.fv),1), round(sum(b.fv),1),
        string_agg(CASE WHEN a.n IS DISTINCT FROM b.n OR abs(coalesce(a.fv,0)-coalesce(b.fv,0))>0.05 THEN coalesce(a.q,b.q) END, ' ')
    FROM a FULL JOIN b USING (cik, q) WHERE coalesce(a.q,b.q) < '{quarter}' GROUP BY 1 ORDER BY 1""").fetchall():
    print("   %s %s" % (FUNDS.get(r[0], r[0]), " | ".join(str(v) for v in r[1:])))
