import json
import os

import pytest

from pipeline.programme.core import ContractError, sha
from pipeline.rule_admission import admitted
from pipeline import rule_promotion as promotion


def staged(tmp_path, name='fix'):
    source=tmp_path/(name+'.json');source.write_text(json.dumps(dict(rule_id=name)))
    return dict(source=source,path='123/'+name+'.json',
        evidence=dict(gate=dict(verdict='PASS',checks=dict(independent_fixture=True)),source_sha256=sha(source)))


def test_new_promotion_does_not_certify_or_hide_legacy_rules(tmp_path):
    base=tmp_path/'live';old=base/'456/old.json';old.parent.mkdir(parents=True);old.write_text('{}')
    item=staged(tmp_path)
    promotion.publish(base,[item])
    manifest=json.loads((base/'admission_manifest.json').read_text())
    assert manifest['format_version']==2
    assert manifest['entries']['456/old.json']['admission_status']=='legacy_unverified'
    assert admitted(old,base) and not admitted(old,base,allow_legacy=False)
    assert admitted(base/item['path'],base,allow_legacy=False)
    old.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='Legacy rule changed'):
        admitted(old,base)


def test_tampered_gate_or_rule_cannot_be_admitted(tmp_path):
    base=tmp_path/'live';item=staged(tmp_path)
    promotion.publish(base,[item])
    manifest=base/'admission_manifest.json'
    data=json.loads(manifest.read_text())
    data['entries'][item['path']]['evidence']['gate']['verdict']='FAIL'
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='no longer matches'):
        admitted(base/item['path'],base)


@pytest.mark.parametrize('change',['hash','gate','proposal','traversal','duplicate'])
def test_preflight_refuses_bad_publication_before_mutating_rules(tmp_path,change):
    base=tmp_path/'live';item=staged(tmp_path)
    if change=='hash': item['source'].write_text('{"changed":true}')
    if change=='gate': item['evidence']['gate']['verdict']='FAIL'
    if change=='proposal': item['path']='123/fix.proposed.json'
    if change=='traversal': item['path']='../escape.json'
    with pytest.raises(ContractError):
        promotion.publish(base,[item,item] if change=='duplicate' else [item])
    assert not list(base.rglob('*.json'))


def test_mid_commit_failure_rolls_back_entire_set_and_manifest(tmp_path,monkeypatch):
    base=tmp_path/'live';first=staged(tmp_path,'first');second=staged(tmp_path,'second')
    promotion.publish(base,[first])
    before=(base/'admission_manifest.json').read_bytes()
    first['source'].write_text('{"revised":true}');first['evidence']['source_sha256']=sha(first['source'])
    replace=os.replace
    def fail_second(source,target):
        if str(target).endswith('second.json'):
            # During a partial commit the loader cannot observe an admitted
            # subset, including a previously admitted rule.
            with pytest.raises(ContractError,match='requires recovery'):
                admitted(base/first['path'],base)
            raise OSError('Injected second-write failure')
        return replace(source,target)
    monkeypatch.setattr(promotion.os,'replace',fail_second)
    with pytest.raises(OSError,match='Injected'):
        promotion.publish(base,[first,second],allow_overwrite=True)
    assert (base/'admission_manifest.json').read_bytes()==before
    assert json.loads((base/first['path']).read_text())==dict(rule_id='first')
    assert not (base/second['path']).exists()
    assert admitted(base/first['path'],base)


def test_process_interruption_requires_explicit_recovery(tmp_path,monkeypatch):
    base=tmp_path/'live';first=staged(tmp_path,'first');second=staged(tmp_path,'second')
    replace=os.replace
    def interrupt(source,target):
        if str(target).endswith('second.json'): raise KeyboardInterrupt('Simulated process interruption')
        return replace(source,target)
    monkeypatch.setattr(promotion.os,'replace',interrupt)
    with pytest.raises(KeyboardInterrupt): promotion.publish(base,[first,second])
    with pytest.raises(ContractError,match='requires recovery'): admitted(base/first['path'],base)
    assert promotion.recover(base)=='prepared'
    assert not (base/first['path']).exists() and not (base/'admission_manifest.json').exists()


def test_recovery_refuses_unexpected_later_edits(tmp_path,monkeypatch):
    base=tmp_path/'live';first=staged(tmp_path,'first');second=staged(tmp_path,'second')
    replace=os.replace
    def interrupt(source,target):
        if str(target).endswith('second.json'): raise KeyboardInterrupt()
        return replace(source,target)
    monkeypatch.setattr(promotion.os,'replace',interrupt)
    with pytest.raises(KeyboardInterrupt): promotion.publish(base,[first,second])
    (base/first['path']).write_text('{"later_work":true}')
    with pytest.raises(ContractError,match='outside admission transaction'): promotion.recover(base)
    assert json.loads((base/first['path']).read_text())['later_work']
