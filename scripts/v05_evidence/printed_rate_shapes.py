"""Read-only: the forms a fund prints in its reference-rate column and the cells after it.

    python scripts/v05_evidence/printed_rate_shapes.py <label> <cik> "<header label>" [filings] [top]

For value rows of up to [filings] of the fund's filings in the sandbox (spread over the sample),
under a header that carries the label: the named cell and the cells up to the next header column,
digits replaced by 9, tallied. One example row is shown per form.
"""
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

label, cik, column = sys.argv[1], sys.argv[2].zfill(10), " ".join(sys.argv[3].lower().split())
count = int(sys.argv[4]) if len(sys.argv) > 4 else 5
top = int(sys.argv[5]) if len(sys.argv) > 5 else 40
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
filings = duckdb.connect().execute(f"""SELECT DISTINCT report_date, accession_number
    FROM read_csv('{S}/bdc_ixbrl_field_status.csv', header=true, all_varchar=true, sample_size=-1)
    WHERE cik='{cik}' AND period_role='current' ORDER BY 1""").fetchall()
step = max(1, (len(filings) - 1) // max(1, count - 1))
chosen = sorted(set(filings[::step][:count] + [filings[-1]]))

from lxml import etree
from pipeline.bdc_xbrl_html_bridge import _detect_header_map, _row_grid, _ixbrl_local

shapes, example = {}, {}
for quarter, accession in chosen:
    path = REPO / "data/raw/filings/bdc_html" / cik.lstrip("0") / (accession.replace("-", "") + ".html")
    if not path.exists():
        print("no cached page:", quarter, accession)
        continue
    header, rows = None, 0
    for tr in etree.parse(str(path)).getroot().iter():
        if _ixbrl_local(tr.tag) != "tr":
            continue
        grid = _row_grid(tr)
        found = _detect_header_map(grid)
        if found is not None:
            header = found
            continue
        if not header:
            continue
        named = [i for i in sorted(header) if " ".join(header[i].lower().split()) == column and i < len(grid)]
        if not named:
            continue
        if not any(_ixbrl_local(el.tag) == "nonFraction" and (el.get("name") or "").endswith("InvestmentOwnedAtFairValue")
                   for el in tr.iter()):
            continue
        later = [i for i in sorted(header) if i > named[0]]
        cells = grid[named[0]:min(later[0] if later else len(grid), len(grid))]
        nxt = (header[later[0]] + "=[" + (grid[later[0]] if later[0] < len(grid) else "") + "]") if later else ""
        shape = re.sub(r"\d", "9", " | ".join(c if c else "-" for c in cells)) + "   -> next " + re.sub(r"\d", "9", nxt)
        shapes[shape] = shapes.get(shape, 0) + 1
        example.setdefault(shape, "%s: %s" % (quarter, " | ".join(c for c in grid if c)[:150]))
        rows += 1
    print("read %s %s: %d value rows under the column" % (quarter, accession, rows))

print("\nforms (rows): cells from the named column to the next header -> next header cell")
for shape, n in sorted(shapes.items(), key=lambda kv: -kv[1])[:top]:
    print("%6d  %s" % (n, shape[:170]))
    print("        e.g. %s" % example[shape])
print("distinct forms:", len(shapes))
