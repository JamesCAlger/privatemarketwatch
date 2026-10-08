"""Read-only: Ares issuer names across the change of member format at 2026-06-30.

    python scripts/v05_evidence/ares_member_format.py <label> [label before the wrapper change]

1. share of a quarter's issuers that were present in the quarter before, last four quarters;
2. member forms (pipe / comma) by quarter;
3. with a second label: rows before 2026-06-30 whose issuer name or instrument differs.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
CIK = "0001287750"


def holdings(label):
    path = (REPO / "scratch/fund_sandbox" / label / "output/private_markets_holdings.parquet").as_posix()
    return f"""(SELECT *, CAST(report_date AS VARCHAR)[:10] AS q FROM read_parquet('{path}')
        WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{CIK}' AND coalesce(accounting_record_class,'')<>'underlying_schedule')"""


con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
H = holdings(sys.argv[1])
print("1. quarter | issuers | also present the quarter before | share")
for r in con.execute(f"""WITH i AS (SELECT DISTINCT q, CAST(issuer_name AS VARCHAR) AS issuer FROM {H}),
        d AS (SELECT DISTINCT q FROM i), p AS (SELECT q, lag(q) OVER (ORDER BY q) AS prev FROM d)
    SELECT i.q, count(*), count(j.issuer), round(100.0*count(j.issuer)/count(*),1)
    FROM i JOIN p ON p.q=i.q LEFT JOIN i j ON j.q=p.prev AND j.issuer=i.issuer
    WHERE i.q >= '2025-09-30' GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
print("2. quarter | members with a pipe | members without")
for r in con.execute(f"""SELECT q, count(*) FILTER (WHERE contains(CAST(bdc_dimensions_raw AS VARCHAR),'|')),
        count(*) FILTER (WHERE NOT contains(CAST(bdc_dimensions_raw AS VARCHAR),'|')) FROM {H} WHERE q >= '2025-09-30' GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
if len(sys.argv) > 2:
    B = holdings(sys.argv[2])
    r = con.execute(f"""SELECT count(*), count(*) FILTER (WHERE a.issuer_name IS DISTINCT FROM b.issuer_name),
            count(*) FILTER (WHERE a.instrument_description IS DISTINCT FROM b.instrument_description)
        FROM {H} a JOIN {B} b USING (accession_number, q, src_context_id) WHERE q < '2026-06-30'""").fetchone()
    print("3. rows before 2026-06-30 compared %s | issuer name differs %s | instrument differs %s" % r)
