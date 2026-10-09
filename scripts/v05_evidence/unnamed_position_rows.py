"""Read-only: draft 'context_identifiers' entries for schedule rows a filer tagged with no identifier member.

    python scripts/v05_evidence/unnamed_position_rows.py <cik> <accession with dashes> <quarter> <axis+axis+...>

For each printed row whose fair-value tag sits on a context of the quarter with exactly the named
axes (lower-case local names) and that starts with a label, prints

    ACCESSION CONTEXT => <type heading> | <industry heading> | <label>      printed fair value

The headings are the last two heading rows above the row (a heading reads 'Name - 12.3%'); the first
heading after a 'Total ...' row is taken as the type. Rows with amounts only (subtotals) are not
listed. Read every line against the page before putting it in a wrapper.
"""
import html
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
cik, accession, quarter, axes = sys.argv[1].lstrip("0"), sys.argv[2], sys.argv[3], frozenset(sys.argv[4].lower().split("+"))
raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession.replace("-", "") + ".html")).read_text(encoding="utf-8", errors="replace")
candidates = set()
for match in re.finditer(r"<xbrli:context[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</xbrli:context>", raw, flags=re.S):
    body = match.group(2)
    instant = re.search(r"<xbrli:instant>([^<]*)<", body)
    dims = frozenset(d.split(":")[-1].lower() for d in re.findall(r"dimension=\"([^\"]*)\"", body))
    if instant and instant.group(1) == quarter and dims == axes:
        candidates.add(match.group(1))
print("candidate contexts:", len(candidates))
HEADING = re.compile(r"^(.*?)\s*[–—-]\s*[\d.]+\s*%")
FOOTNOTES = re.compile(r"(?:\s*\(\d{1,2}\))+\s*$")
kind, industry, expect_kind, seen = "", "", True, set()
for chunk in re.split(r"<tr\b", raw, flags=re.I)[1:]:
    row = re.split(r"</tr>", chunk, maxsplit=1, flags=re.I)[0]
    cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c.split(">", 1)[-1])).replace("\xa0", " ").split())
             for c in re.split(r"<t[dh]\b", row, flags=re.I)[1:]]
    cells = [c for c in cells if c]
    if not cells:
        continue
    first = cells[0]
    if first.lower().startswith("total"):
        expect_kind = True
        continue
    heading = HEADING.match(first)
    if heading and "InvestmentOwnedAtFairValue" not in row:
        if expect_kind:
            kind, industry, expect_kind = FOOTNOTES.sub("", heading.group(1)).strip(), "", False
        else:
            industry = FOOTNOTES.sub("", heading.group(1)).strip()
        continue
    refs = [m.group(1) for m in re.finditer(r"<ix:nonFraction[^>]*name=\"[^\"]*InvestmentOwnedAtFairValue\"[^>]*contextRef=\"([^\"]*)\"", row)]
    refs += [m.group(1) for m in re.finditer(r"<ix:nonFraction[^>]*contextRef=\"([^\"]*)\"[^>]*name=\"[^\"]*InvestmentOwnedAtFairValue\"", row)]
    refs = [r for r in refs if r in candidates]
    if not refs or not re.search(r"[A-Za-z]{2}", first) or re.match(r"^[\$\(\d]", first):
        continue
    label = FOOTNOTES.sub("", first).strip()
    for ref in refs:
        if ref in seen:
            print("   (context used by a second row, check by hand)", ref[:60], label)
            continue
        seen.add(ref)
        line = "%s %s => %s | %s | %s" % (accession, ref, kind, industry, label)
        print(line.encode("ascii", "replace").decode("ascii"), "     fair value cell:", cells[-1])
print("rows drafted:", len(seen))
