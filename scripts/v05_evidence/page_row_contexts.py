"""Read-only: schedule rows whose fair-value tag does not sit on an identifier context of the quarter.

    python scripts/v05_evidence/page_row_contexts.py <cik> <accession no dashes> <quarter> [max rows, default 60]

Counts the fair-value-tagged rows of the page by the kind of context their tag uses, then lists
the rows that do not start with "Total" and whose tag uses a context with no InvestmentIdentifierAxis
member, or an identifier context that another row has already used.
"""
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import bdc_xbrl_html_bridge as b  # noqa: E402

cik, accession, quarter = sys.argv[1].lstrip("0"), sys.argv[2], sys.argv[3]
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 60
path = REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")
raw = path.read_text(encoding="utf-8", errors="replace")
contexts = {}
for match in re.finditer(r"<xbrli:context[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</xbrli:context>", raw, flags=re.S):
    body = match.group(2)
    instant = re.search(r"<xbrli:instant>([^<]*)<", body)
    axes = tuple(sorted(a.split(":")[-1] for a in re.findall(r'dimension="([^"]*)"', body)))
    contexts[match.group(1)] = (instant.group(1) if instant else "", axes)
root = etree.parse(str(path), etree.XMLParser(huge_tree=True, recover=True)).getroot()
kinds, used, shown = Counter(), set(), 0
for tr in root.iter():
    if b._ixbrl_local(tr.tag) != "tr":
        continue
    refs = [el.get("contextRef") for el in tr.iter()
            if b._ixbrl_local(el.tag).lower() == "nonfraction" and (el.get("name") or "").endswith(":InvestmentOwnedAtFairValue")]
    if not refs:
        continue
    instant, axes = contexts.get(refs[0], ("?", ("?",)))
    if instant != quarter:
        continue
    identifier = "InvestmentIdentifierAxis" in axes
    repeat = identifier and refs[0] in used
    used.add(refs[0])
    kinds[("identifier, repeated" if repeat else "identifier") if identifier else ",".join(axes) or "(no axis)"] += 1
    cells = [c for c in (b._norm_text(c) for c in b._row_grid(tr)) if c]
    if (identifier and not repeat) or (cells and cells[0].lower().startswith("total")):
        continue
    shown += 1
    if shown <= limit:
        print(("   %s | %s | %s" % (refs[0], ",".join(axes) or "(no axis)", " | ".join(cells)[:170])).encode("ascii", "replace").decode())
print("rows listed:", min(shown, limit), "of", shown)
for kind, n in kinds.most_common():
    print("   %5d rows | %s" % (n, kind))
