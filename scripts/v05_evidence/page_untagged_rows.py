"""Read-only: schedule rows of a filing's page that print amounts but carry no fair-value tag.

    python scripts/v05_evidence/page_untagged_rows.py <cik> <accession no dashes> [max rows, default 60] [first] [last]

Rows with no tag at all are listed only between the first-th and last-th fair-value-tagged row (the schedule).

A row counts when it has at least three cells that are plain amounts, some investment tag (cost,
principal, rate) but no ix:nonFraction for InvestmentOwnedAtFairValue, and does not begin with "Total". Rows are shown in page order.
"""
import re
import sys
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import bdc_xbrl_html_bridge as b  # noqa: E402

cik, accession = sys.argv[1].lstrip("0"), sys.argv[2]
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 60
first = int(sys.argv[4]) if len(sys.argv) > 4 else 10
last = int(sys.argv[5]) if len(sys.argv) > 5 else 10 ** 9
root = etree.parse(str(REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")), etree.XMLParser(huge_tree=True, recover=True)).getroot()
amount = re.compile(r"^\(?\s*\$?\s*[\d,]+(?:\.\d+)?\s*\)?%?$")
shown = tagged_rows = 0
for tr in root.iter():
    if b._ixbrl_local(tr.tag) != "tr":
        continue
    names = [el.get("name") or "" for el in tr.iter() if b._ixbrl_local(el.tag) .lower() == "nonfraction"]
    if any(n.endswith(":InvestmentOwnedAtFairValue") for n in names):
        tagged_rows += 1
        continue
    if not tagged_rows:
        continue
    cells = [c for c in (b._norm_text(c) for c in b._row_grid(tr)) if c]
    if not cells or cells[0].lower().startswith("total") or sum(1 for c in cells if amount.match(c)) < 3:
        continue
    if names and (any("ConcentrationRisk" in n for n in names) or not any("Investment" in n for n in names)):
        continue
    if not names and (tagged_rows < first or tagged_rows > last):
        continue
    shown += 1
    if shown <= limit:
        print(("   after %d tagged rows | tags %s | %s" % (tagged_rows, sorted({n.split(":")[-1] for n in names}) or "none", " | ".join(cells)[:170])).encode("ascii", "replace").decode())
print("tagged rows:", tagged_rows)
print("rows shown:", min(shown, limit), "of", shown)
