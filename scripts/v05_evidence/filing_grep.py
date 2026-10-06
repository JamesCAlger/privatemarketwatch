"""Read-only: show the text around a phrase in a cached filing (HTML tags stripped), or raw XBRL facts for a context.

    python scripts/v05_evidence/filing_grep.py <cik> <accession no dashes> html "<phrase>" [max hits] [chars after]
    python scripts/v05_evidence/filing_grep.py <cik> <accession no dashes> xml "<context id>"
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, accession, kind, phrase = sys.argv[1].lstrip("0"), sys.argv[2], sys.argv[3], sys.argv[4]
limit = int(sys.argv[5]) if len(sys.argv) > 5 else 4
after = int(sys.argv[6]) if len(sys.argv) > 6 else 500
if kind == "xml":
    text = (REPO / "data/raw/filings/bdc_xbrl" / cik / (accession + ".xml")).read_text(encoding="utf-8", errors="replace")
    for match in re.finditer(r"<([\w\-:]+)[^>]*contextRef=\"%s\"[^>]*>([^<]*)<" % re.escape(phrase), text):
        tag = match.group(0)
        unit = re.search(r"unitRef=\"([^\"]*)\"", tag)
        scale = re.search(r"decimals=\"([^\"]*)\"", tag)
        print("   %s = %s | unit %s | decimals %s" % (match.group(1), match.group(2)[:80], unit.group(1) if unit else "", scale.group(1) if scale else ""))
else:
    raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw).replace("&#160;", " ").replace("&nbsp;", " ").replace("&amp;", "&"))
    hits = 0
    for match in re.finditer(re.escape(phrase), text, flags=re.I):
        hits += 1
        if hits > limit:
            break
        print("   [%d] ...%s" % (match.start(), text[max(0, match.start() - 80): match.start() + after]))
    print("hits shown:", min(hits, limit))
