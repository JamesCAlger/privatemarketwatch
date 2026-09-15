"""D08 retains cash and subsidiary observations independently of anchor totals."""
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from pipeline.agent_promoted import apply_promoted_rules,load_promoted_rules
from pipeline.correction_execution import KEY
from pipeline.programme.core import sha
from pipeline.rule_admission import capture_inputs

ROOT=Path(__file__).resolve().parents[1]
RETIRED={
    '1803498':'exclude_cash_from_investments_fv',
    '2011498':'exclude_nonconsolidated_subsidiary_lookthrough',
}


def test_retired_exclusions_preserve_cash_scopes_zero_values_and_other_positions(tmp_path):
    base=tmp_path/'rules'
    originals={}
    for cik,name in RETIRED.items():
        folder=ROOT/'data/overrides/agent_investigate_rules'/cik
        archive=folder/('_retired_'+name+'.json')
        review=folder/('_retired_'+name+'.review.json')
        evidence=json.loads(review.read_text(encoding='utf-8'))
        assert evidence['status']=='retired' and sha(archive)==evidence['original_sha256']
        target=base/cik;target.mkdir(parents=True)
        shutil.copy2(archive,target/archive.name)
        shutil.copy2(review,target/review.name)
        originals[cik.zfill(10)]=[json.loads(archive.read_text(encoding='utf-8'))]
    rows=pd.DataFrame([
        dict(cik=cik,source='bdc',report_date='2026-03-31',row_id=row,position_id=row,
             issuer_name=issuer,asset_category=category,fair_value=fv,cost=fv,
             is_subsidiary=sub,bdc_dimensions_raw=dimensions)
        for cik,row,issuer,category,fv,sub,dimensions in [
            ('0001803498','cash-parent','Fidelity Treasury Portfolio','CASH',6563000,0,'investmentidentifieraxis=Fidelity'),
            ('0001803498','cash-jv','Fidelity Treasury Portfolio','CASH',26219000,1,'nonconsolidatedsubsidiaryaxis=Emerald JV'),
            ('0002011498','parent-loan','Endor Purchaser, Inc.','DEBT',0,0,'investmentidentifieraxis=Endor'),
            ('0002011498','subsidiary-loan','Endor Purchaser, Inc.','DEBT',0,1,'investmentcompanynonconsolidatedsubsidiaryaxis=AGL EPCI I'),
            ('0002011498','ordinary-loan','Subsidiary Holdings LLC','DEBT',100,0,'investmentidentifieraxis=Subsidiary Holdings LLC'),
            ('0000000123','other-fund-cash','Fidelity Treasury Portfolio','CASH',200,0,'investmentidentifieraxis=Fidelity'),
        ]])
    @capture_inputs(lambda:tmp_path/'audit')
    def run():
        rules=load_promoted_rules(base)
        assert rules=={}
        result,audits=apply_promoted_rules(rows,rules)
        assert audits==[]
        return result
    result=run()
    assert set(result.columns)-set(rows.columns)=={KEY}
    pd.testing.assert_frame_equal(result.drop(columns=KEY),rows)
    audit=pd.read_csv(tmp_path/'audit/input_admission_audit.csv')
    assert len(audit)==4 and set(audit.admission_status)=={'proposed_or_retired'}
    assert not audit.loaded.any()
    # Replaying the exact old rules exposes the D08 conflict, while ordinary
    # borrower-name text and another fund remain outside their predicates.
    old,_=apply_promoted_rules(rows,originals)
    assert set(old.row_id)=={'parent-loan','ordinary-loan','other-fund-cash'}


@pytest.mark.needs_cache
@pytest.mark.parametrize('relative,expected',[
    ('data/raw/filings/bdc_xbrl/1803498/000180349826000031.xml',{
        'c-1427':'6563000','c-1428':'10440000','c-1429':'636726000',
        'c-6033':'377000','c-6034':'26219000','c-6946':'1050000'}),
    ('data/raw/filings/bdc_xbrl/2011498/000119312526214378.xml',{
        'C_08f6f9c3-4851-4570-a607-efbcf43c4e73':'7425000',
        'C_0971f54c-80b4-49d5-8a5e-99055eb4949c':'0'}),
])
def test_retained_records_have_exact_cached_usd_facts(relative,expected):
    from lxml import etree
    from pipeline.monetary_units import XBRLI,unit_definition
    path=ROOT/relative
    if not path.is_file():pytest.skip('Cached source unavailable')
    before=sha(path)
    tree=etree.parse(str(path),etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,huge_tree=True))
    assert not tree.docinfo.doctype
    units={u.get('id'):unit_definition(u) for u in tree.findall('{'+XBRLI+'}unit')}
    found={}
    for node in tree.getroot():
        if (isinstance(node.tag,str) and node.tag.rsplit('}',1)[-1]=='InvestmentOwnedAtFairValue'
                and node.get('contextRef') in expected):
            assert units[node.get('unitRef')]==dict(unit_kind='monetary',currency='USD')
            assert node.get('contextRef') not in found
            found[node.get('contextRef')]=node.text
    assert found==expected and sha(path)==before
