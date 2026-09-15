from lxml import etree
from pipeline.history_bridge_evidence import bridge_cells


def test_bridge_anchors_distinguish_repeated_values_and_source_identity():
    tree=etree.ElementTree(etree.HTML('<table><tr><td>Acme</td><td>6/30/2030</td></tr>'
        '<tr><td>Other loan</td><td>6/30/2030</td></tr></table>'))
    record=dict(html_sha256='a'*64,table_index=0,row_index=0,maturity_date='2030-06-30',
        report_date='2026-03-31',raw_id_lower='acme')
    result=bridge_cells(tree,'a'*64,[record])
    assert len(result)==1 and result[0]['source_text']=='6/30/2030'
    assert tree.xpath('//tr')[0].xpath('.//td')[1].get('data-evidence-anchor')==result[0]['fragment']
    assert tree.xpath('//tr')[1].xpath('.//td')[1].get('data-evidence-anchor') is None
    assert bridge_cells(tree,'b'*64,[record])==[]
    assert bridge_cells(tree,'a'*64,[record],reference_tables=[[['Other','6/30/2030']]])==[]


def test_bridge_ambiguous_or_changed_maturity_has_no_link():
    tree=etree.ElementTree(etree.HTML('<table><tr><td>6/30/2030</td><td>6/30/2030</td></tr></table>'))
    record=dict(html_sha256='a'*64,table_index=0,row_index=0,maturity_date='2030-06-30',
        report_date='2026-03-31',raw_id_lower='acme')
    assert bridge_cells(tree,'a'*64,[record])==[]
    assert bridge_cells(tree,'a'*64,[{**record,'maturity_date':'2031-06-30'}])==[]


def test_bridge_export_binds_filing_period_identifier_and_value():
    import duckdb
    import pandas as pd
    from pipeline.history_bridge_evidence import attach
    markup='<table><tr><td>Acme</td><td>6/30/2030</td></tr></table>'
    tree=etree.ElementTree(etree.HTML(markup))
    base=dict(cik='0000000123',accession_number='0000000123-26-000001',report_date='2026-03-31',
        bdc_investment_identifier='Acme',maturity_date='2030-06-30',maturity_precision='day',
        src_field_overrides='maturity_date=bridge:aaaaaaaa:t0:r0',corrected_fields='')
    history=pd.DataFrame([{**base,'row_id':'good'}, {**base,'row_id':'prior','report_date':'2025-12-31'},
        {**base,'row_id':'other','bdc_investment_identifier':'Other'},
        {**base,'row_id':'amended','accession_number':'0000000123-26-000002'},
        {**base,'row_id':'changed','maturity_date':'2031-06-30'},
        {**base,'row_id':'corrected','corrected_fields':'maturity_date'}])
    bridges=pd.DataFrame([dict(cik='0000000123',accession_number=base['accession_number'],report_date=base['report_date'],
        html_sha256='a'*64,table_index=0,row_index=0,maturity_date='2030-06-30',raw_id_lower='acme')])
    with duckdb.connect() as con:
        con.register('history',history)
        con.execute('CREATE TABLE history_evidence(row_id VARCHAR,field VARCHAR,payload JSON)')
        attach(con,tree,bridges,cik='0000000123',accession=base['accession_number'],source_hash='a'*64,
            release_id='release',href='/sources/source.html#',raw_html=markup)
        assert con.execute('SELECT row_id,field FROM history_evidence').fetchall()==[('good','maturity_date')]
