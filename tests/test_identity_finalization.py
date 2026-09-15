import json

import pandas as pd

from pipeline.financial_conventions import prepare
from pipeline.identity_finalization import finish
from tests.test_financial_conventions import rows


def test_final_packet_assigns_proxy_after_identity_and_synchronizes_raw_rates(tmp_path):
    frame=rows(dict(row_id='A',report_date='2025-12-31',cost='0',fair_value='0',entity_id='E'),
        dict(row_id='B',report_date='2026-03-31',cost='',fair_value='110',entity_id='E'))
    prepared,states=prepare(frame)
    matches=pd.DataFrame([dict(cik='0000000123',source='bdc',position_id='P1',begin_report_date='2025-12-31',
        end_report_date='2026-03-31',begin_interest_rate='10',end_interest_rate='10',begin_cost='999',end_cost='999')])
    pd.DataFrame([dict(entity_id='E',issuer_name_variant='Acme')]).to_csv(tmp_path/'entity_lookup.csv',index=False)
    pd.DataFrame([dict(position_id='P1',edge_type='test')]).to_csv(tmp_path/'position_id_edges.csv',index=False)
    final,updated=finish(prepared,matches,states,directory=tmp_path,release_id='release',build_fingerprint='build')
    assert final.position_id.nunique()==1 and final.position_id.iloc[0]!='P1'
    assert final.entity_id.nunique()==1 and final.entity_id.iloc[0]!='E'
    assert final.cost.tolist()==[0,0]
    assert updated.iloc[0].begin_interest_rate==12 and updated.iloc[0].end_cost==0
    donor=pd.read_csv(tmp_path/'cost_donor_audit.csv').set_index('row_id').loc['B']
    assert donor.donor_row_id=='A' and donor.donor_release=='release'
    assert pd.read_csv(tmp_path/'entity_lookup.csv').iloc[0].entity_id==final.entity_id.iloc[0]
    assert pd.read_csv(tmp_path/'position_id_edges.csv').iloc[0].position_id==final.position_id.iloc[0]
    assert json.loads((tmp_path/'identity_contract.json').read_text())['financial_contract']=='financial-contract.v2'
