"""E11: borrower-id experiments on the cohort (offline).

  a. strict name-key collisions and how it relates to entity_id
  b. dba / fka alias coverage and the cross-fund links aliases add
  c. cross-fund term agreement (maturity + spread) for names held by >=2 funds

Read-only. Cohort BDC rows.
"""
import json
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from pipeline.position_matching import _name_key_sql  # noqa: E402

HOLD = REPO / "data/output/private_markets_holdings.csv"
MAN = REPO / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"
cik_list = ",".join(f"'{e['cik']}'" for e in json.load(open(MAN))["entries"])
OUT = Path(__file__).resolve().parent / "out"

con = duckdb.connect()
con.execute("CREATE MACRO avgb(x) AS AVG(CASE WHEN x THEN 1 ELSE 0 END)")

# Strict key: name_key (ordinal/comma/fka-stripped) -> drop a trailing dba/fka
# parenthetical, legal suffixes, punctuation; collapse whitespace.
SUFFIX = (r"\s+(?:inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|"
          r"lp|l\.p|plc|holdings?|holdco|intermediate|parent|buyer|acquisition|acquisitionco|"
          r"bidco|midco|topco|opco|group|sa|s\.a|bv|b\.v|gmbh|ag|pty|pte|sarl|s\.a\.r\.l)\.?(\s|$)")
def strict_sql(col):
    s = _name_key_sql(col)
    s = f"regexp_replace({s}, '\\s*\\((?:dba|d/b/a|fka|f/k/a|formerly|aka)\\s[^)]*\\)', '', 'g')"
    s = f"regexp_replace({s}, '[^a-z0-9 ]', ' ', 'g')"
    for _ in range(3):
        s = f"regexp_replace({s}, '{SUFFIX}', ' ', 'g')"
    return f"TRIM(regexp_replace({s}, '\\s+', ' ', 'g'))"

LEGAL_ONLY = (r"\s+(?:inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|"
              r"lp|l\.p|plc|sa|s\.a|bv|b\.v|gmbh|ag|pty|pte|sarl|s\.a\.r\.l)\.?(\s|$)")
def legal_sql(col):
    """Strict legal-entity key: legal-form suffixes and punctuation only; structural
    words (holdings, buyer, bidco, parent, intermediate ...) are KEPT."""
    s = _name_key_sql(col)
    s = f"regexp_replace({s}, '\\s*\\((?:dba|d/b/a|fka|f/k/a|formerly|aka)\\s[^)]*\\)', '', 'g')"
    s = f"regexp_replace({s}, '[^a-z0-9 ]', ' ', 'g')"
    for _ in range(2):
        s = f"regexp_replace({s}, '{LEGAL_ONLY}', ' ', 'g')"
    return f"TRIM(regexp_replace({s}, '\\s+', ' ', 'g'))"

ALIAS_RE = r"\((?:dba|d/b/a|fka|f/k/a|formerly|aka)\s+([^)]*)\)"
con.execute(f"""
CREATE TABLE h AS
SELECT row_id, cik, report_date, issuer_name, LOWER(issuer_name) AS name_lower,
       {_name_key_sql('issuer_name')} AS name_key, {strict_sql('issuer_name')} AS skey,
       {legal_sql('issuer_name')} AS lkey,
       entity_id, canonical_name,
       regexp_extract(LOWER(issuer_name), '{ALIAS_RE}', 1) AS alias_raw,
       regexp_matches(LOWER(issuer_name), '(?:^|\\W)(?:dba|d/b/a)(?:\\W|$)') AS has_dba,
       regexp_matches(LOWER(issuer_name), '(?:^|\\W)(?:fka|f/k/a|formerly)(?:\\W|$)') AS has_fka,
       TRY_CAST(maturity_date AS DATE) AS mat, TRY_CAST(basis_spread AS DOUBLE) AS spread,
       TRY_CAST(fair_value AS DOUBLE) AS fv
FROM read_csv_auto('{HOLD.as_posix()}', all_varchar=true, sample_size=-1)
WHERE LOWER(source)='bdc' AND cik IN ({cik_list}) AND issuer_name IS NOT NULL AND issuer_name <> ''""")
con.execute("CREATE TABLE lq AS SELECT * FROM h WHERE report_date = (SELECT MAX(report_date) FROM h)")

def show(t, sql, save=None):
    print("\n==", t); r = con.execute(sql); print(" | ".join(d[0] for d in r.description))
    for row in r.fetchall():
        print(" | ".join("" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x)) for x in row))
    if save:
        con.execute(f"COPY ({sql}) TO '{(OUT/save).as_posix()}' (HEADER)")

# ------------------------------------------------------------------ a. collisions
show("E11a: key cardinalities, latest quarter (lkey = legal-form-only strict key; skey = structure-stripped group-ish key)", """
SELECT COUNT(*) AS rows, COUNT(DISTINCT name_lower) AS raw_names, COUNT(DISTINCT name_key) AS name_keys,
       COUNT(DISTINCT lkey) AS legal_keys, COUNT(DISTINCT skey) AS structure_stripped_keys, COUNT(DISTINCT entity_id) AS entity_ids,
       SUM(lkey='' OR LENGTH(lkey)<4) AS degenerate_lkey_rows
FROM lq""")
show("E11a: legal-key vs entity layer: lkeys split across entities / entities merging several lkeys", """
SELECT
  (SELECT COUNT(*) FROM (SELECT lkey FROM lq WHERE lkey<>'' GROUP BY 1 HAVING COUNT(DISTINCT entity_id)>1)) AS lkeys_multi_entity,
  (SELECT COUNT(*) FROM (SELECT entity_id FROM lq WHERE entity_id IS NOT NULL GROUP BY 1 HAVING COUNT(DISTINCT lkey)>1)) AS entities_multi_lkey,
  (SELECT COUNT(DISTINCT lkey) FROM lq WHERE lkey<>'') AS legal_keys""")
show("E11a: legal keys with >=2 distinct name_keys AND >1 entity_id -- collision suspects under the legal-only key", """
SELECT lkey, COUNT(DISTINCT name_key) AS n_namekeys, COUNT(DISTINCT entity_id) AS n_entities, STRING_AGG(DISTINCT issuer_name, ' || ') AS names
FROM lq WHERE lkey<>'' GROUP BY 1 HAVING COUNT(DISTINCT name_key)>=2 AND COUNT(DISTINCT entity_id)>1 ORDER BY n_namekeys DESC LIMIT 12""",
     save="e11a_legal_key_collision_suspects.csv")
show("E11a: count of legal-key collision suspects", """
SELECT COUNT(*) AS n FROM (SELECT lkey FROM lq WHERE lkey<>'' GROUP BY 1 HAVING COUNT(DISTINCT name_key)>=2 AND COUNT(DISTINCT entity_id)>1)""")
show("E11a: structure words -- how many legal keys collapse into each structure-stripped key (deal-family size)", """
SELECT n_lkeys, COUNT(*) AS skeys FROM (SELECT skey, COUNT(DISTINCT lkey) AS n_lkeys FROM lq WHERE skey<>'' GROUP BY 1) GROUP BY 1 ORDER BY 1 LIMIT 6""")
show("E11a: strict keys that span >1 entity_id (entity layer SPLITS the name) and entity_ids spanning >1 strict key (entity layer MERGES names)", """
SELECT
  (SELECT COUNT(*) FROM (SELECT skey FROM lq WHERE skey<>'' GROUP BY 1 HAVING COUNT(DISTINCT entity_id)>1)) AS skeys_multi_entity,
  (SELECT COUNT(*) FROM (SELECT entity_id FROM lq WHERE entity_id IS NOT NULL GROUP BY 1 HAVING COUNT(DISTINCT skey)>1)) AS entities_multi_skey,
  (SELECT COUNT(DISTINCT skey) FROM lq WHERE skey<>'') AS strict_keys""")
show("E11a: short-stem strict keys (<=1 token or <=5 chars) with >=2 distinct raw names -- collision suspects", """
SELECT skey, COUNT(DISTINCT name_lower) AS n_names, COUNT(DISTINCT cik) AS n_funds, STRING_AGG(DISTINCT issuer_name, ' || ') AS names
FROM lq WHERE skey<>'' AND (LENGTH(skey)<=5 OR NOT regexp_matches(skey, ' '))
GROUP BY 1 HAVING COUNT(DISTINCT name_lower)>=2 ORDER BY n_names DESC LIMIT 15""", save="e11a_short_stem_collisions.csv")
show("E11a: strict keys with >=2 distinct name_keys where the entity layer also disagrees (>1 entity_id) -- likely true collisions", """
SELECT skey, COUNT(DISTINCT name_key) AS n_namekeys, COUNT(DISTINCT entity_id) AS n_entities,
       STRING_AGG(DISTINCT issuer_name, ' || ') AS names
FROM lq WHERE skey<>'' GROUP BY 1 HAVING COUNT(DISTINCT name_key)>=2 AND COUNT(DISTINCT entity_id)>1
ORDER BY n_namekeys DESC LIMIT 15""", save="e11a_collision_suspects.csv")
show("E11a: counts of the above", """
SELECT COUNT(*) AS skeys_multi_namekey_multi_entity FROM
 (SELECT skey FROM lq WHERE skey<>'' GROUP BY 1 HAVING COUNT(DISTINCT name_key)>=2 AND COUNT(DISTINCT entity_id)>1)""")

# ------------------------------------------------------------------ b. aliases
show("E11b: alias coverage (all quarters / latest)", """
SELECT scope, COUNT(*) AS rows, ROUND(avgb(has_dba),3) AS dba_rows, ROUND(avgb(has_fka),3) AS fka_rows,
       ROUND(avgb(alias_raw<>''),3) AS parenthetical_alias_rows,
       COUNT(DISTINCT CASE WHEN alias_raw<>'' THEN skey END) AS strict_keys_with_alias,
       COUNT(DISTINCT skey) AS strict_keys
FROM (SELECT 'all' AS scope, * FROM h UNION ALL SELECT 'latest', * FROM lq) GROUP BY 1 ORDER BY 1""")
con.execute(f"""
CREATE TABLE alias AS
SELECT DISTINCT skey, {strict_sql('alias_raw')} AS alias_key FROM h WHERE alias_raw<>''""")
con.execute("DELETE FROM alias WHERE alias_key='' OR alias_key=skey")
show("E11b: cross-fund links that ONLY an alias provides (latest quarter): fund A names X, fund B names the alias of X", """
WITH k AS (SELECT DISTINCT cik, skey FROM lq WHERE skey<>''),
     via AS (SELECT DISTINCT a.skey AS key_a, b.skey AS key_b, a.cik AS cik_a, b.cik AS cik_b
             FROM k a JOIN alias al ON al.skey=a.skey JOIN k b ON b.skey=al.alias_key AND b.cik<>a.cik
             WHERE NOT EXISTS (SELECT 1 FROM k c WHERE c.cik=b.cik AND c.skey=a.skey))
SELECT COUNT(DISTINCT (key_a, key_b)) AS alias_bridged_name_pairs, COUNT(DISTINCT (cik_a, cik_b, key_a)) AS fund_pair_links,
       (SELECT COUNT(*) FROM alias) AS alias_pairs_total FROM via""")
show("E11b: sample alias-bridged pairs", """
WITH k AS (SELECT DISTINCT cik, skey, MIN(issuer_name) AS nm FROM lq WHERE skey<>'' GROUP BY 1,2)
SELECT a.nm AS name_in_fund_a, b.nm AS name_in_fund_b
FROM k a JOIN alias al ON al.skey=a.skey JOIN k b ON b.skey=al.alias_key AND b.cik<>a.cik
WHERE NOT EXISTS (SELECT 1 FROM k c WHERE c.cik=b.cik AND c.skey=a.skey) LIMIT 10""")

# ------------------------------------------------------------------ c. cross-fund term agreement
con.execute("""
CREATE TABLE mf AS
SELECT skey, COUNT(DISTINCT cik) AS n_funds, SUM(fv) AS fv FROM lq WHERE skey<>'' GROUP BY 1 HAVING COUNT(DISTINCT cik)>=2""")
con.execute("""
CREATE TABLE fp AS
SELECT a.skey, a.cik AS cik_a, b.cik AS cik_b,
  MAX(CASE WHEN a.mat=b.mat AND ABS(a.spread-b.spread)<=0.01 THEN 1 ELSE 0 END) AS agree_mat_spr,
  MAX(CASE WHEN DATE_TRUNC('month', a.mat)=DATE_TRUNC('month', b.mat) AND ABS(a.spread-b.spread)<=0.01 THEN 1 ELSE 0 END) AS agree_month_spr,
  MAX(CASE WHEN ABS(DATEDIFF('day', a.mat, b.mat))<=45 THEN 1 ELSE 0 END) AS agree_mat45,
  MAX(CASE WHEN a.mat=b.mat THEN 1 ELSE 0 END) AS agree_mat,
  MAX(CASE WHEN a.mat IS NOT NULL AND b.mat IS NOT NULL THEN 1 ELSE 0 END) AS both_mat_known
FROM lq a JOIN lq b ON a.skey=b.skey AND a.cik<b.cik
WHERE a.skey IN (SELECT skey FROM mf) GROUP BY 1,2,3""")
show("E11c: cross-fund term agreement, latest quarter (names held by >=2 cohort funds)", """
SELECT (SELECT COUNT(*) FROM mf) AS multi_fund_names, ROUND((SELECT SUM(fv) FROM mf)/1e9,1) AS fv_busd,
  COUNT(*) AS fund_pairs, SUM(both_mat_known) AS pairs_mat_known,
  ROUND(SUM(agree_mat_spr)*1.0/NULLIF(SUM(both_mat_known),0),3) AS share_agree_mat_and_spread,
  ROUND(SUM(agree_mat)*1.0/NULLIF(SUM(both_mat_known),0),3) AS share_agree_maturity_exact,
  ROUND(SUM(agree_month_spr)*1.0/NULLIF(SUM(both_mat_known),0),3) AS share_agree_month_and_spread,
  ROUND(SUM(agree_mat45)*1.0/NULLIF(SUM(both_mat_known),0),3) AS share_agree_maturity_45d,
  ROUND(SUM(CASE WHEN both_mat_known=1 AND agree_mat45=0 THEN 1 ELSE 0 END)*1.0/NULLIF(SUM(both_mat_known),0),3) AS share_no_overlap_45d
FROM fp""")
show("E11c: per-name: share of multi-fund names with NO fund pair agreeing on maturity within 45 days (merge-error or different-deal suspects)", """
WITH per AS (SELECT skey, MAX(agree_mat45) AS any_agree, MAX(both_mat_known) AS known FROM fp GROUP BY 1)
SELECT SUM(known) AS names_checkable, SUM(CASE WHEN known=1 AND any_agree=0 THEN 1 ELSE 0 END) AS names_no_agreement,
       ROUND(SUM(CASE WHEN known=1 AND any_agree=0 THEN 1 ELSE 0 END)*1.0/SUM(known),3) AS share,
       ROUND(SUM(CASE WHEN known=1 AND any_agree=0 THEN mf.fv END)/1e9,1) AS fv_busd
FROM per JOIN mf USING (skey)""")
show("E11c: no-agreement examples within 45 days (largest FV)", """
WITH per AS (SELECT skey, MAX(agree_mat45) AS any_agree, MAX(both_mat_known) AS known FROM fp GROUP BY 1)
SELECT mf.skey, mf.n_funds, ROUND(mf.fv/1e6,1) AS fv_musd,
  (SELECT STRING_AGG(DISTINCT issuer_name || ' [' || COALESCE(CAST(mat AS VARCHAR),'?') || ' ' || COALESCE(CAST(spread AS VARCHAR),'?') || ']', ' || ')
     FROM lq WHERE lq.skey=mf.skey) AS variants
FROM per JOIN mf USING (skey) WHERE known=1 AND any_agree=0 ORDER BY mf.fv DESC LIMIT 12""", save="e11c_no_agreement.csv")
