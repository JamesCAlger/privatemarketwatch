import json

import pytest

from pipeline.programme.core import ContractError,sha
from pipeline.programme.rule_snapshot import include_retirement


def inputs(tmp_path,store='agent_b2_corrections'):
    root=tmp_path/'root';frozen=tmp_path/'frozen'
    relative='data/overrides/'+store+'/123'
    folder=root/relative;old=frozen/relative
    folder.mkdir(parents=True);old.mkdir(parents=True)
    (old/'column_remap.json').write_text('{"preserved":true}')
    (folder/'_retired_column_remap.json').write_bytes((old/'column_remap.json').read_bytes())
    evidence=root/'evidence.xml';evidence.write_text('<source/>')
    review=folder/'_retired_column_remap.review.json'
    review.write_text(json.dumps(dict(status='retired',mechanism='Contradicted by source',
        original_file='_retired_column_remap.json',previous_file='column_remap.json',
        original_sha256=sha(old/'column_remap.json'),sources=[dict(path='evidence.xml',sha256=sha(evidence))])))
    return root,frozen,review,old


def test_retirement_requires_exact_original_and_preserves_it(tmp_path):
    root,frozen,review,old=inputs(tmp_path)
    prior=(old/'column_remap.json').read_bytes()
    overlay=include_retirement(root,frozen,review)
    assert not (old/'column_remap.json').exists()
    assert (old/'_retired_column_remap.json').read_bytes()==prior
    assert (old/review.name).read_bytes()==review.read_bytes()
    assert overlay['retired_path'].endswith('/column_remap.json')


@pytest.mark.parametrize('changed',['original','evidence','path'])
def test_changed_or_escaping_retirement_evidence_cannot_mutate_snapshot(tmp_path,changed):
    root,frozen,review,old=inputs(tmp_path)
    if changed=='original':(old/'column_remap.json').write_text('{"different":true}')
    elif changed=='evidence':(root/'evidence.xml').write_text('<changed/>')
    else:
        data=json.loads(review.read_text());data['previous_file']='../column_remap.json'
        review.write_text(json.dumps(data))
    before=(old/'column_remap.json').read_bytes()
    with pytest.raises(ContractError):include_retirement(root,frozen,review)
    assert (old/'column_remap.json').read_bytes()==before
    assert not (old/'_retired_column_remap.json').exists()


def test_investigation_retirement_carries_exact_owner_decision(tmp_path):
    root,frozen,review,old=inputs(tmp_path,'agent_investigate_rules')
    decision=root/'docs/decision.md';decision.parent.mkdir();decision.write_text('Retain separately disclosed scopes')
    data=json.loads(review.read_text());data['decision']=dict(path='docs/decision.md',sha256=sha(decision))
    review.write_text(json.dumps(data))
    include_retirement(root,frozen,review)
    assert (frozen/'docs/decision.md').read_bytes()==decision.read_bytes()
    assert not (old/'column_remap.json').exists()


def test_retirement_cannot_rely_on_changed_policy(tmp_path):
    root,frozen,review,old=inputs(tmp_path)
    decision=root/'decision.md';decision.write_text('original decision')
    data=json.loads(review.read_text());data['decision']=dict(path='decision.md',sha256=sha(decision))
    review.write_text(json.dumps(data));decision.write_text('changed decision')
    with pytest.raises(ContractError,match='policy decision changed'):
        include_retirement(root,frozen,review)
    assert (old/'column_remap.json').exists()
