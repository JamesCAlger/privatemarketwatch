import pandas as pd

from pipeline import entity_resolution as entities


def test_same_observations_choose_same_extraction_key_in_any_scan_order(tmp_path,monkeypatch):
    issuer='Alpha, Inc. and Beta, Inc., First lien loan 1'
    first='Alpha, Inc. and Beta, Inc.,  First lien loan 1'
    second='Alpha, Inc. and Beta, Inc., First lien loan 1'
    cache=tmp_path/'extractions.csv'
    pd.DataFrame([
        dict(bdc_investment_identifier=first,extracted_company_name='Alpha, Inc. and Beta, Inc.'),
        dict(bdc_investment_identifier=second,extracted_company_name='Alpha, Inc.')]).to_csv(cache,index=False)
    monkeypatch.setattr(entities,'IDENTIFIER_EXTRACTION_LOOKUP_FILE',cache)
    inputs=pd.DataFrame([
        dict(issuer_name=issuer,source='bdc',bdc_investment_identifier=identifier,cusip='',lei='')
        for identifier in [first,second,second]])
    # Equal-count variants also need a stable final GROUP BY order.
    inputs=pd.concat([inputs,pd.DataFrame([dict(issuer_name='Gamma, Inc.',source='nport',
        bdc_investment_identifier='',cusip='222',lei='B'),dict(issuer_name='Gamma, Inc.',source='nport',
        bdc_investment_identifier='',cusip='111',lei='A')])],ignore_index=True)
    outputs=[]
    for index,frame in enumerate([inputs,inputs.iloc[::-1],inputs.sample(frac=1,random_state=4)]):
        path=tmp_path/f'input{index}.csv';frame.to_csv(path,index=False)
        variants=entities._build_variant_table(path)
        outputs.append(entities._exact_dedup(variants))
    for output in outputs[1:]:pd.testing.assert_frame_equal(output,outputs[0])
    row=outputs[0].set_index('issuer_name').loc[issuer]
    assert row.bdc_investment_identifier==first
    assert row.canonical_name=='Alpha, Inc. and Beta, Inc.'


def test_equal_count_canonical_choice_is_stable_and_larger_count_still_wins():
    frame=pd.DataFrame([dict(extracted_name='Zeta Inc.',occurrence_count=2),
                        dict(extracted_name='ZETA INC.',occurrence_count=2)])
    assert entities._pick_canonical(frame)==entities._pick_canonical(frame.iloc[::-1])
    frame.loc[0,'occurrence_count']=3
    assert entities._pick_canonical(frame)=='Zeta Inc.'
