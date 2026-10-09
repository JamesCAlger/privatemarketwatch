"""Read-only: every row that fails the percent-of-net-assets identity, read on the filing page.

    python scripts/v05_evidence/pct_rows_on_page.py <sandbox label> <cik> [max rows listed, default 40]

For each published row whose percent disagrees with its fair value (the rule's own test), finds
the row's context in the cached page and prints the percent and the fair value as the filer
prints and tags them, next to the published figures and to the percent the fair value implies.
The question it answers: is the odd percent the filer's own number, or did the pipeline misread it?
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 40
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
rows = con.execute(f"""
WITH ff AS (SELECT CAST(report_date AS VARCHAR)[:10] AS d, max(TRY_CAST(net_assets AS DOUBLE)) AS nav
            FROM read_csv_auto('{S}/fund_financials.csv', sample_size=-1)
            WHERE source = 'companyfacts' AND lpad(CAST(cik AS VARCHAR),10,'0') = '{cik}' GROUP BY 1),
     h AS (SELECT CAST(report_date AS VARCHAR)[:10] AS d, TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(pct_of_net_assets AS DOUBLE) AS p,
                  CAST(bdc_investment_identifier AS VARCHAR) AS id, replace(CAST(accession_number AS VARCHAR), '-', '') AS acc,
                  CAST(src_context_id AS VARCHAR) AS ctx
           FROM read_parquet('{S}/private_markets_holdings.parquet')
           WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '{cik}' AND coalesce(accounting_record_class,'') <> 'underlying_schedule')
SELECT h.d, h.acc, h.ctx, h.fv, h.p, ff.nav, h.id FROM h JOIN ff USING (d)
WHERE h.p > 0 AND h.fv <> 0 AND ff.nav > 0
  AND NOT (abs(h.fv - h.p/100*ff.nav) <= 0.10*abs(h.fv) OR abs(h.p - 100*h.fv/ff.nav) <= 0.06)
ORDER BY 1, abs(h.fv) DESC""").fetchall()

by_filing = defaultdict(list)
for row in rows:
    by_filing[row[1]].append(row)
verdicts, printed_lines = Counter(), []
for accession, group in sorted(by_filing.items()):
    path = REPO / "data/raw/filings/bdc_html" / cik.lstrip("0") / (accession + ".html")
    if not path.exists():
        verdicts["page not cached"] += len(group)
        continue
    raw = path.read_text(encoding="utf-8", errors="replace")
    facts = defaultdict(dict)
    wanted = {r[2] for r in group}
    for match in re.finditer(r"<ix:nonFraction([^>]*)>([^<]*)<", raw):
        attrs = match.group(1)
        ref = re.search(r'contextRef="([^"]*)"', attrs)
        if not ref or ref.group(1) not in wanted:
            continue
        name = re.search(r'name="[^"]*:([^"]*)"', attrs).group(1)
        if name in ("InvestmentOwnedPercentOfNetAssets", "InvestmentOwnedAtFairValue"):
            scale = re.search(r'scale="(-?\d+)"', attrs)
            facts[ref.group(1)].setdefault(name, (match.group(2).strip(), int(scale.group(1)) if scale else 0))
    for d, _, ctx, fv, p, nav, ident in group:
        pct_text, pct_scale = facts[ctx].get("InvestmentOwnedPercentOfNetAssets", ("", 0))
        fv_text, fv_scale = facts[ctx].get("InvestmentOwnedAtFairValue", ("", 0))
        try:
            printed_pct = float(re.sub(r"[^0-9.]", "", pct_text)) * 10 ** (pct_scale + 2) if pct_text else None
            printed_fv = float(re.sub(r"[^0-9.]", "", fv_text)) * 10 ** fv_scale if fv_text else None
        except ValueError:
            printed_pct = printed_fv = None
        implied = 100 * fv / nav
        if printed_pct is None or printed_fv is None:
            verdict = "row not found on the page"
        elif abs(printed_pct - p) > 0.005 or abs(printed_fv - abs(fv)) > 0.5:
            verdict = "published differs from the page"
        else:
            verdict = "published as printed"
        verdicts[verdict] += 1
        printed_lines.append("   %s | %s | published pct %.2f fv %.0fK | page pct '%s' fv '%s' | fv implies %.2f pct | %s" % (
            d, verdict, p, fv / 1e3, pct_text, fv_text, implied, ident[:70]))
print("rows failing the identity: %d in %d filings" % (len(rows), len(by_filing)))
for verdict, n in verdicts.most_common():
    print("   %4d | %s" % (n, verdict))
shown = [line for line in printed_lines if "published as printed" not in line][:limit]
shown += [line for line in printed_lines if "published as printed" in line][:max(0, limit - len(shown))]
for line in shown:
    print(line.encode("ascii", "replace").decode())
