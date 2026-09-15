import hashlib
import json
from uuid import uuid5

import duckdb
import pandas as pd
import pytest

from pipeline.durable_identity import NAMESPACE,allocate,uuid5_sql


def holdings(*changes):
    base=dict(row_id="R1",position_id="rawP1",entity_id="rawE1",cik="123",report_date="2026-03-31",
        is_subsidiary="0",jv_subsidiary="")
    return pd.DataFrame([dict(base,**change) for change in (changes or ({},))])


def matches(*ids):
    return pd.DataFrame({"position_id":list(ids)})


@pytest.mark.parametrize("kind,scope,decision",[("position","123|parent","R1"),("entity","global","Muenchen \u00e9")])
def test_vector_uuid_matches_rfc_uuid5(kind,scope,decision):
    with duckdb.connect() as con:
        actual=con.execute("SELECT "+uuid5_sql("?","?","?"),[kind,scope,decision]).fetchone()[0]
    assert actual==str(uuid5(NAMESPACE,json.dumps([kind,scope,decision],ensure_ascii=False,separators=(",",":"))))


def test_cold_reorder_and_older_observation_do_not_renumber(tmp_path):
    frame=holdings({},dict(row_id="R2",report_date="2026-06-30"),dict(row_id="other",position_id="rawP2",entity_id="rawE2"))
    first,_,_,_=allocate(frame,matches("rawP1","rawP2"),output_registry=tmp_path/"first.duckdb",release_id="first",build_fingerprint="A")
    second,_,_,_=allocate(frame.iloc[::-1],matches("rawP1","rawP2"),output_registry=tmp_path/"second.duckdb",release_id="second",build_fingerprint="B")
    assert first.set_index("row_id").position_id.to_dict()==second.set_index("row_id").position_id.to_dict()
    prior_hash=hashlib.sha256((tmp_path/"first.duckdb").read_bytes()).hexdigest()
    extended=pd.concat([frame,holdings(dict(row_id="R0",report_date="2025-12-31"))],ignore_index=True)
    third,_,_,_=allocate(extended,matches("rawP1","rawP2"),input_registry=tmp_path/"first.duckdb",
        output_registry=tmp_path/"third.duckdb",release_id="third",build_fingerprint="C")
    assert third.set_index("row_id").loc["R0","position_id"]==first.set_index("row_id").loc["R1","position_id"]
    assert hashlib.sha256((tmp_path/"first.duckdb").read_bytes()).hexdigest()==prior_hash


def test_one_entity_three_positions_and_scope_cannot_cross(tmp_path):
    frame=holdings({},dict(row_id="loan-q2",report_date="2026-06-30"),
        dict(row_id="equity",position_id="rawP2"),dict(row_id="fundB",position_id="rawP3",cik="456"))
    result,updated,_,_=allocate(frame,matches("rawP1"),output_registry=tmp_path/"valid.duckdb",release_id="R",build_fingerprint="B")
    assert result.entity_id.nunique()==1 and result.position_id.nunique()==3
    assert updated.iloc[0].position_id==result.set_index("row_id").loc["R1","position_id"]
    with pytest.raises(ValueError,match="accounting scope"):
        allocate(holdings({},dict(row_id="JV",is_subsidiary="1",jv_subsidiary="JV")),matches(),
            output_registry=tmp_path/"invalid.duckdb",release_id="R",build_fingerprint="B")


def test_jv_boolean_is_not_accounting_identity_and_pinned_input_must_exist(tmp_path):
    frame=holdings(dict(is_subsidiary='1',jv_subsidiary='Y'),dict(row_id='R2',is_subsidiary='1',jv_subsidiary='Y'))
    with pytest.raises(ValueError,match='accounting scope'):
        allocate(frame,matches(),output_registry=tmp_path/'ambiguous.duckdb',release_id='R',build_fingerprint='B')
    frame['bdc_dimensions_raw']='us-gaap:EquityMethodInvestmentEquityMethodInvesteeNameAxis=ExampleJVMember'
    final,_,_,_=allocate(frame,matches(),output_registry=tmp_path/'scoped.duckdb',release_id='R',build_fingerprint='B')
    assert final.position_id.nunique()==1
    with pytest.raises(ValueError,match='Pinned input identity registry is missing'):
        allocate(frame,matches(),input_registry=tmp_path/'missing.duckdb',output_registry=tmp_path/'noinput.duckdb',release_id='R',build_fingerprint='B')


def test_split_requires_explicit_observation_revision_and_preserves_history(tmp_path):
    before=holdings({},dict(row_id="R2",report_date="2026-06-30"))
    first,_,_,_=allocate(before,matches(),output_registry=tmp_path/"before.duckdb",release_id="A",build_fingerprint="A")
    after=before.copy();after.loc[after.row_id=="R2","position_id"]="new_component"
    with pytest.raises(ValueError,match="Unreviewed identity split"):
        allocate(after,matches(),input_registry=tmp_path/"before.duckdb",output_registry=tmp_path/"failed.duckdb",release_id="B",build_fingerprint="B")
    revision=dict(decision_id="split-1",kind="position",scope="0000000123|parent",admission_status="promoted",
        old_identity_id=first.iloc[0].position_id,row_ids=["R2"],action="split",evidence="cached filing adjudication")
    result,_,_,stats=allocate(after,matches(),input_registry=tmp_path/"before.duckdb",
        output_registry=tmp_path/"after.duckdb",release_id="B",build_fingerprint="B",revisions=[revision])
    assert result.position_id.nunique()==2 and stats["revisions"]==1
    assert result.set_index("row_id").loc["R1","position_id"]==first.iloc[0].position_id


def test_merge_names_survivor_and_cannot_leave_dangling_retirement(tmp_path):
    frame=holdings({},dict(row_id="R2",position_id="rawP2",report_date="2026-06-30"))
    first,_,_,_=allocate(frame,matches(),output_registry=tmp_path/"before.duckdb",release_id="A",build_fingerprint="A")
    merged=frame.copy();merged["position_id"]="one_component"
    with pytest.raises(ValueError,match="Unreviewed identity merge"):
        allocate(merged,matches(),input_registry=tmp_path/"before.duckdb",output_registry=tmp_path/"failed.duckdb",release_id="B",build_fingerprint="B")
    ids=first.set_index("row_id").position_id
    revision=dict(decision_id="merge-1",kind="position",scope="0000000123|parent",admission_status="promoted",
        old_identity_id=ids["R2"],survivor=ids["R1"],row_ids=["R2"],action="merge",evidence="same facility amendment")
    result,_,_,stats=allocate(merged,matches(),input_registry=tmp_path/"before.duckdb",output_registry=tmp_path/"after.duckdb",
        release_id="B",build_fingerprint="B",revisions=[revision])
    assert result.position_id.nunique()==1 and result.iloc[0].position_id==ids["R1"]
    with duckdb.connect(str(tmp_path/"after.duckdb"),read_only=True) as con:
        assert con.execute("SELECT status FROM identities WHERE identity_id=?",[ids["R2"]]).fetchone()[0]=="retired"
        assert con.execute("SELECT count(DISTINCT build_fingerprint) FROM aliases").fetchone()[0]==2
