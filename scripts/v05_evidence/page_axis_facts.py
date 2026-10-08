"""Read-only: the printed fair-value facts of a filing on one axis combination, with their members.

    python scripts/v05_evidence/page_axis_facts.py <cik> <accession no dashes> <quarter> <axis,axis> [max rows, default 80]

Axis names are local names, comma separated, e.g. InvestmentTypeAxis. Shows each context's members
and printed value, for comparing the filer's own subtotals with the sum of the tagged rows.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, accession, quarter = sys.argv[1].lstrip("0"), sys.argv[2], sys.argv[3]
wanted = tuple(sorted(sys.argv[4].split(",")))
limit = int(sys.argv[5]) if len(sys.argv) > 5 else 80
raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
contexts = {}
for match in re.finditer(r"<xbrli:context[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</xbrli:context>", raw, flags=re.S):
    body = match.group(2)
    instant = re.search(r"<xbrli:instant>([^<]*)<", body)
    members = re.findall(r'dimension="[^"]*:([^":]*)"[^>]*>(.*?)</xbrldi:', body, flags=re.S)
    if instant and instant.group(1) == quarter and tuple(sorted(m[0] for m in members)) == wanted:
        contexts[match.group(1)] = " / ".join(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m[1])).strip().split(":")[-1] for m in sorted(members))
seen, total, shown = set(), 0.0, 0
for match in re.finditer(r"<ix:nonFraction([^>]*)>([^<]*)<", raw):
    attrs, text = match.group(1), match.group(2)
    if ':InvestmentOwnedAtFairValue"' not in attrs:
        continue
    ctx = re.search(r'contextRef="([^"]*)"', attrs).group(1)
    if ctx not in contexts or ctx in seen:
        continue
    seen.add(ctx)
    scale = re.search(r'scale="(-?\d+)"', attrs)
    digits = "0" if "&#8212" in text else re.sub(r"[^0-9.]", "", text)
    value = (-1.0 if 'sign="-"' in attrs else 1.0) * float(digits or 0) * 10 ** int(scale.group(1) if scale else 0)
    total += value
    shown += 1
    if shown <= limit:
        print(("   %12.1f | %s" % (value / 1e3, contexts[ctx][:150])).encode("ascii", "replace").decode())
print("contexts: %d | sum $K: %.1f" % (len(seen), total / 1e3))
