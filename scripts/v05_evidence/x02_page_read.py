"""Read-only: the printed schedule line of each X02 row the disposition's reason does not explain.

    python scripts/v05_evidence/x02_page_read.py <label> <cik> [max rows, default 60] [min fair value $M, default 0]

X02 flags a credit row with no rate and no spread. The standing reason is "no rate fact, and the
row is undrawn, on non-accrual or PIK only" (pipeline/disposition_validity.py). For each flagged
row outside that reason this prints the text before the row's fair value in the cached filing,
found by the issuer's name and then the value as the fund prints it. A printed rate on the line
means the page has what the tags lack.
"""
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 60
floor = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
rows = con.execute(f"""
WITH i AS (SELECT DISTINCT row_id FROM read_csv('{S}/row_validation_issues.csv', header=true, all_varchar=true, sample_size=-1)
           WHERE rule_id='X02' AND lpad(cik,10,'0')='{cik}'),
h AS (SELECT CAST(row_id AS VARCHAR) AS row_id, CAST(report_date AS VARCHAR)[:10] AS q, CAST(accession_number AS VARCHAR) AS acc,
        TRY_CAST(fair_value AS DOUBLE) AS fv, TRY_CAST(cost AS DOUBLE) AS cost, TRY_CAST(principal_amount AS DOUBLE) AS pa,
        coalesce(TRY_CAST(pik_rate AS DOUBLE),0)>0 AS pik, coalesce(CAST(nonaccrual_status AS VARCHAR),'')='nonaccrual' AS na,
        coalesce(CAST(src_facts AS VARCHAR),'') AS sf, CAST(bdc_investment_identifier AS VARCHAR) AS id, CAST(issuer_name AS VARCHAR) AS issuer
      FROM read_parquet('{S}/private_markets_holdings.parquet'))
SELECT q, acc, fv, cost, pa, id, issuer FROM i JOIN h USING (row_id)
WHERE NOT (NOT (sf LIKE '%"interest_rate"%' OR sf LIKE '%"basis_spread"%') AND (coalesce(fv,0)<=0 OR na OR pik))
  AND coalesce(fv,0) >= {floor * 1e6}
ORDER BY fv DESC LIMIT {limit}""").fetchall()

texts = {}


def filing_text(accession):
    if accession not in texts:
        path = REPO / "data/raw/filings/bdc_html" / cik.lstrip("0") / (accession.replace("-", "") + ".html")
        if not path.exists():
            texts[accession] = ""
        else:
            raw = path.read_text(encoding="utf-8", errors="replace")
            body = re.sub(r"<[^>]+>", " ", raw).replace("&#160;", " ").replace("&nbsp;", " ").replace("&amp;", "&")
            body = body.replace("&#8212;", "-").replace("&#8217;", "'")
            texts[accession] = re.sub(r"\s+", " ", body)
    return texts[accession]


def printed_forms(value):
    """The value as a schedule may print it: millions to one decimal, or thousands with commas."""
    if value is None:
        return []
    return ["%.1f" % (value / 1e6), "{:,.0f}".format(value / 1e3)]


print("%d rows outside the reason (largest first)" % len(rows))
for q, acc, fv, cost, pa, ident, issuer in rows:
    text = filing_text(acc)
    name = (issuer or ident or "")[:28]
    found = ""
    for start in [m.start() for m in re.finditer(re.escape(name), text)][:40]:
        window = text[start:start + 2500]
        for form in printed_forms(fv):
            hit = re.search(r"(?<![\d,.])" + re.escape(form) + r"(?![\d,.])", window)
            if hit and all(f is None or any(re.search(r"(?<![\d,.])" + re.escape(x) + r"(?![\d,.])", window[max(0, hit.start() - 60):hit.end()])
                                             for x in printed_forms(f)) for f in (cost,)):
                found = window[max(0, hit.start() - 230):hit.end() + 25]
                break
        if found:
            break
    line = (found or "(printed line not found by name and value)").encode("ascii", "replace").decode()
    print("%s | fv %.1fM cost %s par %s | %s" % (q, (fv or 0) / 1e6, "%.1fM" % (cost / 1e6) if cost is not None else "-",
                                               "%.1fM" % (pa / 1e6) if pa is not None else "-", (ident or "")[:90].encode("ascii", "replace").decode()))
    print("      page: ..." + line)
