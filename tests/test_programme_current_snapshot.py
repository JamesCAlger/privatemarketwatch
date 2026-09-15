"""A repair candidate freezes current code without changing its source data."""
from pipeline.programme import runner
from pipeline.programme.core import atomic_json,digest,read_json,record,sha


def test_current_snapshot_includes_repairs_new_modules_and_schema(tmp_path,monkeypatch):
    root=tmp_path/"repo";root.mkdir()
    base=root/"base";frozen=base/"frozen";frozen.mkdir(parents=True)
    original={"pipeline/old.py":"old implementation","pipeline/removed.py":"removed",
        "schemas/a.json":"old schema","data/output/input.csv":"cik,value\n123,7\n"}
    import json
    from tests.test_agent_rule import _rule
    rule_name='data/overrides/agent_investigate_rules/1377936/reviewed.json'
    original[rule_name]=json.dumps(_rule())
    for name,body in original.items():
        path=frozen/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
    records=[record(frozen,name) for name in original]
    atomic_json(base/"snapshot.json",dict(artifacts=records,input_fingerprint=digest(records)))
    atomic_json(base/"snapshot_complete.json",dict(manifest_sha256=sha(base/"snapshot.json")))
    current={"pipeline/old.py":"repaired implementation","pipeline/new.py":"new finalizer",
        "schemas/a.json":"new schema","scripts/build.py":"current build",
        "data/reference/quarter_acceptance_programme_thresholds.json":"{}",
        "requirements-programme-windows.txt":"fixture"}
    current[rule_name]=json.dumps(_rule(rationale='Source-reviewed amendment'))
    for name,body in current.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
    monkeypatch.setattr(runner,"ROOT",root)
    monkeypatch.setattr(runner.native,"runtime_identity",lambda **kwargs:dict(runtime="fixture"))
    candidate=root/"candidate"
    runner.snapshot(candidate,base,current_code=True,rule_inputs=[root/rule_name])
    assert (candidate/"frozen/pipeline/old.py").read_text()=="repaired implementation"
    assert (candidate/"frozen/pipeline/new.py").is_file()
    assert not (candidate/"frozen/pipeline/removed.py").exists()
    assert (candidate/"frozen/data/output/input.csv").read_text()==original["data/output/input.csv"]
    assert (frozen/"pipeline/old.py").read_text()=="old implementation"
    assert read_json(candidate/"snapshot.json")["current_code"] is True
    assert read_json(candidate/'frozen'/rule_name)['rationale']=='Source-reviewed amendment'
    assert (frozen/rule_name).read_text()==original[rule_name]
    runner.verify_snapshot(candidate)


def test_snapshot_applies_reviewed_retirement_without_changing_base(tmp_path,monkeypatch):
    import json
    root=tmp_path/'repo';root.mkdir()
    base=root/'base';frozen=base/'frozen'
    relative='data/overrides/agent_b2_corrections/123'
    old=frozen/relative/'column_remap.json'
    old.parent.mkdir(parents=True);old.write_text('{"original":true}')
    original_sha=sha(old)
    records=[record(frozen,old.relative_to(frozen).as_posix())]
    atomic_json(base/'snapshot.json',dict(artifacts=records,input_fingerprint=digest(records)))
    atomic_json(base/'snapshot_complete.json',dict(manifest_sha256=sha(base/'snapshot.json')))
    archive=root/relative/'_retired_column_remap.json'
    archive.parent.mkdir(parents=True);archive.write_bytes(old.read_bytes())
    source=root/'source.xml';source.write_text('<evidenced-source/>')
    review=archive.with_name('_retired_column_remap.review.json')
    review.write_text(json.dumps(dict(status='retired',mechanism='Source contradicts correction',
        previous_file=old.name,original_file=archive.name,original_sha256=original_sha,
        sources=[dict(path='source.xml',sha256=sha(source))])))
    threshold=root/'data/reference/quarter_acceptance_programme_thresholds.json'
    threshold.parent.mkdir(parents=True);threshold.write_text('{}')
    (root/'requirements-programme-windows.txt').write_text('fixture')
    monkeypatch.setattr(runner,'ROOT',root)
    monkeypatch.setattr(runner.native,'runtime_identity',lambda **kwargs:dict(runtime='fixture'))
    candidate=root/'candidate'
    runner.snapshot(candidate,base,current_code=True,retired_rules=[review])
    assert sha(old)==original_sha
    assert not (candidate/'frozen'/relative/old.name).exists()
    assert sha(candidate/'frozen'/relative/archive.name)==original_sha
    assert sha(candidate/'frozen'/relative/review.name)==sha(review)
    overlays=read_json(candidate/'snapshot.json')['code_overlay']
    assert any(item.get('retired_path')==old.relative_to(frozen).as_posix() for item in overlays)
    runner.verify_snapshot(candidate)
