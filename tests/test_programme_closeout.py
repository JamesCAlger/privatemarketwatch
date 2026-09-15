from copy import deepcopy
import json
import shutil
import subprocess
import sys
import pytest

from scripts.programme_closeout.candidate import commit_bundle,read_bundle,fingerprint,safe_relative
from scripts.programme_closeout.identity import allocate,apply_decisions,cost_value
from scripts.programme_closeout.inventory_units import document_units
from scripts.programme_closeout.fx import convert
from scripts.programme_closeout.citation_viewer import resolve_cell,sanitize
from lxml import etree
from scripts.programme_closeout.acceptance import evaluate,zero_error_lower_bound,programme_verdict


def test_manifest_reuse_rejects_stale_inputs_and_tampered_data(tmp_path):
    (tmp_path/'data.csv').write_text('id,value\n1,0\n')
    commit_bundle(tmp_path,['data.csv'],'inputs-v1','fail')
    assert read_bundle(tmp_path,'inputs-v1')['quality']=='fail'
    with pytest.raises(ValueError,match='Stale'):read_bundle(tmp_path,'inputs-v2')
    (tmp_path/'data.csv').write_text('id,value\n1,9\n')
    with pytest.raises(ValueError,match='artifact'):read_bundle(tmp_path,'inputs-v1')


def test_partial_write_is_not_a_completed_bundle(tmp_path):
    (tmp_path/'data.csv').write_text('partial')
    with pytest.raises(FileNotFoundError):read_bundle(tmp_path,'v1')
    with pytest.raises(ValueError):commit_bundle(tmp_path,[],'v1','pass')


def test_restore_validates_whole_bundle_without_original_workspace(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'data.csv').write_text('id\n1\n')
    commit_bundle(source,['data.csv'],'v1','unassessable')
    restored=tmp_path/'restored';shutil.copytree(source,restored)
    assert read_bundle(restored,'v1')['quality']=='unassessable'
    (restored/'data.csv').unlink()
    with pytest.raises(ValueError):read_bundle(restored,'v1')


def test_bundle_rejects_path_escape_and_completed_overwrite(tmp_path):
    with pytest.raises(ValueError):safe_relative(tmp_path,'../escape')
    (tmp_path/'x').write_text('x');commit_bundle(tmp_path,['x'],'v1','pass')
    with pytest.raises(ValueError):commit_bundle(tmp_path,['x'],'v1','pass')


def test_literal_units_validate_namespace_and_composite(tmp_path):
    path=tmp_path/'units.xml'
    path.write_text('''<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:iso="http://www.xbrl.org/2003/iso4217" xmlns:fake="urn:fake">
      <unit id="opaque"><measure>iso:EUR</measure></unit>
      <unit id="usd"><measure>iso:USD</measure></unit>
      <unit id="false"><measure>fake:EUR</measure></unit>
      <unit id="ratio"><divide><unitNumerator><measure>iso:USD</measure></unitNumerator><unitDenominator><measure>shares</measure></unitDenominator></divide></unit>
    </xbrl>''')
    rows={r['unit_ref']:r for r in document_units(path)}
    assert rows['opaque']['currency']=='EUR'
    assert rows['usd']['currency']=='USD'
    assert rows['false']['currency']==''
    assert rows['ratio']['currency']==''


def create(name,scope='fund:1/parent'):
    return dict(decision_id=name,action='create',kind='position',scope=scope,evidence=['source:example'])


def assign(name,identity,anchors,scope='fund:1/parent'):
    return dict(decision_id=name,action='assign',kind='position',scope=scope,evidence=['source:example'],
                identity_id=identity,anchors=anchors)


def test_identity_reorder_addition_and_explicit_amendment_preserve_identity():
    d1=create('loan-created');d2=create('equity-created')
    first=apply_decisions({},[d1,d2])
    reversed_registry=apply_decisions({},[d2,d1])
    assert first['identities']==reversed_registry['identities']
    loan=allocate('position','loan-created','fund:1/parent')
    first=apply_decisions(first,[assign('initial',loan,['filing1:row1'])])
    added=apply_decisions(first,[create('new-loan'),assign('amendment',loan,['filing1-amended:row3'])])
    assert added['assignments']['filing1:row1']==added['assignments']['filing1-amended:row3']==loan
    assert apply_decisions(added,[d1])==added


def test_distinct_facilities_scopes_and_conflicting_assignments():
    first=apply_decisions({},[create('term'),create('revolver'),create('other-fund','fund:2/parent')])
    term=allocate('position','term','fund:1/parent');rev=allocate('position','revolver','fund:1/parent')
    first=apply_decisions(first,[assign('a',term,['q1:term']),assign('b',rev,['q1:revolver'])])
    assert len(set(first['assignments'].values()))==2
    with pytest.raises(ValueError):apply_decisions(first,[assign('bad',rev,['q1:term'])])
    with pytest.raises(ValueError):apply_decisions(first,[assign('bad-scope',term,['q1:x'],'fund:2/parent')])
    with pytest.raises(ValueError):apply_decisions(first,[dict(assign('bad-kind',term,['q1:x']),kind='entity')])


def test_explicit_split_and_merge_preserve_survivor_and_history():
    reg=apply_decisions({},[create('one'),create('two')])
    p1=allocate('position','one','fund:1/parent');p2=allocate('position','two','fund:1/parent')
    reg=apply_decisions(reg,[assign('initial',p1,['r1','r2'])])
    decision=dict(decision_id='split',action='split',kind='position',scope='fund:1/parent',evidence=['source:two facilities'],
                  assignments={'r2':p2})
    split=apply_decisions(reg,[decision])
    assert split['assignments']=={'r1':p1,'r2':p2}
    assert reg['assignments']=={'r1':p1,'r2':p1}
    merged=apply_decisions(split,[dict(decision,decision_id='merge',action='merge',assignments={'r2':p1},survivor=p1,retire=[p2])])
    assert merged['identities'][p2]['status']=='retired'
    with pytest.raises(ValueError):apply_decisions(merged,[assign('reuse',p2,['r3'])])


def test_cost_preserves_reported_zero_and_invalid_is_not_missing():
    obs=dict(cost_reported_state='reported',cost_reported=0)
    assert cost_value(obs,[])['value']=='0'
    obs['cost_reported_state']='currency_unresolved'
    assert cost_value(obs,[])['value'] is None


def test_cost_donor_is_identity_scope_safe_retains_zero_and_rejects_ties():
    obs=dict(cost_reported_state='not_disclosed',position_id='loan',position_status='established',scope='parent')
    donor=dict(position_id='loan',scope='parent',report_date='2023-03-31',source_anchor='r1',fair_value=0,
               fv_state='source_valid_USD',selected_source=True)
    other=dict(donor,scope='JV',fair_value=999,report_date='2022-12-31')
    assert cost_value(obs,[other,donor])['value']=='0'
    assert cost_value(obs,[donor,dict(donor,source_anchor='r2')])['method']=='ambiguous_earliest_donor'
    assert cost_value(dict(obs,position_status='provisional'),[donor])['value'] is None


def test_fx_cross_direction_weekend_zero_sign_and_no_lookahead():
    # Deliberately synthetic values, not market observations.
    q=dict(date='2023-03-31',usd_per_unit={'GBP':'1.5','EUR':'1.2'},quote_id='synthetic',source_sha256='fixture')
    future=dict(q,date='2023-04-03',quote_id='future',usd_per_unit={'GBP':'9','EUR':'9'})
    assert convert(80,'GBP','2023-04-02',[q,future])['value']=='120.0'
    assert convert(-80,'GBP','2023-04-02',[q])['value']=='-120.0'
    assert convert(0,'GBP','2023-04-02',[q])['value']=='0.0'
    assert convert(100,'EUR','2023-04-02',[q])['value']=='120.0'
    assert convert(100,'USD','2023-04-02',[])['method']=='already_USD'


def test_fx_missing_stale_conflicted_and_duplicate_are_not_assumed():
    q=dict(date='2023-03-31',usd_per_unit={'GBP':'1.5','EUR':'1.2'},quote_id='synthetic',source_sha256='fixture')
    assert convert(80,'GBP','2023-04-09',[q])['method']=='FX_stale'
    assert convert(80,'KPW','2023-04-02',[q])['method']=='FX_unavailable'
    with pytest.raises(ValueError):convert(80,'unresolved','2023-04-02',[q])
    with pytest.raises(ValueError):convert(80,'GBP','2023-04-02',[q,q])


def test_citation_rejects_wrong_row_value_and_ambiguous_duplicate():
    tree=etree.ElementTree(etree.fromstring('<html><body><table><tr><td><fact name="x:fairvalue">10</fact></td></tr><tr><td><fact name="x:fairvalue">10</fact></td></tr></table></body></html>'))
    fact,cell=resolve_cell(tree,'/html/body/table/tr[2]','fairvalue','10')
    assert tree.getpath(cell)=='/html/body/table/tr[2]/td'
    with pytest.raises(ValueError):resolve_cell(tree,'/html/body/table/tr','fairvalue','10')
    with pytest.raises(ValueError):resolve_cell(tree,'/html/body/table/tr[2]','fairvalue','11')
    with pytest.raises(ValueError):resolve_cell(tree,'/html/body/table/tr[3]','fairvalue','10')


def test_passive_rendition_removes_active_content_and_remote_links():
    tree=etree.ElementTree(etree.fromstring('<html><head/><body onload="bad()"><script>bad()</script><iframe src="https://example.com"/><a href="https://example.com">source</a><table><tr><td>10</td></tr></table></body></html>'))
    sanitize(tree)
    assert not tree.xpath('//script|//iframe|//*[@onload]|//a[@href]')
    assert tree.xpath('string(//td)')=='10'


def observation(**kw):
    return dict(dict(release_id='candidate',input_sha256='fixture',eligible=100,assessed=100,
        design='census',denominator_known=True,value=1),**kw)


def test_acceptance_unknown_denominator_or_unsupported_reference_never_passes():
    assert evaluate('sector_fv_coverage',observation(missing_weight=1))['status']=='UNASSESSABLE'
    assert evaluate('sector_accuracy',observation(requires_reference=True,independent_reference=False))['status']=='UNASSESSABLE'
    assert evaluate('sector_accuracy',observation(assessed=99))['status']=='UNASSESSABLE'
    assert evaluate('sector_accuracy',observation(eligible=0,assessed=0))['status']=='UNASSESSABLE'


def test_acceptance_perfect_small_sample_does_not_certify_high_accuracy():
    result=evaluate('amount_field_accuracy',observation(design='sample',design_id='synthetic-independent',
        interval_method='exact one-sided zero-error binomial',lower_95_bound=zero_error_lower_bound(30)))
    assert result['status']=='FAIL'
    assert zero_error_lower_bound(598)>=.995
    assert zero_error_lower_bound(597)<.995
    assert evaluate('amount_field_accuracy',observation(design='sample',design_id='clustered'))['status']=='UNASSESSABLE'


def test_acceptance_failure_cannot_be_hidden_by_missing_metrics():
    failed=evaluate('primary_absolute_error_ratio',observation(value=.01))
    unknown=evaluate('sector_accuracy',observation(denominator_known=False))
    assert programme_verdict([failed,unknown])=='FAIL_WITH_UNASSESSED_ITEMS'
    assert failed['approval']=='proposal_only'


def test_actual_child_guard_blocks_external_mutations_network_and_processes(tmp_path):
    run=subprocess.run([sys.executable,'-m','scripts.programme_closeout.guard_probe','--root',str(tmp_path/'allowed')],
                       capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)['outside_write']=='blocked'
    assert not (tmp_path/'guard_outside.txt').exists()
