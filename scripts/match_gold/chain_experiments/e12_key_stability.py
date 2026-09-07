"""E12: cross-quarter stability of the legal-form-only borrower key.

On production-chained positions (same position_id in adjacent quarters, same CIK):
how often does the legal key change? Compared with raw name and name_key, and split
by whether the change is an alias/structure variant or something else.
Read-only. Cohort BDC rows.
"""
import json
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from pipeline.position_matching import _name_key_sql, _next_quarter_sql, _quarter_label_sql  # noqa: E402

HOLD = REPO / "data/output/private_markets_holdings.csv"
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
cik_list = ",".join(f"'{e['cik']}'" for e in json.load(open(MAN))["entries"])

LEGAL_ONLY = (r"\s+(?:inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|"
              r"lp|l\.p|plc|sa|s\.a|bv|b\.v|gmbh|ag|pty|pte|sarl|s\.a\.r\.l)\.?(\s|$)")
STRUCT = (r"\s+(?:holdings?|holdco|intermediate|parent|buyer|acquisition|acquisitionco|bidco|midco|"
          r"topco|opco|group)(\s|$)")
def legal_sql(col):
    s = _name_key_sql(col)
    s = f"regexp_replace({s}, '\\s*\\((?:dba|d/b/a|fka|f/k/a|formerly|aka)\\s[^)]*\\)', '', 'g')"
    s = f"regexp_replace({s}, '[^a-z0-9 ]', ' ', 'g')"
    for _ in range(2):
        s = f"regexp_replace({s}, '{LEGAL_ONLY}', ' ', 'g')"
    return f"TRIM(regexp_replace({s}, '\\s+', ' ', 'g'))"
def struct_sql(col):
    s = legal_sql(col)
    for _ in range(3):
        s = f"regexp_replace({s}, '{STRUCT}', ' ', 'g')"
    return f"TRIM(regexp_replace({s}, '\\s+', ' ', 'g'))"

con = duckdb.connect()
con.execute("CREATE MACRO avgb(x) AS AVG(CASE WHEN x THEN 1 ELSE 0 END)")
con.execute(f"""
CREATE TABLE h AS
SELECT cik, {_quarter_label_sql('report_date')} AS q, position_id, issuer_name, LOWER(issuer_name) AS raw,
       {_name_key_sql('issuer_name')} AS name_key, {legal_sql('issuer_name')} AS lkey, {struct_sql('issuer_name')} AS skey,
       regexp_extract(LOWER(issuer_name), '\\((?:dba|d/b/a|fka|f/k/a|formerly|aka)\\s+([^)]*)\\)', 1) AS alias,
       TRY_CAST(fair_value AS DOUBLE) AS fv, bdc_form_type
FROM read_csv_auto('{HOLD.as_posix()}', all_varchar=true, sample_size=-1)
WHERE LOWER(source)='bdc' AND cik IN ({cik_list}) AND issuer_name IS NOT NULL AND issuer_name<>'' AND position_id IS NOT NULL""")
con.execute(f"""
CREATE TABLE steps AS
SELECT a.cik, a.q, a.issuer_name AS n1, b.issuer_name AS n2, a.raw=b.raw AS raw_same, a.name_key=b.name_key AS namekey_same,
       a.lkey=b.lkey AS lkey_same, a.skey=b.skey AS skey_same,
       (a.alias<>'' AND a.alias=b.lkey) OR (b.alias<>'' AND b.alias=a.lkey) AS alias_bridge,
       a.fv, a.bdc_form_type AS form1, b.bdc_form_type AS form2
FROM h a JOIN h b ON a.cik=b.cik AND a.position_id=b.position_id AND b.q={_next_quarter_sql('a.q')}""")

def show(t, sql):
    print("\n==", t); r = con.execute(sql); print(" | ".join(d[0] for d in r.description))
    for row in r.fetchall():
        print(" | ".join("" if x is None else (f"{x:.4f}" if isinstance(x, float) else str(x)) for x in row))

show("E12a: key stability on adjacent-quarter chain steps (cohort)", """
SELECT COUNT(*) AS steps, ROUND(avgb(raw_same),4) AS raw_name_same, ROUND(avgb(namekey_same),4) AS name_key_same,
       ROUND(avgb(lkey_same),4) AS legal_key_same, ROUND(avgb(skey_same),4) AS struct_key_same,
       ROUND(avgb(NOT lkey_same AND (skey_same OR alias_bridge)),4) AS lkey_change_explained_by_structure_or_alias,
       ROUND(avgb(NOT lkey_same AND NOT skey_same AND NOT alias_bridge),4) AS lkey_change_unexplained
FROM steps""")
show("E12b: legal-key changes by filing-boundary type", """
SELECT CASE WHEN form1 LIKE '10-K%' THEN '10-K -> next' ELSE '10-Q -> next' END AS boundary, COUNT(*) AS steps,
       ROUND(avgb(NOT lkey_same),4) AS lkey_change_rate FROM steps GROUP BY 1""")
show("E12c: per-CIK legal-key change rate (worst 12, >=1000 steps)", """
SELECT cik, COUNT(*) AS steps, ROUND(avgb(NOT lkey_same),4) AS lkey_change, ROUND(avgb(NOT namekey_same),4) AS namekey_change
FROM steps GROUP BY 1 HAVING COUNT(*)>=1000 ORDER BY lkey_change DESC LIMIT 12""")
show("E12d: sample of unexplained legal-key changes (largest FV)", """
SELECT cik, q, n1, n2, ROUND(fv/1e6,1) AS fv_musd FROM steps
WHERE NOT lkey_same AND NOT skey_same AND NOT alias_bridge ORDER BY fv DESC LIMIT 15""")
