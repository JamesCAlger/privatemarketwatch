"""Read-only: printed "Total <group>" lines of a filing against published rows grouped by a holdings column, to
localise a gap between published and filed totals.

    python scripts/v05_evidence/industry_totals.py <label> <cik> <accession no dashes> <quarter> [column]

The printed fair value is taken as the last of the two or three numbers that follow "Total <name>". Only groups
whose name matches a value of the column (case and punctuation ignored) are compared.
"""
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik, accession, quarter = sys.argv[1], sys.argv[2].zfill(10), sys.argv[3], sys.argv[4]
column = sys.argv[5] if len(sys.argv) > 5 else "extracted_industry"
raw = (REPO / "data/raw/filings/bdc_html" / cik.lstrip("0") / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw).replace("&#160;", " ").replace("&nbsp;", " ").replace("&amp;", "&").replace("&#8217;", "'"))


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
groups = con.execute(f"""SELECT coalesce(CAST({column} AS VARCHAR), ''), sum(TRY_CAST(fair_value AS DOUBLE)), count(*)
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
      AND coalesce(accounting_record_class,'') <> 'underlying_schedule' AND coalesce(asset_category,'') <> 'CASH' GROUP BY 1""", [cik, quarter]).fetchall()
published = {norm(name): (name, value or 0.0, n) for name, value, n in groups}
printed = {}
for match in re.finditer(r"Total ([A-Z][A-Za-z,&'/\- ]{3,70}?)(?: - non-controlled/non-affiliated)? \$? ?([\d,]+) \$? ?([\d,]+)(?: \$? ?([\d,]+))?(?= )", text):
    key = norm(match.group(1))
    if key in published and key not in printed:
        numbers = [g for g in match.groups()[1:] if g]
        printed[key] = [int(n.replace(",", "")) * 1000 for n in numbers]
print("column %s: %d groups published, %d matched to a printed total; rows with an empty group: %s"
      % (column, len(published), len(printed), published.get("", ("", 0, 0))[2]))
print("group | rows | published $K | printed numbers $K | smallest gap $K")
for key, (name, value, n) in sorted(published.items()):
    if key not in printed:
        continue
    gaps = [value - p for p in printed[key]]
    best = min(gaps, key=abs)
    if abs(best) >= 500:
        print("   %s | %d | %d | %s | %d" % (name, n, value / 1000, [p // 1000 for p in printed[key]], best / 1000))
