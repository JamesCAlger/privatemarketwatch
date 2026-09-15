from pipeline.programme.source_snapshot import include_sources
from pipeline.programme.source_snapshot import freeze_refresh_support
from pipeline.programme.core import ContractError,sha
import pytest


def test_unlocatable_observations_are_audited_without_constructing_paths(tmp_path):
    root=tmp_path/'root';frozen=tmp_path/'frozen'
    output=frozen/'data/output';output.mkdir(parents=True)
    holdings=output/'private_markets_holdings.csv'
    holdings.write_text('cik,source,report_date,accession_number\n'
        '0000000123,bdc,2026-03-31,\n'
        '0000000123,bdc,2026-03-31,../../secret\n'
        '0000000123,bdc,2026-03-31,0000000123-26-000001\n')
    source=root/'data/raw/filings/bdc_html/123/000000012326000001.html'
    source.parent.mkdir(parents=True);source.write_text('<html>cached</html>')
    records=include_sources(root,frozen)
    unlocatable=[r for r in records if 'reason' in r]
    assert len(unlocatable)==2 and all(r['status']=='unavailable' and r['rows']==1 for r in unlocatable)
    assert len([r for r in records if r['status']=='frozen'])==1
    assert (frozen/source.relative_to(root)).read_text()=='<html>cached</html>'
    assert len(holdings.read_text().splitlines())==4


def test_raw_bdc_unit_documents_are_frozen_outside_public_history(tmp_path):
    root=tmp_path/'root';frozen=tmp_path/'frozen'
    output=frozen/'data/output';output.mkdir(parents=True)
    (output/'bdc_holdings.csv').write_text('cik,accession_number\n0000000123,0000000123-19-000001\n')
    relative='data/raw/filings/bdc_xbrl/123/000000012319000001.xml'
    source=root/relative;source.parent.mkdir(parents=True);source.write_text('<cached-units/>')
    records=include_sources(root,frozen)
    assert (frozen/relative).read_bytes()==source.read_bytes()
    record=next(r for r in records if r.get('path')==relative)
    assert record['status']=='frozen' and len(record['sha256'])==64


def test_every_diagnosed_refresh_accession_is_frozen_when_cached(tmp_path):
    from pipeline.programme.source_refresh import REFRESHES
    root=tmp_path/'root';frozen=tmp_path/'frozen'
    (frozen/'data/output').mkdir(parents=True)
    expected=[]
    for entry in REFRESHES:
        relative='data/raw/filings/bdc_xbrl/'+entry['cik']+'/'+entry['accession'].replace('-','')+'.xml'
        source=root/relative;source.parent.mkdir(parents=True,exist_ok=True);source.write_text('<instance/>')
        expected.append(relative)
    records=include_sources(root,frozen)
    for relative in expected:
        record=next(r for r in records if r.get('path')==relative)
        assert record['status']=='frozen' and (frozen/relative).is_file()


def test_reviewed_wrapper_replaces_only_its_older_candidate_copy(tmp_path):
    relative='data/overrides/bdc_xbrl_wrappers/0000000123.json'
    root=tmp_path/'root';frozen=tmp_path/'frozen'
    source=root/relative;source.parent.mkdir(parents=True);source.write_text('{"version":2}')
    prior=frozen/relative;prior.parent.mkdir(parents=True);prior.write_text('{"version":1}')
    unrelated=prior.with_name('0000000456.json');unrelated.write_text('retained old wrapper')
    entry=dict(path=relative,sha256=sha(source),reason='Reviewed wrapper repair')
    records=freeze_refresh_support(root,frozen,support_files=[entry])
    assert prior.read_bytes()==source.read_bytes()
    assert unrelated.read_text()=='retained old wrapper'
    assert records[0]['sha256']==entry['sha256']
    assert records[0]['role']=='reviewed diagnosed-refresh support'


@pytest.mark.parametrize('changed',[False,True])
def test_missing_or_changed_wrapper_cannot_overwrite_frozen_input(tmp_path,changed):
    relative='data/overrides/bdc_xbrl_wrappers/0000000123.json'
    root=tmp_path/'root';root.mkdir();frozen=tmp_path/'frozen'
    prior=frozen/relative;prior.parent.mkdir(parents=True);prior.write_text('preserve')
    if changed:
        source=root/relative;source.parent.mkdir(parents=True);source.write_text('changed')
    with pytest.raises(ContractError):
        freeze_refresh_support(root,frozen,support_files=[dict(path=relative,sha256='0'*64,reason='review')])
    assert prior.read_text()=='preserve'


@pytest.mark.parametrize('relative',[
    '../outside.json','data/overrides/bdc_xbrl_wrappers/../../outside.json',
    'data/overrides/agent_b2_corrections/0000000123.json',
])
def test_refresh_support_is_limited_to_explicit_wrapper_paths(tmp_path,relative):
    with pytest.raises(ContractError,match='Invalid'):
        freeze_refresh_support(tmp_path,support_files=[dict(path=relative,sha256='0'*64,reason='review')])


def test_all_support_is_verified_before_any_wrapper_is_overwritten(tmp_path):
    root=tmp_path/'root';frozen=tmp_path/'frozen'
    relative='data/overrides/bdc_xbrl_wrappers/0000000123.json'
    source=root/relative;source.parent.mkdir(parents=True);source.write_text('new')
    prior=frozen/relative;prior.parent.mkdir(parents=True);prior.write_text('old')
    entry=dict(path=relative,sha256=sha(source),reason='review')
    with pytest.raises(ContractError,match='repeated'):
        freeze_refresh_support(root,frozen,support_files=[entry,entry])
    assert prior.read_text()=='old'


@pytest.mark.needs_cache
def test_registered_refresh_support_matches_reviewed_cached_wrapper():
    from pipeline import config
    from pipeline.programme.source_refresh import REFRESH_SUPPORT
    records=freeze_refresh_support(config.PROJECT_ROOT)
    assert len(records)==len(REFRESH_SUPPORT)==2
    assert records[0]['path'].endswith('/0002008748.json')
    assert records[1]['path'].endswith('/unlisted_bdc_xbrl_reference.json')


def test_wrapper_version_reference_is_an_explicit_pinned_dependency(tmp_path):
    relative='data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json'
    source=tmp_path/'root'/relative;source.parent.mkdir(parents=True);source.write_text('{"cohort":"unchanged"}')
    entry=dict(path=relative,sha256=sha(source),reason='Reviewed version metadata')
    frozen=tmp_path/'frozen'
    freeze_refresh_support(tmp_path/'root',frozen,support_files=[entry])
    assert (frozen/relative).read_bytes()==source.read_bytes()
