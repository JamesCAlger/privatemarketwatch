"""Read-only: every fair-value fact printed in a filing's page, summed per period, with repeats shown.

    python scripts/v05_evidence/page_fact_sum.py <cik> <accession no dashes> [concept, default InvestmentOwnedAtFairValue]

A context that is printed more than once with different values, or printed once but absent from the
flat file, explains a gap between the tagged rows and the printed total. Prints at most 40 repeats.
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, accession = sys.argv[1].lstrip("0"), sys.argv[2]
concept = sys.argv[3] if len(sys.argv) > 3 else "InvestmentOwnedAtFairValue"
raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
facts = defaultdict(list)
for match in re.finditer(r"<ix:nonFraction([^>]*)>([^<]*)<", raw):
    attrs, text = match.group(1), match.group(2)
    if ":" + concept + '"' not in attrs:
        continue
    ctx = re.search(r'contextRef="([^"]*)"', attrs).group(1)
    scale = re.search(r'scale="(-?\d+)"', attrs)
    sign = -1.0 if 'sign="-"' in attrs else 1.0
    digits = "0" if "&#8212" in text else re.sub(r"[^0-9.]", "", text)
    if not digits:
        continue
    facts[ctx].append(sign * float(digits) * 10 ** int(scale.group(1) if scale else 0))
contexts = {}
for match in re.finditer(r"<xbrli:context[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</xbrli:context>", raw, flags=re.S):
    body = match.group(2)
    instant = re.search(r"<xbrli:instant>([^<]*)<", body)
    axes = re.findall(r'dimension="([^"]*)"', body)
    contexts[match.group(1)] = (instant.group(1) if instant else "", tuple(sorted(a.split(":")[-1] for a in axes)))
groups = defaultdict(lambda: [0, 0.0])
for ctx, values in facts.items():
    key = contexts.get(ctx, ("?", ("?",)))
    groups[key][0] += 1
    groups[key][1] += values[0]
print("instant | axes | contexts | sum $M")
for key, (n, total) in sorted(groups.items(), key=lambda kv: (kv[0][0], -kv[1][1]))[-25:]:
    print("   %s | %s | %d | %.1f" % (key[0], ",".join(key[1]) or "(none)", n, total / 1e6))
print("contexts with a printed fact:", len(facts), "| printed facts:", sum(len(v) for v in facts.values()))
shown = 0
for ctx, values in facts.items():
    if len(values) > 1 and len(set(values)) > 1:
        shown += 1
        if shown <= 40:
            print("   repeated with different values:", ctx, [v / 1e3 for v in values])
print("contexts repeated with different values:", shown)
print("sum, first value per context ($M): %.1f | sum, every printed fact ($M): %.1f" % (
    sum(v[0] for v in facts.values()) / 1e6, sum(sum(v) for v in facts.values()) / 1e6))
