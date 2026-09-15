"""Candidate-local durable identities with immutable allocation and revision history.

The matcher supplies continuity components. This registry persists identities;
it never decides that two instruments are the same. Unexpected merges/splits
stop allocation until a governed revision identifies the affected observations.
"""
from __future__ import annotations
import json
from pathlib import Path
import shutil
from uuid import UUID

import duckdb
import pandas as pd

NAMESPACE=UUID("7f737366-c6c0-5d8c-88d4-07c1e817253b")
VERSION="durable-identity.v1"


def uuid5_sql(kind,scope,decision):
    """RFC UUIDv5, computed by DuckDB over UTF-8 JSON [kind,scope,decision]."""
    digest="sha1(from_hex('"+NAMESPACE.hex+"') || encode(to_json(list_value("+kind+","+scope+","+decision+"))))"
    return ("(SELECT substr(h,1,8)||'-'||substr(h,9,4)||'-5'||substr(h,14,3)||'-'||"
        "substr('89ab',((strpos('0123456789abcdef',substr(h,17,1))-1)%4)+1,1)||substr(h,18,3)||'-'||substr(h,21,12) "
        "FROM (SELECT "+digest+" AS h))")


def initialize(con):
    con.execute("CREATE TABLE IF NOT EXISTS registry_meta(version VARCHAR PRIMARY KEY)")
    versions=con.execute("SELECT version FROM registry_meta").fetchall()
    if versions and versions!=[(VERSION,)]: raise ValueError("Unsupported durable registry version")
    con.execute("INSERT INTO registry_meta SELECT ? WHERE NOT EXISTS(SELECT 1 FROM registry_meta)",[VERSION])
    con.execute("""CREATE TABLE IF NOT EXISTS identities(identity_id VARCHAR PRIMARY KEY,kind VARCHAR,
        scope VARCHAR,creation_decision_id VARCHAR,created_release VARCHAR,status VARCHAR)""")
    con.execute("""CREATE TABLE IF NOT EXISTS assignments(kind VARCHAR,row_id VARCHAR,identity_id VARCHAR,
        assigned_release VARCHAR,PRIMARY KEY(kind,row_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS aliases(build_fingerprint VARCHAR,kind VARCHAR,scope VARCHAR,
        legacy_id VARCHAR,identity_id VARCHAR,PRIMARY KEY(build_fingerprint,kind,scope,legacy_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS revisions(decision_id VARCHAR,row_id VARCHAR,kind VARCHAR,
        old_identity_id VARCHAR,new_identity_id VARCHAR,release_id VARCHAR,evidence VARCHAR,
        PRIMARY KEY(decision_id,kind,row_id))""")


def revise(con,revisions,release_id):
    """Apply explicit promoted reassignments to a private registry copy.

    Each revision supplies a complete observation list. Empty lists, absent
    assignments and scope changes cannot silently create identity links.
    """
    for item in revisions:
        if item.get("admission_status")!="promoted" or not all(item.get(k) for k in
            ("decision_id","kind","scope","evidence","row_ids","old_identity_id","action")):
            raise ValueError("Identity revision lacks promotion or evidence")
        if item["kind"] not in ("entity","position") or item["action"] not in ("merge","split"):
            raise ValueError("Unsupported identity revision")
        con.register("revision_rows",pd.DataFrame({"row_id":item["row_ids"]}))
        if con.execute("SELECT count(*)-count(DISTINCT row_id) FROM revision_rows").fetchone()[0]:
            raise ValueError("Revision repeats an observation")
        old=con.execute("SELECT kind,scope FROM identities WHERE identity_id=?",[item["old_identity_id"]]).fetchone()
        if old!=(item["kind"],item["scope"]): raise ValueError("Revision changes governed scope")
        if con.execute("""SELECT count(*) FROM revision_rows r LEFT JOIN assignments a
            ON r.row_id=a.row_id AND a.kind=? WHERE a.identity_id IS DISTINCT FROM ?""",
            [item["kind"],item["old_identity_id"]]).fetchone()[0]:
            raise ValueError("Revision names absent or differently assigned observations")
        if item["action"]=="merge":
            target=item.get("survivor")
            survivor=con.execute("SELECT kind,scope,status FROM identities WHERE identity_id=?",[target]).fetchone()
            if survivor!=(item["kind"],item["scope"],"active") or target==item["old_identity_id"]:
                raise ValueError("Invalid merge survivor")
        else:
            target=con.execute("SELECT "+uuid5_sql("?","?","?"),
                [item["kind"],item["scope"],item["decision_id"]]).fetchone()[0]
            con.execute("INSERT INTO identities VALUES (?,?,?,?,?,'active')",
                [target,item["kind"],item["scope"],item["decision_id"],release_id])
        con.execute("""INSERT INTO revisions SELECT ?,r.row_id,?,?,?, ?,? FROM revision_rows r""",
            [item["decision_id"],item["kind"],item["old_identity_id"],target,release_id,item["evidence"]])
        con.execute("""UPDATE assignments SET identity_id=?,assigned_release=? WHERE kind=?
            AND row_id IN (SELECT row_id FROM revision_rows)""",[target,release_id,item["kind"]])
        remaining=con.execute("SELECT count(*) FROM assignments WHERE identity_id=?",[item["old_identity_id"]]).fetchone()[0]
        if item["action"]=="merge" and remaining:
            raise ValueError("Merge leaves observations pointing to the retired identity")
        if not remaining:
            con.execute("UPDATE identities SET status='retired' WHERE identity_id=?",[item["old_identity_id"]])


def allocate(frame,matches,*,input_registry=None,output_registry,release_id,build_fingerprint,revisions=()):
    if not release_id or not build_fingerprint: raise ValueError("Registry requires release and legacy-build identity")
    output=Path(output_registry).resolve()
    if output.exists(): raise ValueError("Use a new candidate-local registry path")
    output.parent.mkdir(parents=True,exist_ok=True)
    if input_registry is not None:
        if not Path(input_registry).is_file(): raise ValueError('Pinned input identity registry is missing')
        if Path(input_registry).resolve()==output: raise ValueError("Never mutate the accepted registry in place")
        shutil.copy2(input_registry,output)
    from pipeline.accounting_scope import annotate
    frame=annotate(frame)
    for field in ("jv_subsidiary","is_subsidiary","entity_id"):
        if field not in frame: frame[field]=""
    for field in ('row_id','position_id','entity_id','cik','is_subsidiary','jv_subsidiary'):
        frame[field]=frame[field].astype('string').fillna('')
    with duckdb.connect(str(output),config={"threads":2,"memory_limit":"-1"}) as con:
        con.execute("BEGIN TRANSACTION")
        initialize(con)
        con.register("holdings",frame);con.register("matches",matches)
        if con.execute("""SELECT count(*) FROM holdings WHERE coalesce(row_id,'')='' OR coalesce(position_id,'')=''""").fetchone()[0]:
            raise ValueError("Durable allocation requires complete observation/component IDs")
        if con.execute("SELECT count(*)-count(DISTINCT row_id) FROM holdings").fetchone()[0]:
            raise ValueError("Repeated observation identity")
        from pipeline.matching_contract import scope_sql
        con.execute("""CREATE TEMP TABLE incoming AS
            SELECT 'position' AS kind,row_id,position_id AS legacy_id,
                """+scope_sql(frame.columns)+""" AS scope
            FROM holdings UNION ALL
            SELECT 'entity',row_id,entity_id,'global' FROM holdings WHERE coalesce(entity_id,'')<>''""")
        if con.execute("""SELECT count(*) FROM (SELECT kind,legacy_id FROM incoming GROUP BY ALL HAVING count(DISTINCT scope)>1)""").fetchone()[0]:
            raise ValueError("Matcher continuity crosses accounting scope")
        revise(con,revisions,release_id)
        con.execute("""CREATE TEMP TABLE groups AS SELECT i.kind,i.scope,i.legacy_id,
            'initial-observation:'||min(i.row_id) AS creation_decision,
            count(DISTINCT a.identity_id) AS previous_count,min(a.identity_id) AS previous_id
            FROM incoming i LEFT JOIN assignments a USING(kind,row_id) GROUP BY i.kind,i.scope,i.legacy_id""")
        if con.execute("SELECT count(*) FROM groups WHERE previous_count>1").fetchone()[0]:
            raise ValueError("Unreviewed identity merge")
        if con.execute("""SELECT count(*) FROM (SELECT previous_id FROM groups WHERE previous_id IS NOT NULL
            GROUP BY previous_id HAVING count(*)>1)""").fetchone()[0]:
            raise ValueError("Unreviewed identity split")
        if con.execute("""SELECT count(*) FROM groups g JOIN identities r ON g.previous_id=r.identity_id
            WHERE g.kind<>r.kind OR g.scope<>r.scope OR r.status<>'active'""").fetchone()[0]:
            raise ValueError("Existing identity changed scope or was retired")
        con.execute("""CREATE TEMP TABLE mapped AS SELECT *,coalesce(previous_id,"""+
            uuid5_sql("kind","scope","creation_decision")+") AS identity_id FROM groups")
        con.execute("""INSERT INTO identities SELECT identity_id,kind,scope,creation_decision,?,'active'
            FROM mapped WHERE previous_id IS NULL""",[release_id])
        con.execute("""INSERT OR REPLACE INTO assignments SELECT i.kind,i.row_id,m.identity_id,?
            FROM incoming i JOIN mapped m USING(kind,scope,legacy_id)""",[release_id])
        # The build fingerprint is part of every legacy alias; raw E/P numbers
        # alone have no cross-rebuild meaning.
        conflict=con.execute("""SELECT count(*) FROM mapped m JOIN aliases a USING(kind,scope,legacy_id)
            WHERE a.build_fingerprint=? AND a.identity_id<>m.identity_id""",[build_fingerprint]).fetchone()[0]
        if conflict: raise ValueError("Legacy-build alias changed identity")
        con.execute("""INSERT OR REPLACE INTO aliases SELECT ?,kind,scope,legacy_id,identity_id FROM mapped""",[build_fingerprint])
        result=con.execute("""SELECT h.* REPLACE(p.identity_id AS position_id,
            CASE WHEN coalesce(h.entity_id,'')<>'' THEN e.identity_id END AS entity_id)
            FROM holdings h JOIN assignments p ON h.row_id=p.row_id AND p.kind='position'
            LEFT JOIN assignments e ON h.row_id=e.row_id AND e.kind='entity'""").fetchdf()
        updated=con.execute("""SELECT m.* REPLACE(p.identity_id AS position_id) FROM matches m
            LEFT JOIN mapped p ON p.kind='position' AND CAST(m.position_id AS VARCHAR)=p.legacy_id""").fetchdf()
        if len(result)!=len(frame) or len(updated)!=len(matches): raise ValueError("Registry changed observation/match grain")
        if len(updated) and updated.position_id.isna().any(): raise ValueError("Match identity did not resolve")
        mapping=con.execute("SELECT kind,scope,legacy_id,identity_id FROM mapped ORDER BY kind,scope,legacy_id").fetchdf()
        stats=dict(identities=con.execute("SELECT count(*) FROM identities").fetchone()[0],
            assignments=con.execute("SELECT count(*) FROM assignments").fetchone()[0],
            revisions=con.execute("SELECT count(*) FROM revisions").fetchone()[0])
        con.execute("COMMIT")
    return result,updated,mapping,stats
