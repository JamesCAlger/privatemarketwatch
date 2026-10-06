"""Read-only: Apollo printed industry totals against the published rows for one quarter, to localise a gap to an industry.

The printed schedule ends each industry with "Total <Industry> $ cost $ fair value". The published identifier starts
with the industry name.

    python scripts/v05_evidence/apollo_industry_totals.py <label> <accession no dashes> <quarter>
"""
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, accession, quarter = sys.argv[1], sys.argv[2], sys.argv[3]
raw = (REPO / "data/raw/filings/bdc_html/1837532" / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw).replace("&#160;", " ").replace("&nbsp;", " ").replace("&amp;", "&").replace("&#8217;", "'"))
end = text.find("Total Investments before Cash Equivalents")
section = text[:end]
printed = {}
for match in re.finditer(r"Total ([A-Z][A-Za-z,&'\- ]+?) \$? ?([\d,]+) \$? ?([\d,]+)(?= )", section):
    name = match.group(1).strip()
    printed[name.lower()] = (name, int(match.group(3).replace(",", "")) * 1000)
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
rows = duckdb.connect().execute(f"""SELECT CAST(bdc_investment_identifier AS VARCHAR), TRY_CAST(fair_value AS DOUBLE)
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '0001837532'
      AND CAST(report_date AS VARCHAR)[:10] = ? AND coalesce(asset_category,'') <> 'CASH'""", [quarter]).fetchall()
names = sorted(printed, key=len, reverse=True)
sums, unmatched = {}, []
for identifier, value in rows:
    low = identifier.lower()
    key = next((n for n in names if low.startswith(n + " ")), None)
    if key is None:
        unmatched.append((identifier[:80], value))
    else:
        sums[key] = sums.get(key, 0.0) + (value or 0.0)
print("industries printed:", len(printed), "| published rows:", len(rows), "| rows with no industry match:", len(unmatched))
print("printed total of industries $M:", round(sum(v for _, v in printed.values()) / 1e6, 3), "| published matched $M:", round(sum(sums.values()) / 1e6, 3))
print("industry | printed $K | published $K | gap $K")
for key in sorted(printed):
    name, value = printed[key]
    gap = sums.get(key, 0.0) - value
    if abs(gap) >= 1000:
        print("   %s | %d | %d | %d" % (name, value / 1000, sums.get(key, 0.0) / 1000, gap / 1000))
for identifier, value in unmatched[:12]:
    print("   unmatched:", identifier, value)
