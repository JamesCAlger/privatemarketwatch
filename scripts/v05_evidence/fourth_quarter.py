"""Read-only: fund-level year-end figures before and after the fourth-quarter fix.

    python scripts/v05_evidence/fourth_quarter.py <label> <before label>
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
con = duckdb.connect()


def table(label):
    path = (REPO / "scratch/fund_sandbox" / label / "output/fund_financials.csv").as_posix()
    return f"(SELECT * FROM read_csv('{path}', header=true, all_varchar=true, sample_size=-1) WHERE source='companyfacts' AND report_date>='2022-01-01')"


A, B = table(sys.argv[1]), table(sys.argv[2])
FIELDS = ("total_investment_income", "net_investment_income", "total_expenses", "management_fee", "incentive_fee", "interest_expense", "net_expenses")
print("field | fund-quarters changed | of which year-end | negative now | emptied")
for f in FIELDS:
    r = con.execute(f"""SELECT count(*) FILTER (WHERE TRY_CAST(a.{f} AS DOUBLE) IS DISTINCT FROM TRY_CAST(b.{f} AS DOUBLE)),
        count(*) FILTER (WHERE TRY_CAST(a.{f} AS DOUBLE) IS DISTINCT FROM TRY_CAST(b.{f} AS DOUBLE) AND a.report_date LIKE '%-12-31'),
        count(*) FILTER (WHERE TRY_CAST(a.{f} AS DOUBLE) < 0), count(*) FILTER (WHERE TRY_CAST(a.{f} AS DOUBLE) IS NULL AND TRY_CAST(b.{f} AS DOUBLE) IS NOT NULL)
        FROM {A} a JOIN {B} b USING (cik, report_date)""").fetchone()
    print("   %s | %s | %s | %s | %s" % ((f,) + tuple(r)))
print("other columns that differ (count of fund-quarters):")
columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {A}").fetchall() if r[0] not in FIELDS + ("cik", "report_date")]
for c in columns:
    n = con.execute(f"""SELECT count(*) FROM {A} a JOIN {B} b USING (cik, report_date) WHERE a."{c}" IS DISTINCT FROM b."{c}"
        AND NOT coalesce(abs(TRY_CAST(a."{c}" AS DOUBLE)-TRY_CAST(b."{c}" AS DOUBLE))<=1e-9*greatest(abs(TRY_CAST(a."{c}" AS DOUBLE)),1),false)""").fetchone()[0]
    if n:
        print("   %s | %d" % (c, n))
print("year-end total investment income, $M: cik | date | before | after")
for r in con.execute(f"""SELECT cik, report_date, round(TRY_CAST(b.total_investment_income AS DOUBLE)/1e6,1), round(TRY_CAST(a.total_investment_income AS DOUBLE)/1e6,1)
    FROM {A} a JOIN {B} b USING (cik, report_date) WHERE report_date LIKE '%-12-31' ORDER BY 1,2""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
