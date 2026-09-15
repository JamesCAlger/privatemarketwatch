import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from pipeline.agent_promoted import load_promoted_corrections, apply_promoted_stage2_corrections
from pipeline.rule_admission import capture_inputs
from pipeline.programme.core import sha

ROOT=Path(__file__).resolve().parents[1]
RETIRED=ROOT/'data/overrides/agent_b2_corrections/0001911066/_retired_column_remap.json'


def test_retired_broad_remap_preserves_both_separate_source_positions(tmp_path):
    assert sha(RETIRED)=='1d18582390d9d2381a26dc7d16c91d7c7b4665c9df1b2fb7c6265869803a5702'
    folder=tmp_path/'corrections/0001911066';folder.mkdir(parents=True)
    shutil.copy2(RETIRED,folder/RETIRED.name)
    rows=pd.DataFrame([
        dict(cik='0001911066',source='bdc',report_date='2025-12-31',
            issuer_name='360 Holdco, Inc. (360 Training)',
            bdc_investment_identifier=identifier,cost=cost,fair_value=fv)
        for identifier,cost,fv in [('First Lien Debt',3918000,3902000),
                                  ('First Lien Debt (Delayed Draw)',0,-32000)]])
    @capture_inputs(lambda:tmp_path/'audit')
    def run():
        leaves=load_promoted_corrections(tmp_path/'corrections')
        assert leaves==[]
        result,audits=apply_promoted_stage2_corrections(rows,leaves)
        assert audits==[]
        return result
    result=run()
    from pipeline.correction_execution import KEY
    assert set(result.columns)-set(rows.columns)=={KEY}
    pd.testing.assert_frame_equal(result.drop(columns=[KEY]),rows)
    audit=pd.read_csv(tmp_path/'audit/input_admission_audit.csv')
    assert list(audit.admission_status)==['proposed_or_retired']
    assert list(audit.loaded)==[False]
    # Demonstrate the rejected mechanism, including its second-position spill.
    wrong,audits=apply_promoted_stage2_corrections(rows,[json.loads(RETIRED.read_text())])
    assert list(wrong.fair_value)==[3918000,0] and audits[0]['rows_changed']==2


@pytest.mark.needs_cache
def test_retired_remap_conflicts_with_exact_cached_source_values():
    from lxml import etree
    path=ROOT/'data/raw/filings/bdc_xbrl/1911066/000191106626000012.xml'
    if not path.is_file():pytest.skip('Cached filing unavailable')
    tree=etree.parse(str(path),etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    wanted={('c-499','InvestmentOwnedAtCost'):'3918000',('c-499','InvestmentOwnedAtFairValue'):'3902000',
            ('c-500','InvestmentOwnedAtCost'):'0',('c-500','InvestmentOwnedAtFairValue'):'-32000'}
    actual={(e.get('contextRef'),etree.QName(e).localname):e.text for e in tree.getroot()
        if e.get('contextRef') in ('c-499','c-500') and isinstance(e.tag,str)}
    assert {key:actual[key] for key in wanted}==wanted
