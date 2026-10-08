"""Read-only: what a fund's printed schedule holds for the reference rate and the margin.

    python scripts/v05_evidence/printed_rate_columns.py <label> <cik> [sample rows per filing]

1. the sandbox field-status artifact, current-period rows: status of the printed reference rate by quarter;
2. for the fund's first and last filing in the sandbox: each distinct header row the page reader
   detects, and for sample position rows the cells under the columns the shared rule would read.
"""
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

label, cik = sys.argv[1], sys.argv[2].zfill(10)
samples = int(sys.argv[3]) if len(sys.argv) > 3 else 8
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
F = f"""(SELECT * FROM read_csv('{S}/bdc_ixbrl_field_status.csv', header=true, all_varchar=true, sample_size=-1)
    WHERE cik='{cik}' AND period_role='current')"""

print("1. quarter | accession | value | blank | validation_needed | not_applicable | not_found/other | printed margin read")
filings = con.execute(f"""SELECT report_date, accession_number, count(*) FILTER (WHERE reference_rate_status='value'),
        count(*) FILTER (WHERE reference_rate_status='blank'), count(*) FILTER (WHERE reference_rate_status='validation_needed'),
        count(*) FILTER (WHERE reference_rate_status='not_applicable'),
        count(*) FILTER (WHERE reference_rate_status NOT IN ('value','blank','validation_needed','not_applicable')),
        count(*) FILTER (WHERE nullif(trim(printed_margin),'') IS NOT NULL)
    FROM {F} GROUP BY 1,2 ORDER BY 1""").fetchall()
for r in filings:
    print("   " + " | ".join(str(v) for v in r))
if not filings:
    raise SystemExit("no rows for this fund")

from lxml import etree
from pipeline.bdc_xbrl_html_bridge import _detect_header_map, _row_grid, _ixbrl_local, _FIELD_COLUMN_RULES

RULE = re.compile(_FIELD_COLUMN_RULES["reference_rate_type"]["header"])
for quarter, accession in sorted({(filings[0][0], filings[0][1]), (filings[len(filings) // 2][0], filings[len(filings) // 2][1]),
                                  (filings[-1][0], filings[-1][1])}):
    path = REPO / "data/raw/filings/bdc_html" / cik.lstrip("0") / (accession.replace("-", "") + ".html")
    print("\n2. %s %s" % (quarter, accession))
    if not path.exists():
        print("   no cached page")
        continue
    root = etree.parse(str(path)).getroot()
    headers, header, shown = {}, None, 0
    for tr in root.iter():
        if _ixbrl_local(tr.tag) != "tr":
            continue
        grid = _row_grid(tr)
        found = _detect_header_map(grid)
        if found is not None:
            header = found
            key = " | ".join(found[i] for i in sorted(found))
            headers[key] = headers.get(key, 0) + 1
            continue
        if header is None or shown >= samples:
            continue
        has_value = any(_ixbrl_local(el.tag) == "nonFraction" and (el.get("name") or "").endswith("InvestmentOwnedAtFairValue")
                        for el in tr.iter())
        if not has_value or not any(RULE.search(v) for v in header.values()):
            continue
        # every 40th value row, so the sample spans the schedule
        headers["_rows"] = headers.get("_rows", 0) + 1
        if headers["_rows"] % 40 != 1:
            continue
        shown += 1
        print("   row: " + " | ".join(c for c in grid if c)[:230])
        print("        read columns: " + "; ".join("%s=[%s]" % (header[i], grid[i] if i < len(grid) else "")
                                                   for i in sorted(header) if RULE.search(header[i])))
    headers.pop("_rows", None)
    print("   header rows detected (count):")
    for key, n in sorted(headers.items(), key=lambda kv: -kv[1])[:8]:
        print("     %4d  %s" % (n, key[:230]))
