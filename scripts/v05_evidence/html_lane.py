"""Read-only: how HTML-extracted rows are marked in the published file, and overlap with the HTML validation table."""
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
con = duckdb.connect()
pq = f"read_parquet('{(REPO / 'data/output/private_markets_holdings.parquet').as_posix()}')"
print("source | fair_value_source | bdc_form_type sample | rows | funds | first..last")
for r in con.execute(f"""SELECT source, fair_value_source, any_value(bdc_form_type), count(*), count(DISTINCT cik), min(CAST(report_date AS VARCHAR)[:10]), max(CAST(report_date AS VARCHAR)[:10])
    FROM {pq} GROUP BY 1,2 ORDER BY 4 DESC""").fetchall():
    print("   ", r)
v = f"read_csv_auto('{(REPO / 'data/output/html_template_validation.csv').as_posix()}', sample_size=-1)"
print("html validation fund-quarters:", con.execute(f"SELECT count(*), count(DISTINCT cik), min(CAST(report_date AS VARCHAR)), max(CAST(report_date AS VARCHAR)) FROM {v}").fetchone())
print("of which the published rows for that fund-quarter are all XBRL-tagged / some not / no published rows:")
print("   ", con.execute(f"""WITH p AS (SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d,
            count(*) AS n, count(*) FILTER (WHERE coalesce(fair_value_source,'') = 'xbrl_field') AS x FROM {pq} WHERE source = 'bdc' GROUP BY 1,2),
        h AS (SELECT DISTINCT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS d FROM {v})
    SELECT count(*) FILTER (WHERE p.n = p.x), count(*) FILTER (WHERE p.n > p.x), count(*) FILTER (WHERE p.n IS NULL) FROM h LEFT JOIN p USING (cik, d)""").fetchone())
print("published rows that are not xbrl_field, by source value:", con.execute(f"SELECT fair_value_source, count(*) FROM {pq} WHERE source='bdc' AND coalesce(fair_value_source,'') <> 'xbrl_field' GROUP BY 1").fetchall())
