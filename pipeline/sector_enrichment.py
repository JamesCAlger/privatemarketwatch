"""Replay recorded P5 inferences by observation and unchanged entity wording.

No model calls occur here. The decision bundle pins its taxonomy, exact input
text and membership; a renamed/reassigned observation needs a new decision.
"""
from pathlib import Path
import hashlib
import json

import duckdb
import pandas as pd

from pipeline.programme.artifacts import literal

SUBJECT_SQL="lower(trim(coalesce(nullif(cast(canonical_name AS VARCHAR),''),cast(issuer_name AS VARCHAR),'')))"


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def load_decisions(path, taxonomy_path):
    path=Path(path)
    bundle=json.loads(path.read_text(encoding="utf-8"))
    if bundle.get("format_version")!=1 or bundle.get("admission_status")!="promoted":
        raise ValueError("Sector bundle is not admitted")
    if bundle.get("taxonomy_sha256")!=file_sha(taxonomy_path):
        raise ValueError("Sector taxonomy changed")
    membership=(path.parent/bundle["membership"]["path"]).resolve()
    if not membership.is_relative_to(path.parent.resolve()) or file_sha(membership)!=bundle["membership"]["sha256"]:
        raise ValueError("Sector observation membership changed")
    valid=set(json.loads(Path(taxonomy_path).read_text(encoding="utf-8")))
    decisions=bundle["decisions"]
    seen=set()
    for decision in decisions:
        subject=decision["subject"]
        if not subject or subject in seen:
            raise ValueError("Blank or duplicate sector subject")
        seen.add(subject)
        if not all(decision.get(k) for k in ("decision_id","input_text","model","prompt_sha256","recorded_at","reason")):
            raise ValueError("Sector decision lacks provenance")
        if decision["input_text"].lower().strip()!=subject:
            raise ValueError("Sector input does not match subject")
        if decision["status"] not in ("inferred","abstained"):
            raise ValueError("Invalid sector status")
        if decision["status"]=="inferred" and (decision["value"] not in valid or decision["confidence"]!="high"):
            raise ValueError("Invalid admitted sector inference")
    return bundle,membership


def replay(frame, bundle_path, taxonomy_path, *, prior_audit=None):
    bundle,membership=load_decisions(bundle_path,taxonomy_path)
    decisions=pd.DataFrame(bundle["decisions"],columns=["subject","decision_id","status","value"],dtype='string')
    frame=frame.copy()
    # An all-abstained bundle and an unclassified sample both have all-null
    # columns. Keep their declared text types across the pandas/DuckDB boundary.
    for column in ('row_id','canonical_name','issuer_name','gics_sub_industry'):
        frame[column]=frame[column].astype('string')
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        con.register("holdings",frame)
        con.register("decisions",decisions)
        if prior_audit is None: prior_audit=pd.DataFrame(columns=['row_id','decision_id','status'])
        con.register('prior_audit',prior_audit[['row_id','decision_id','status']].astype('string'))
        if con.execute('SELECT count(*) FROM (SELECT row_id FROM prior_audit GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
            raise ValueError('Prior sector audit repeats observation identity')
        con.execute("CREATE TABLE members AS SELECT * FROM read_csv_auto("+literal(membership)+",all_varchar=true)")
        if con.execute("SELECT count(*) FROM (SELECT row_id FROM members GROUP BY row_id HAVING count(*)>1)").fetchone()[0]:
            raise ValueError("Sector membership is not observation-unique")
        valid=pd.DataFrame({"value":json.loads(Path(taxonomy_path).read_text(encoding="utf-8"))})
        con.register("valid",valid)
        con.execute("""CREATE TABLE resolved AS SELECT h.row_id,d.decision_id,d.value,
            CASE WHEN d.subject IS NULL THEN 'no_decision'
                 WHEN """+SUBJECT_SQL+"""<>m.subject THEN 'subject_changed'
                 WHEN d.status<>'inferred' THEN 'abstained'
                 WHEN p.status='applied' AND p.decision_id=d.decision_id AND h.gics_sub_industry=d.value THEN 'applied'
                 WHEN EXISTS(SELECT 1 FROM valid v WHERE v.value=h.gics_sub_industry) THEN 'already_classified'
                 ELSE 'applied' END AS status
            FROM holdings h JOIN members m ON h.row_id=m.row_id
            LEFT JOIN decisions d ON d.subject=m.subject LEFT JOIN prior_audit p ON p.row_id=h.row_id""")
        result=con.execute("""SELECT h.* REPLACE(CASE WHEN r.status='applied' THEN r.value
            ELSE h.gics_sub_industry END AS gics_sub_industry)
            FROM holdings h LEFT JOIN resolved r ON h.row_id=r.row_id""").fetchdf()
        audit=con.execute("SELECT *, 'inferred' AS derivation FROM resolved ORDER BY row_id").fetchdf()
    return result,audit
