import json

import pandas as pd
import pytest

from pipeline.sector_enrichment import file_sha,load_decisions,replay
from scripts.run_sector_enrichment import prepare,run


def bundle(tmp_path):
    taxonomy=tmp_path/"taxonomy.json"
    taxonomy.write_text(json.dumps(["Application Software","Oil & Gas Equipment & Services"]))
    members=tmp_path/"members.csv"
    members.write_text("row_id,subject\nR1,acme\nR2,acme\nR3,acme\n")
    path=tmp_path/"sector_decisions.json"
    payload=dict(format_version=1,admission_status="promoted",taxonomy_sha256=file_sha(taxonomy),
        membership=dict(path=members.name,sha256=file_sha(members)),decisions=[dict(subject="acme",
        decision_id="D1",input_text="Acme",model="model-version",prompt_sha256="hash",recorded_at="2026-09-12T00:00:00Z",
        reason="inference",status="inferred",value="Application Software",confidence="high")])
    path.write_text(json.dumps(payload))
    return path,taxonomy,payload


def test_replay_rejects_changed_identity_preserves_known_sector_and_row_count(tmp_path):
    path,taxonomy,_=bundle(tmp_path)
    frame=pd.DataFrame([dict(row_id=r,canonical_name=n,issuer_name=n,gics_sub_industry=s)
        for r,n,s in (("R1","Acme",""),("R2","Acme","Oil & Gas Equipment & Services"),
                      ("R3","New borrower",""),("R4","Acme",""))])
    result,audit=replay(frame,path,taxonomy)
    assert len(result)==4
    by_id=result.set_index("row_id")
    assert by_id.loc["R1","gics_sub_industry"]=="Application Software"
    assert by_id.loc["R2","gics_sub_industry"]=="Oil & Gas Equipment & Services"
    assert by_id.loc["R3","gics_sub_industry"]==""
    assert by_id.loc["R4","gics_sub_industry"]==""
    assert audit.set_index("row_id").loc["R3","status"]=="subject_changed"
    again,retained=replay(result,path,taxonomy,prior_audit=audit)
    assert retained.set_index('row_id').loc['R1','status']=='applied'
    assert retained.set_index('row_id').loc['R2','status']=='already_classified'
    assert again.set_index('row_id').loc['R3','gics_sub_industry']==''


@pytest.mark.parametrize("change",["proposal","taxonomy","membership","duplicate","thin"])
def test_unadmitted_stale_or_ambiguous_decision_blocks(tmp_path,change):
    path,taxonomy,payload=bundle(tmp_path)
    if change=="proposal": payload["admission_status"]="proposed"
    elif change=="taxonomy": payload["taxonomy_sha256"]="changed"
    elif change=="membership": (tmp_path/"members.csv").write_text("row_id,subject\nwrong,acme\n")
    elif change=="duplicate": payload["decisions"]*=2
    else: payload["decisions"][0]["confidence"]="low"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError): load_decisions(path,taxonomy)


def test_full_task_budget_abstention_residuals_and_taxonomy_control(tmp_path,monkeypatch):
    from pipeline import config
    from scripts import gics_quality_gate
    from scripts import run_sector_enrichment as task
    taxonomy=tmp_path/"taxonomy.json";taxonomy.write_text('["Application Software"]')
    cohort=tmp_path/"cohort.json";cohort.write_text('{}')
    monkeypatch.setattr(config,"GICS_REFERENCE_FILE",taxonomy)
    monkeypatch.setattr(config,"WRAPPER_COHORT_MANIFEST_FILE",cohort)
    monkeypatch.setattr(gics_quality_gate,"GICS_REFERENCE_FILE",taxonomy)
    monkeypatch.setattr(task,"load_cohort",lambda *a:{"0000000123":"Fixture"})
    hp=tmp_path/"holdings.csv"
    rows=[dict(row_id="R"+str(i),cik="123",canonical_name="Company "+str(i),issuer_name="Name "+str(i),
        entity_id="E"+str(i),report_date="2026-03-31",fair_value=str(i-2),
        gics_sub_industry="",issuer_category="CORPORATE") for i in range(53)]
    rows.append(dict(rows[0],row_id="outside",cik="999"))
    pd.DataFrame(rows).to_csv(hp,index=False)
    calls=[]
    def classify(names,taxonomy):
        calls.append(names)
        return [dict(id=i,gics_sub_industry="Application Software",confidence="high" if i==1 else "low")
                for i in range(1,len(names)+1)]
    output=tmp_path/"out"
    run(hp,output,1,call=classify)
    assert len(calls)==1 and len(calls[0])==50
    summary=json.loads((output/"summary.json").read_text())
    assert summary["inferred"]==1 and summary["abstained"]==49
    assert summary["quality_gate"] is True
    residual=pd.read_csv(output/"residuals.csv")
    assert len(residual)==52
    assert (residual.reason=="outside_call_budget").sum()==3
    assert json.loads((output/"population.json").read_text())["rows"]==53
    load_decisions(output/"sector_decisions.json",taxonomy)


def test_service_error_record_does_not_expose_exception_credentials(tmp_path):
    from types import SimpleNamespace
    from scripts.run_sector_enrichment import RecordedClient
    def failing(**kwargs): raise ValueError('authentication failed: example-private-credential')
    client=SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=failing))))
    recorder=RecordedClient(client,tmp_path/'response.json')
    with pytest.raises(RuntimeError,match='Recorded classification service failure') as error:
        recorder.parse(model='model-version')
    assert 'example-private-credential' not in str(error.value)
    assert 'example-private-credential' not in (tmp_path/'response.json').read_text()
    assert recorder.metadata['error']['type']=='ValueError'


@pytest.mark.parametrize('empty',[False,True])
@pytest.mark.parametrize('known',[None,'Oil & Gas Equipment & Services'])
def test_all_abstained_or_empty_bundle_preserves_null_and_known_sectors(tmp_path,empty,known):
    path,taxonomy,payload=bundle(tmp_path)
    if empty:
        payload['decisions']=[]
    else:
        payload['decisions'][0].update(status='abstained',value=None,reason='service_error')
    path.write_text(json.dumps(payload))
    frame=pd.DataFrame([dict(row_id='R1',canonical_name='Acme',issuer_name='Acme',gics_sub_industry=known),
                        dict(row_id='R2',canonical_name='Acme',issuer_name='Acme',gics_sub_industry=None)])
    result,audit=replay(frame,path,taxonomy)
    values=result.set_index('row_id').gics_sub_industry
    assert len(result)==2 and pd.isna(values['R2'])
    assert pd.isna(values['R1']) if known is None else values['R1']==known
    assert set(audit.status)==({'no_decision'} if empty else {'abstained'})
    assert audit.value.isna().all()
