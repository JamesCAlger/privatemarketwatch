"""Read-only: published rows of a fund-quarter whose fair value (in thousands) does not appear anywhere in the printed
schedule of the filing, up to an end marker. A way to find rows behind a gap to the printed total.

    python scripts/v05_evidence/unprinted_values.py <label> <cik> <accession no dashes> <quarter> "<end marker>" [scale]

scale: 1000 when the schedule is printed in thousands (default), 1000000 with one decimal for millions.
"""
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik, accession, quarter, marker = sys.argv[1], sys.argv[2].zfill(10), sys.argv[3], sys.argv[4], sys.argv[5]
raw = (REPO / "data/raw/filings/bdc_html" / cik.lstrip("0") / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw).replace("&#160;", " ").replace("&nbsp;", " ").replace("&amp;", "&"))
end = text.find(marker)
if end < 0:
    raise SystemExit("marker not found")
section = text[:end]
plain = {int(n.replace(",", "")) for n in re.findall(r"(?<![\d.,])\d{1,3}(?:,\d{3})*(?![\d.,%])", section)}
negative = {int(n.replace(",", "")) for n in re.findall(r"\( ?(\d{1,3}(?:,\d{3})*) ?\)", section)}
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
rows = duckdb.connect().execute(f"""SELECT CAST(bdc_investment_identifier AS VARCHAR), TRY_CAST(fair_value AS DOUBLE), TRY_CAST(cost AS DOUBLE), TRY_CAST(principal_amount AS DOUBLE), src_context_id
    FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND CAST(report_date AS VARCHAR)[:10] = ?
      AND coalesce(accounting_record_class,'') <> 'underlying_schedule' AND coalesce(asset_category,'') <> 'CASH'""", [cik, quarter]).fetchall()
missing = []
for identifier, value, cost, par, ctx in rows:
    k = int(round(abs(value or 0) / 1000))
    if k and k not in (negative if (value or 0) < 0 else plain):
        missing.append((value, cost, par, ctx, identifier))
print("section chars: %d | published rows: %d | fair values not printed: %d, sum $K %d" % (len(section), len(rows), len(missing), sum(m[0] for m in missing) / 1000))
print("fv $K | cost $K | principal $K | context | id")
for value, cost, par, ctx, identifier in sorted(missing, key=lambda m: -abs(m[0]))[:25]:
    print("   %d | %s | %s | %s | %s" % (value / 1000, None if cost is None else round(cost / 1000), None if par is None else round(par / 1000), ctx, identifier[:80]))
