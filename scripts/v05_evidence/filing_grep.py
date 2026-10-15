"""Read-only: show the text around a phrase in a cached filing (HTML tags stripped), or raw XBRL facts for a context.

    python scripts/v05_evidence/filing_grep.py <cik> <accession no dashes> html "<phrase>" [max hits] [chars after]
    python scripts/v05_evidence/filing_grep.py <cik> <accession no dashes> xml "<context id>"

With ``xml``, the facts on the context are listed, then the facts on every other context of the
same investment (the same dimension members, another period). Many filers tag a rate or a date on
the investment's year-to-date (duration) context beside the instant one that holds the values
(Stone Point, 10-K 2024-12-31: PreferredStockDividendRatePercentage on 'Duration_1_1_2024_To_12_31_2024_...');
reading the instant context alone shows them as untagged.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, accession, kind, phrase = sys.argv[1].lstrip("0"), sys.argv[2], sys.argv[3], sys.argv[4]
limit = int(sys.argv[5]) if len(sys.argv) > 5 else 4
after = int(sys.argv[6]) if len(sys.argv) > 6 else 500


def _facts(text, context):
    for match in re.finditer(r"<([\w\-:]+)[^>]*contextRef=\"%s\"[^>]*>([^<]*)<" % re.escape(context), text):
        tag = match.group(0)
        unit = re.search(r"unitRef=\"([^\"]*)\"", tag)
        scale = re.search(r"decimals=\"([^\"]*)\"", tag)
        yield "%s = %s | unit %s | decimals %s" % (match.group(1), " ".join(match.group(2).split())[:80],
                                                   unit.group(1) if unit else "", scale.group(1) if scale else "")


if kind == "xml":
    text = (REPO / "data/raw/filings/bdc_xbrl" / cik / (accession + ".xml")).read_text(encoding="utf-8", errors="replace")
    for line in _facts(text, phrase):
        print("   " + line)
    contexts = {}
    # with or without the xbrli: prefix (Stone Point writes plain <context>, <segment>, <instant>)
    for m in re.finditer(r"<(?:xbrli:)?context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</(?:xbrli:)?context>", text, flags=re.S):
        segment = re.search(r"<(?:xbrli:)?segment>(.*?)</(?:xbrli:)?segment>", m.group(2), flags=re.S)
        period = re.findall(r"<(?:xbrli:)?(?:instant|startDate|endDate)>([^<]+)<", m.group(2))
        contexts[m.group(1)] = (" ".join(re.sub(r"<[^>]+>", " ", segment.group(1)).split()) if segment else "", " to ".join(period))
    member = contexts.get(phrase, ("", ""))[0]
    if member:
        siblings = [c for c, (seg, _p) in contexts.items() if seg == member and c != phrase]
        for sibling in siblings:
            lines = list(_facts(text, sibling))
            if lines:
                print("   same investment, context %s (%s):" % (sibling[-60:], contexts[sibling][1]))
                for line in lines:
                    print("      " + line)
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
