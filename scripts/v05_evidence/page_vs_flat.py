"""Read-only: per identifier context, the fair value printed on the page against the flat file.

    python scripts/v05_evidence/page_vs_flat.py <label> <cik> <accession no dashes> <quarter>

Lists identifier-axis contexts at the quarter whose printed fair value differs from, or is missing in,
the sandbox's bdc_holdings.csv. Prints at most 40 rows, largest difference first.
"""
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik, accession, quarter = sys.argv[1], sys.argv[2].lstrip("0"), sys.argv[3], sys.argv[4]
raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
contexts = {}
for match in re.finditer(r"<xbrli:context[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</xbrli:context>", raw, flags=re.S):
    body = match.group(2)
    instant = re.search(r"<xbrli:instant>([^<]*)<", body)
    member = re.search(r'dimension="[^"]*InvestmentIdentifierAxis"[^>]*>(.*?)</xbrldi:', body, flags=re.S)
    if instant and member and instant.group(1) == quarter:
        contexts[match.group(1)] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", member.group(1))).strip()
page = {}
for match in re.finditer(r"<ix:nonFraction([^>]*)>([^<]*)<", raw):
    attrs, text = match.group(1), match.group(2)
    if ':InvestmentOwnedAtFairValue"' not in attrs:
        continue
    ctx = re.search(r'contextRef="([^"]*)"', attrs).group(1)
    digits = "0" if "&#8212" in text else re.sub(r"[^0-9.]", "", text)
    if ctx not in contexts or not digits:
        continue
    scale = re.search(r'scale="(-?\d+)"', attrs)
    page.setdefault(ctx, []).append((-1.0 if 'sign="-"' in attrs else 1.0) * float(digits) * 10 ** int(scale.group(1) if scale else 0))
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
flat = dict(duckdb.connect().execute(f"""SELECT src_context_id, TRY_CAST(fair_value AS DOUBLE) FROM read_csv('{S}/bdc_holdings.csv', header=true, all_varchar=true, sample_size=-1)
    WHERE lpad(cik,10,'0')='{cik.zfill(10)}' AND replace(accession_number,'-','')='{accession}' AND CAST(period AS VARCHAR)[:10]='{quarter}'""").fetchall())
print("identifier contexts at %s: %d | with a printed fair value: %d | flat rows: %d" % (quarter, len(contexts), len(page), len(flat)))
print("page sum $M: %.1f | flat sum $M: %.1f" % (sum(v[0] for v in page.values()) / 1e6, sum(v or 0 for v in flat.values()) / 1e6))
rows = []
for ctx, values in page.items():
    got = flat.get(ctx)
    if got is None or abs(got - values[0]) > 500:
        rows.append((abs(values[0] - (got or 0)), ctx, values, got))
rows.sort(reverse=True)
print("contexts that differ:", len(rows), "| in flat but not printed:", len([c for c in flat if c not in page]))
for diff, ctx, values, got in rows[:40]:
    print(("   %s | page %s | flat %s | %s" % (ctx, [v / 1e3 for v in values], "absent" if got is None else got / 1e3, contexts[ctx][:110])).encode("ascii", "replace").decode())
repeats = [(ctx, values) for ctx, values in page.items() if len(values) > 1]
print("contexts printed more than once: %d | extra value beyond the first $M: %.1f" % (len(repeats), sum(sum(v[1:]) for _, v in repeats) / 1e6))
for ctx, values in repeats[:40]:
    print(("   %s | %s | %s" % (ctx, [v / 1e3 for v in values], contexts[ctx][:110])).encode("ascii", "replace").decode())
