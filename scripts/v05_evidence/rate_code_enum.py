"""Read-only: a filer's printed reference-rate codes against the benchmark it tags on the same row.

    python scripts/v05_evidence/rate_code_enum.py <cik> <accession no dashes> [regex with one group for the code]

Reads each fact whose concept name ends in 'InterestRateTypeExtensibleEnumeration', takes the code
from the context's identifier member with the regex (default: the text before ' +' after
'Reference Rate and Spread'), and counts code against tagged member. Evidence for
source_encodings.reference_rate_codes.
"""
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, accession = sys.argv[1].lstrip("0"), sys.argv[2]
code_re = re.compile(sys.argv[3] if len(sys.argv) > 3 else r"Reference Rate and ?Spread ([A-Za-z]+) ?\+")
raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
members = {}
for match in re.finditer(r"<xbrli:context[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</xbrli:context>", raw, flags=re.S):
    member = re.search(r'dimension="[^"]*InvestmentIdentifierAxis"[^>]*>(.*?)</xbrldi:', match.group(2), flags=re.S)
    if member:
        members[match.group(1)] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", member.group(1))).strip()
counts = Counter()
for match in re.finditer(r"<ix:nonNumeric\b([^>]*)>([^<]*)<", raw):
    attrs = match.group(1)
    if "InterestRateTypeExtensibleEnumeration" not in attrs:
        continue
    ctx = re.search(r'contextRef="([^"]*)"', attrs).group(1)
    code = code_re.search(members.get(ctx, ""))
    for uri in match.group(2).split():
        counts[(code.group(1) if code else "(no code)", uri.split("#")[-1])] += 1
for (code, member), n in sorted(counts.items()):
    print("   %-8s | %-55s | %d" % (code, member, n))
