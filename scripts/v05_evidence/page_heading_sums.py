"""Read-only: tagged position rows of a page summed under each heading row, in page order.

    python scripts/v05_evidence/page_heading_sums.py <cik> <accession no dashes> <quarter>

A heading is a table row with one text cell and no tag. Rows whose fair-value tag sits on an
identifier context of the quarter are summed under the last heading. Compare the sums with the
filer's own subtotals (page_axis_facts.py) to find the section where tagged rows fall short.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import page_labelled_contexts as plc  # noqa: E402

cik, accession, quarter = sys.argv[1].lstrip("0"), sys.argv[2], sys.argv[3]
raw = (REPO / "data/raw/filings/bdc_html" / cik / (accession + ".html")).read_text(encoding="utf-8", errors="replace")
identifier = set()
for match in re.finditer(r"<xbrli:context[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</xbrli:context>", raw, flags=re.S):
    body = match.group(2)
    instant = re.search(r"<xbrli:instant>([^<]*)<", body)
    if instant and instant.group(1) == quarter and "InvestmentIdentifierAxis" in body:
        identifier.add(match.group(1))
heading, sums, order, seen = "(before any heading)", {}, [], set()
listed = sys.argv[4].lower() if len(sys.argv) > 4 else None
offset = 0
for chunk in re.split(r"<tr\b", raw, flags=re.I)[1:]:
    offset += len(chunk) + 3
    row = re.split(r"</tr>", chunk, maxsplit=1, flags=re.I)[0]
    if "<ix:nonFraction" not in row:
        cells = plc._cell_texts(row)
        if len(cells) == 1 and re.search(r"[A-Za-z]{3}", cells[0]) and len(cells[0]) < 90 and not cells[0].lower().startswith("total"):
            heading = cells[0]
        continue
    for tag in re.finditer(r'<ix:nonFraction\b([^>]*name="[^"]*:InvestmentOwnedAtFairValue"[^>]*)>([^<]*)<', row):
        ctx = re.search(r'contextRef="([^"]*)"', tag.group(1)).group(1)
        if ctx not in identifier or ctx in seen:
            continue
        seen.add(ctx)
        scale = re.search(r'scale="(-?\d+)"', tag.group(1))
        digits = "0" if "&#8212" in tag.group(2) else re.sub(r"[^0-9.]", "", tag.group(2))
        value = (-1.0 if 'sign="-"' in tag.group(1) else 1.0) * float(digits or 0) * 10 ** int(scale.group(1) if scale else 0)
        if heading not in sums:
            sums[heading] = [0, 0.0]
            order.append(heading)
        sums[heading][0] += 1
        if listed and heading.lower() == listed:
            print(("      at %9d | %12.1f | %s" % (offset, value / 1e3, " | ".join(plc._cell_texts(row))[:110])).encode("ascii", "replace").decode())
        sums[heading][1] += value
for name in order:
    print(("   %14.1f | %4d rows | %s" % (sums[name][1] / 1e3, sums[name][0], name)).encode("ascii", "replace").decode())
print("rows: %d | sum $K: %.1f" % (sum(v[0] for v in sums.values()), sum(v[1] for v in sums.values()) / 1e3))
