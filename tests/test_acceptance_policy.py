import json

import pytest

from pipeline.acceptance_policy import load, verify
from pipeline.programme.core import ContractError, sha


def policy(tmp_path):
    decision=tmp_path/'decision.md';decision.write_text('Synthetic owner decision for tests only')
    measurement=tmp_path/'measurement.json';measurement.write_text('{"synthetic":true}')
    authority=dict(path=decision.name,sha256=sha(decision))
    files={name:dict(sha256=name+'-digest') for name in ('contexts','reconciliation','obligations','exclusions')}
    data=dict(format_version=1,field_floors=dict(status='adopted',decision=authority,
        measurement=dict(path=measurement.name,sha256=sha(measurement)),floors=dict(fair_value=.95,maturity_precision=.9)),
        denominator=dict(status='adopted',decision=authority,
            evidence_sha256={name:files[name]['sha256'] for name in ('obligations','exclusions')}),
        source_roster=dict(status='certified',decision=authority,currency='USD',
            evidence_sha256={name:files[name]['sha256'] for name in ('contexts','reconciliation')}))
    path=tmp_path/'policy.json';path.write_text(json.dumps(data))
    return path,data,files


def test_absence_and_pending_do_not_infer_approval(tmp_path):
    absent,records=load(None,evidence_files={})
    assert not absent['source_roster_certified'] and absent['field_floor_adoption'] is None and not records
    path=tmp_path/'pending.json'
    path.write_text(json.dumps(dict(format_version=1,field_floors=dict(status='pending',floors=dict(fair_value=0)))))
    pending,_=load(path,evidence_files={})
    assert pending==absent


def test_adopted_policy_binds_decision_measurement_and_exact_populations(tmp_path):
    path,data,files=policy(tmp_path)
    result,records=load(path,evidence_files=files)
    assert result['field_assessability_floors']==dict(fair_value=.95,maturity_precision=.9)
    assert result['denominator_adoption'] and result['source_roster_certified']
    assert len(records)==3
    verify(records)
    (tmp_path/'decision.md').write_text('changed')
    with pytest.raises(ContractError,match='changed'):
        verify(records)


@pytest.mark.parametrize('section,name', [('source_roster','contexts'),('source_roster','reconciliation'),
                                        ('denominator','obligations'),('denominator','exclusions')])
def test_adoption_cannot_certify_different_evidence(tmp_path,section,name):
    path,data,files=policy(tmp_path)
    files[name]['sha256']='changed'
    with pytest.raises(ContractError,match='different'):
        load(path,evidence_files=files)


@pytest.mark.parametrize('value',[True,-.1,1.1,float('nan'),'1'])
def test_invalid_floors_do_not_become_adopted(tmp_path,value):
    path,data,files=policy(tmp_path)
    data['field_floors']['floors']['fair_value']=value
    path.write_text(json.dumps(data))
    with pytest.raises(ContractError,match='finite proportions'):
        load(path,evidence_files=files)


@pytest.mark.parametrize('key',['decision','measurement'])
def test_numeric_floor_alone_is_not_authority(tmp_path,key):
    path,data,files=policy(tmp_path)
    del data['field_floors'][key]
    path.write_text(json.dumps(data))
    with pytest.raises(ContractError,match='recorded decision'):
        load(path,evidence_files=files)
