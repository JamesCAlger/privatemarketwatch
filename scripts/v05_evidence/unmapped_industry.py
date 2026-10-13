"""Read-only: filer industry labels in a sandbox that do not map to GICS without a model call."""
import sys
from pathlib import Path
import duckdb
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline.unified_holdings import printed_industry_gics  # noqa: E402
S = (REPO / "scratch/fund_sandbox" / sys.argv[1] / "output/private_markets_holdings.parquet").as_posix()
rows = duckdb.connect().execute(
    "SELECT extracted_industry, count(*) n, round(sum(fair_value)/1e6,1) fv, count(DISTINCT cik) funds FROM read_parquet('" + S + "') "
    "WHERE source='bdc' AND nullif(trim(extracted_industry),'') IS NOT NULL AND coalesce(index_classification,'')<>'CASH' GROUP BY 1 ORDER BY 2 DESC LIMIT 2000").fetchall()
mapping = printed_industry_gics([r[0] for r in rows])
how = {}
for label, n, fv, funds in rows:
    how[mapping.get(label, ("", "unmapped"))[1]] = how.get(mapping.get(label, ("", "unmapped"))[1], 0) + n
print("rows by mapping kind:", how)
for label, n, fv, funds in rows:
    if label not in mapping:
        print("  unmapped: %r rows %d fv %s" % (label, n, fv))
