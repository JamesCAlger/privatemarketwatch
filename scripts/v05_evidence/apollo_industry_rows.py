"""Read-only: for one Apollo industry and quarter, published fair values that are not printed in that industry's
section of the schedule, and the printed text of the section, to find the row behind a gap.

    python scripts/v05_evidence/apollo_industry_rows.py <label> <accession no dashes> <quarter> "<Industry>" [show]
"""
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, accession, quarter, industry = sys.argv[1:5]
raw = (REPO / "data/raw/filings/bdc_html/1837532" / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw).replace("&#160;", " ").replace("&nbsp;", " ").replace("&amp;", "&").replace("&#8217;", "'").replace("&#8212;", "-"))
stop = text.find("Total " + industry + " ")
before = text[:stop]
start = max(before.rfind("Total "), 0)
section = text[start:stop + 120]
printed_numbers = {int(n.replace(",", "")) for n in re.findall(r"(?<![\d.,])\d{1,3}(?:,\d{3})*(?![\d.,%])", section)}
printed_negative = {int(n.replace(",", "")) for n in re.findall(r"\( ?(\d{1,3}(?:,\d{3})*) ?\)", section)}
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
rows = duckdb.connect().execute(f"""SELECT CAST(bdc_investment_identifier AS VARCHAR), TRY_CAST(fair_value AS DOUBLE), TRY_CAST(cost AS DOUBLE), src_context_id
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '0001837532'
      AND CAST(report_date AS VARCHAR)[:10] = ? AND starts_with(lower(CAST(bdc_investment_identifier AS VARCHAR)), lower(?) || ' ')
    ORDER BY 1""", [quarter, industry]).fetchall()
print("section chars:", len(section), "| published rows:", len(rows), "| published sum $K:", round(sum(r[1] or 0 for r in rows) / 1000))
print("published fair values not printed in the section: fv $K | cost $K | context | id")
for identifier, value, cost, ctx in rows:
    k = int(round(abs(value or 0) / 1000))
    pool = printed_negative if (value or 0) < 0 else printed_numbers
    if k and k not in pool:
        print("   %s | %s | %s | %s" % (round((value or 0) / 1000), None if cost is None else round(cost / 1000), ctx, identifier[len(industry) + 1:140]))
if len(sys.argv) > 5:
    print(section[:int(sys.argv[5])])
