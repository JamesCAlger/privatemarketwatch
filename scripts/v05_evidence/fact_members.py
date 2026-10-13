"""Read-only: which contexts (and members) carry a given fact value in a cached XBRL instance.

    python scripts/v05_evidence/fact_members.py <cik> <accession no dashes> <value> [<value> ...]

Use it to check a claim of the form 'the filer tagged this subtotal on that member'.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, accession, values = sys.argv[1].lstrip("0"), sys.argv[2].replace("-", ""), sys.argv[3:]
text = (REPO / "data/raw/filings/bdc_xbrl" / cik / (accession + ".xml")).read_text(encoding="utf-8", errors="replace")
contexts = {}
for match in re.finditer(r"<(?:xbrli:)?context id=\"([^\"]+)\">(.*?)</(?:xbrli:)?context>", text, flags=re.S):
    body = match.group(2)
    members = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m)).strip() for m in re.findall(r"<xbrldi:(?:typed|explicit)Member.*?</xbrldi:(?:typed|explicit)Member>", body, flags=re.S)]
    instant = re.search(r"<(?:xbrli:)?instant>([^<]+)<", body)
    contexts[match.group(1)] = (instant.group(1) if instant else "", "; ".join(members))
for value in values:
    print("value", value)
    for fact in re.finditer(r"<([\w\-]+:[\w]+)[^>]*contextRef=\"([^\"]+)\"[^>]*>%s<" % re.escape(value), text):
        instant, members = contexts.get(fact.group(2), ("", ""))
        print("   %s | %s | %s | %s" % (fact.group(1), fact.group(2)[:14], instant, members[:200].encode("ascii", "replace").decode()))
