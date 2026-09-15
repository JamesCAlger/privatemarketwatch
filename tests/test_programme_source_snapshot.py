from pipeline.programme.source_snapshot import include_sources


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
