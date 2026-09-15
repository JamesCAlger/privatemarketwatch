import json

import duckdb
import pytest

from pipeline.delivery_coverage import build_census, load_history, metrics, verify_documents
from pipeline.output_schemas import OUTPUT_SCHEMAS
from pipeline.programme.core import ContractError, sha


CIK = '0000000123'
ACCESSION = '0000000123-26-000001'


def direct(row, field='fair_value', **changes):
    from pipeline.bdc_filings import CANONICAL_CONCEPT
    return dict(status='direct',release_id='R',row_id=row,field=field,accession_number=ACCESSION,
        source_sha256='a'*64,source_text='100',context_id='ctx',concept=CANONICAL_CONCEPT[field].lower(),unit='usd',
        href=f'/data/holdings_history/{CIK}/sources/{ACCESSION}-'+('a'*16)+'.html#evidence-'+('b'*24),**changes)


def observation(row, **changes):
    return {**dict.fromkeys(OUTPUT_SCHEMAS['private_markets_holdings.csv']),
        'row_id':row,'position_id':'P','cik':CIK,'report_date':'2026-03-31','source':'bdc',
        'src_context_id':'ctx','accession_number':ACCESSION,'fair_value':100,'cost_source':'reported',
        **changes}


def history(tmp_path, rows):
    root = tmp_path / 'history'
    fund = root / CIK
    fund.mkdir(parents=True)
    path = fund / '2026-03-31.json'
    path.write_text(json.dumps(dict(release_id='R',cik=CIK,quarter='2026-03-31',rows=rows)),encoding='utf-8')
    (fund / 'index.json').write_text(json.dumps(dict(release_id='R',cik=CIK,quarters=[
        dict(quarter='2026-03-31',path=CIK+'/2026-03-31.json',rows=len(rows),sha256=sha(path))])),encoding='utf-8')
    (root / 'manifest.json').write_text(json.dumps(dict(release_id='R',funds=[CIK],rows=len(rows))),encoding='utf-8')
    return root


def census(con, root):
    load_history(con, root)
    build_census(con, 'R')
    return metrics(con)


def test_complete_denominators_signed_zero_and_missing_links(tmp_path):
    root = history(tmp_path,[
        observation('r1',cost=50,evidence={'fair_value':direct('r1'),'cost':direct('r1','cost')}),
        observation('r2',fair_value=-5,cost=2,evidence={'fair_value':direct('r2')}),
        observation('r3',fair_value=0,evidence={'fair_value':direct('r3')})])
    with duckdb.connect() as con:
        result = census(con,root)
    overall = result['coverage'][0]
    assert overall['amount_abs_fv'] == 105
    assert overall['reported_amount_highlight_fv_coverage'] == 100/105
    assert overall['reported_numeric_highlight_row_coverage'] == 2/3
    assert overall['numeric_verdict'] == 'FAIL'
    assert len(result['coverage']) == 2


@pytest.mark.parametrize('change',[
    {'release_id':'other'},{'row_id':'other'},{'field':'cost'},
    {'context_id':'comparative'},{'accession_number':'0000000123-26-000002'},
    {'source_sha256':'c'*64},{'href':'https://example.invalid/number'},
    {'concept':'investmentcost'},{'unit':'eur'},
])
def test_stale_or_misleading_link_cannot_count_as_highlight(tmp_path,change):
    evidence = {**direct('r1'),**change}
    root = history(tmp_path,[observation('r1',evidence={'fair_value':evidence})])
    with duckdb.connect() as con:
        result = census(con,root)
    assert result['coverage'][0]['reported_numeric_highlight_row_coverage'] == 0
    assert result['coverage'][0]['reported_amount_highlight_fv_coverage'] == 0


def test_proxy_cost_does_not_hide_missing_reported_coupon(tmp_path):
    root = history(tmp_path,[observation('r1',cost=100,cost_source='first_observed_fv_proxy',
        interest_rate=12,evidence={'fair_value':direct('r1')})])
    with duckdb.connect() as con:
        result = census(con,root)
    assert result['coverage'][0]['reported_amount_highlight_fv_coverage'] == 1
    assert result['coverage'][0]['reported_numeric_highlight_row_coverage'] == 0
    cost = next(f for f in result['fields'] if f['quarter'] is None and f['field']=='cost')
    assert cost['reported_or_unknown'] == 0 and cost['populated'] == 1


@pytest.mark.parametrize('coupon,excluded',[(13,True),(14,False)])
def test_computed_coupon_is_distinct_from_reported_highlights_but_not_hidden(tmp_path,coupon,excluded):
    root = history(tmp_path,[observation('r1',interest_rate=coupon,interest_rate_reported=11,
        pik_rate=2,interest_rate_kind='cash',src_transforms='interest_rate:cash_plus_pik',
        evidence={'fair_value':direct('r1')})])
    with duckdb.connect() as con:
        result = census(con,root)
    rate = next(f for f in result['fields'] if f['quarter'] is None and f['field']=='interest_rate')
    assert rate['calculated_values'] == int(excluded)
    assert rate['reported_or_unknown'] == int(not excluded)
    assert rate['populated'] == 1 and rate['highlighted'] == 0
    assert result['coverage'][0]['reported_numeric_highlight_row_coverage'] == int(excluded)


@pytest.mark.parametrize('position,expected_errors',[('P',0),('another-tranche',1)])
def test_same_position_donor_and_zero_input(tmp_path,position,expected_errors):
    calc = dict(status='calculated',release_id='R',row_id='r2',field='cost',method='first_observed_fv_proxy',
        donor_row_id='r1',donor_release='R',donor_date='2026-03-31',input=direct('r1'))
    root = history(tmp_path,[observation('r1',fair_value=0,position_id=position),
        observation('r2',cost=0,cost_source='first_observed_fv_proxy',evidence={'cost':calc})])
    with duckdb.connect() as con:
        census(con,root)
        assert con.execute('SELECT count(*) FROM delivery_graph_errors').fetchone()[0] == expected_errors


def test_same_row_fv_can_support_cost_without_a_cycle(tmp_path):
    calc = dict(status='calculated',release_id='R',row_id='r1',field='cost',method='first_observed_fv_proxy',
        donor_row_id='r1',donor_release='R',donor_date='2026-03-31',input=direct('r1'))
    root = history(tmp_path,[observation('r1',cost=100,cost_source='first_observed_fv_proxy',
        evidence={'fair_value':direct('r1'),'cost':calc})])
    with duckdb.connect() as con:
        census(con,root)
        assert con.execute('SELECT count(*) FROM delivery_graph_errors').fetchone()[0] == 0


def test_no_positive_denominator_is_not_a_pass(tmp_path):
    root = history(tmp_path,[observation('r1',fair_value=0)])
    with duckdb.connect() as con:
        result = census(con,root)
    assert result['coverage'][0]['amount_verdict'] == 'UNASSESSABLE'
    assert result['coverage'][0]['numeric_rows'] == 1


def test_wider_download_fields_stay_visible_in_census(tmp_path):
    root = history(tmp_path,[observation('r1',principal_amount=1000,evidence={'fair_value':direct('r1')})])
    with duckdb.connect() as con:
        result = census(con,root)
    principal = next(f for f in result['fields'] if f['quarter'] is None and f['field']=='principal_amount')
    assert principal['reported_or_unknown'] == 1 and principal['highlighted'] == 0
    assert principal['displayed'] is False


def test_inferred_classification_is_not_a_reported_field(tmp_path):
    inference = dict(status='inferred',release_id='R',row_id='r1',field='gics_sub_industry',
        decision_id='D',model='fixture',input_text='Issuer description',taxonomy_sha256='c'*64)
    root = history(tmp_path,[observation('r1',gics_sub_industry='Application Software',
        evidence={'gics_sub_industry':inference})])
    with duckdb.connect() as con:
        result = census(con,root)
    field = next(f for f in result['fields'] if f['quarter'] is None and f['field']=='gics_sub_industry')
    assert field['inferred_values'] == 1 and field['reported_or_unknown'] == 0


def test_tampered_payload_is_rejected_before_measurement(tmp_path):
    root = history(tmp_path,[observation('r1')])
    with (root / CIK / '2026-03-31.json').open('a') as stream:
        stream.write(' ')
    with duckdb.connect() as con, pytest.raises(ContractError,match='changed history'):
        load_history(con,root)


def test_required_quarter_without_rows_is_reported_unassessable(tmp_path):
    root = history(tmp_path,[observation('r1')])
    path = root / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest.update(start='2025-12-31',end='2026-03-31')
    path.write_text(json.dumps(manifest),encoding='utf-8')
    with duckdb.connect() as con:
        result = census(con,root)
    empty = next(r for r in result['coverage'] if r['quarter']=='2025-12-31')
    assert empty['numeric_verdict'] == empty['amount_verdict'] == 'UNASSESSABLE'
    assert empty['holdings_rows'] == 0
    assert len(result['coverage']) == 3


def test_absent_source_inventory_prevents_link_credit(tmp_path):
    root = history(tmp_path,[observation('r1',evidence={'fair_value':direct('r1')})])
    (root / 'source_documents.json').write_text('[]',encoding='utf-8')
    out = tmp_path / 'requests'
    out.mkdir()
    with duckdb.connect() as con:
        load_history(con,root)
        build_census(con,'R')
        verify_documents(con,root,tmp_path/'cache',out)
        assert metrics(con)['coverage'][0]['reported_numeric_highlight_row_coverage'] == 0


@pytest.mark.parametrize('tamper',[False,True])
def test_pinned_document_inventory_creates_browser_requests_without_reading_html(tmp_path,tamper):
    cache = tmp_path / 'cache'
    source = cache / '123' / (ACCESSION.replace('-','')+'.html')
    source.parent.mkdir(parents=True)
    source.write_text('<html><body>100</body></html>',encoding='utf-8')
    digest = sha(source)
    filename = ACCESSION+'-'+digest[:16]+'.html'
    citation = {**direct('r1'),'source_sha256':digest,
        'href':f'/data/holdings_history/{CIK}/sources/{filename}#evidence-'+('b'*24)}
    root = history(tmp_path,[observation('r1',evidence={'fair_value':citation})])
    rendition = root / CIK / 'sources' / filename
    rendition.parent.mkdir()
    rendition.write_bytes(source.read_bytes())
    (root / 'source_documents.json').write_text(json.dumps([dict(cik=CIK,accession=ACCESSION,
        status='rendered',source_sha256=digest,rendition_sha256=sha(rendition))]),encoding='utf-8')
    out = tmp_path / 'requests'
    out.mkdir()
    if tamper:
        source.write_text('<html><body>Changed filing</body></html>',encoding='utf-8')
    with duckdb.connect() as con:
        load_history(con,root)
        build_census(con,'R')
        if tamper:
            with pytest.raises(ContractError,match='bytes differ'):
                verify_documents(con,root,cache,out)
        else:
            requests, _ = verify_documents(con,root,cache,out)
            assert len(requests) == 1
            assert json.loads((out / requests[0]['path']).read_text())[0]['href'] == citation['href']
            assert json.loads((out / requests[0]['path']).read_text())[0]['reference_count'] == 1
            result = metrics(con)
            assert result['coverage'][0]['reported_numeric_highlight_row_coverage'] == 1
            # This fixture intentionally has no anchor. Only the browser can
            # establish actual target availability; metadata is not DOM proof.
            assert 'until the complete browser anchor census passes' in result['interpretation']
