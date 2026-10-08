"""Read-only: the heading and total rows of a filing's schedule, as the page reader sees them.

    python scripts/v05_evidence/page_sections.py <cik> <accession no dashes> [max rows, default 80]

Prints each row that is a lone label (a heading) or begins with "Total", with whether the reader
recognises it as a section. A heading the reader does not recognise leaves the previous lien
section open for the rows that follow.
"""
import sys
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import bdc_xbrl_html_bridge as b  # noqa: E402

cik, accession = sys.argv[1].lstrip("0"), sys.argv[2]
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 80
root = etree.parse(str(REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html"))).getroot()
shown, last = 0, None
for tr in root.iter():
    if b._ixbrl_local(tr.tag) != "tr":
        continue
    cells = [b._norm_text(c) for c in b._row_grid(tr)]
    nonempty = [c for c in cells if c]
    if not nonempty:
        continue
    first = nonempty[0]
    section = b._section_for_row(cells)
    heading = len(nonempty) == 1 and not b._VALUE_RE.search(first)
    total = first.lower().startswith("total")
    if not (section or total or (heading and ("debt" in first.lower() or "equity" in first.lower() or "finance" in first.lower()
                                              or "venture" in first.lower() or "lien" in first.lower()))):
        continue
    line = "%-9s %s" % ("SECTION" if section else "total" if total else "heading", " | ".join(nonempty)[:150])
    if line == last:
        continue
    last = line
    print(line.encode("ascii", "replace").decode())
    shown += 1
    if shown >= limit:
        break
