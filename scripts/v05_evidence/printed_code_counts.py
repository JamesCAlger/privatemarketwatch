"""Read-only: count the codes a filer prints before ' + margin' or before a reset period, per cached filing.

    python scripts/v05_evidence/printed_code_counts.py <cik> [plus|reset]

plus   counts 'CODE + 5.25' (the default);
reset  counts 'CODE (Q)' style cells, e.g. 'SOFR (Q)', 'NIBOR (S)'.
Evidence for source_encodings.reference_rate_codes: which codes appear, in which filings.
"""
import html
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik = sys.argv[1].lstrip("0")
mode = sys.argv[2] if len(sys.argv) > 2 else "plus"
pattern = (re.compile(r"(?<![A-Za-z])([A-Z][A-Za-z]{0,7})\s*\+\s*\d") if mode == "plus"
           else re.compile(r"(?<![A-Za-z])([A-Z][A-Za-z ]{1,14}?)\s*\(([A-Z])\)\s+\d"))
total = Counter()
for path in sorted((REPO / "data/raw/filings/bdc_html" / cik).glob("*.html")):
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"<ix:header>.*?</ix:header>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))
    counts = Counter(m.group(1).strip() for m in pattern.finditer(text))
    total.update(counts)
    print(path.stem, " ".join("%s:%d" % kv for kv in counts.most_common(14)))
print("all filings:", " ".join("%s:%d" % kv for kv in total.most_common(30)))
