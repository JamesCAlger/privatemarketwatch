"""Read-only: show the page text before (and a little after) a phrase in a cached filing, tags stripped.

    python scripts/v05_evidence/filing_before.py <cik> <accession no dashes> "<phrase>" [chars before] [hit number] [chars after]

Use it to read the rows above a printed subtotal. Text inside the hidden iXBRL header is skipped.
"""
import html
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, accession, phrase = sys.argv[1].lstrip("0"), sys.argv[2], sys.argv[3]
before = int(sys.argv[4]) if len(sys.argv) > 4 else 3000
which = int(sys.argv[5]) if len(sys.argv) > 5 else 1
after = int(sys.argv[6]) if len(sys.argv) > 6 else 200
raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
raw = re.sub(r"<ix:header>.*?</ix:header>", " ", raw, flags=re.S | re.I)
text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))
hits = [m.start() for m in re.finditer(re.escape(phrase), text)]
print("hits:", len(hits))
if len(hits) >= which:
    at = hits[which - 1]
    out = text[max(0, at - before): at + len(phrase) + after]
    print(out.encode("ascii", "replace").decode("ascii"))
