"""A cover amendment must not hide its same-quarter source schedule."""
from functools import partial
from pathlib import Path

import pytest

from pipeline.context_inventory import scan_instance
from pipeline.field_assessment import read_field_document
from scripts.run_context_census import scan_selected_source, verify_source_selection

CIK = '0001588272'
QUARTER = '2023-03-31'
ORIGINAL = '0001193125-23-000001'
AMENDED = '0001193125-23-000002'
OBLIGATION = dict(cik=CIK, report_date=QUARTER, positive_source_accession='')


def filing(accession, form, date, *, quarter=QUARTER):
    return dict(cik=CIK, report_date=quarter, filing_date=date, accession_number=accession, form_type=form)


def source(cache, accession, *, instant=QUARTER, document_end=QUARTER):
    path = cache / str(int(CIK)) / (accession.replace('-', '') + '.xml')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'''<x:xbrl xmlns:x="http://www.xbrl.org/2003/instance"
        xmlns:dei="http://xbrl.sec.gov/dei/2022" xmlns:gaap="http://fasb.org/us-gaap/2022">
        <x:context id="fund"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">{CIK}</x:identifier></x:entity>
        <x:period><x:instant>{instant}</x:instant></x:period></x:context>
        <dei:DocumentPeriodEndDate contextRef="fund">{document_end}</dei:DocumentPeriodEndDate>
        </x:xbrl>''', encoding='utf-8')
    return path


@pytest.fixture
def filings():
    return [filing(ORIGINAL, '10-Q', '2023-05-01'), filing(AMENDED, '10-Q/A', '2023-06-01')]


def test_cover_only_amendment_retains_primary_and_both_source_hashes(tmp_path, filings):
    source(tmp_path, ORIGINAL)
    source(tmp_path, AMENDED, instant='2023-05-25')
    result = scan_selected_source(OBLIGATION, filings + [filings[0]], cache_root=tmp_path)
    assert result['accession'] == ORIGINAL
    assert result['source_complete'] and result['target_instant_contexts'] == 1
    assert result['indexed_choices'] == 2
    assert [r['disposition'] for r in result['source_selection']] == [
        'amendment_without_target_instant', 'selected']
    assert all(r['sha256'] for r in result['source_selection'])
    verify_source_selection(result, cache_root=tmp_path)


def test_amendment_with_target_instant_is_authoritative(tmp_path, filings):
    source(tmp_path, ORIGINAL)
    source(tmp_path, AMENDED)
    result = scan_selected_source(OBLIGATION, filings, cache_root=tmp_path)
    assert result['accession'] == AMENDED
    assert len(result['source_selection']) == 1


@pytest.mark.parametrize('problem', ['missing', 'invalid', 'oversized', 'wrong_quarter', 'unknown_quarter'])
def test_unverified_amendment_cannot_be_bypassed(tmp_path, filings, problem):
    source(tmp_path, ORIGINAL)
    if problem != 'missing':
        path = source(tmp_path, AMENDED, instant='2023-05-25',
            document_end='2023-06-30' if problem == 'wrong_quarter' else '' if problem == 'unknown_quarter' else QUARTER)
        if problem == 'invalid':
            path.write_text('<broken', encoding='utf-8')
    scanner = partial(scan_instance, max_bytes=1) if problem == 'oversized' else scan_instance
    result = scan_selected_source(OBLIGATION, filings, cache_root=tmp_path, scanner=scanner)
    assert result['accession'] == AMENDED
    assert len(result['source_selection']) == 1


def test_later_comparative_cannot_supply_missing_primary(tmp_path):
    source(tmp_path, AMENDED, document_end='2023-06-30')
    result = scan_selected_source(OBLIGATION, [filing(AMENDED, '10-Q', '2023-08-01', quarter='2023-06-30')],
                                  cache_root=tmp_path)
    assert result['accession'] == '' and not result['source_complete']


def test_fallback_primary_must_prove_its_document_quarter(tmp_path, filings):
    source(tmp_path, ORIGINAL, document_end='2023-06-30')
    source(tmp_path, AMENDED, instant='2023-05-25')
    result = scan_selected_source(OBLIGATION, filings, cache_root=tmp_path)
    assert not result['source_complete']
    assert 'same primary economic quarter' in result['errors'][-1]


def test_different_form_family_does_not_supply_the_schedule(tmp_path, filings):
    source(tmp_path, ORIGINAL)
    source(tmp_path, AMENDED, instant='2023-05-25')
    filings[0]['form_type'] = '10-K'
    result = scan_selected_source(OBLIGATION, filings, cache_root=tmp_path)
    assert result['accession'] == AMENDED


def test_conflicting_duplicate_index_rows_reject(tmp_path, filings):
    with pytest.raises(ValueError, match='Conflicting filing metadata'):
        scan_selected_source(OBLIGATION, filings + [dict(filings[0], form_type='10-K')], cache_root=tmp_path)


@pytest.mark.parametrize('changed', [ORIGINAL, AMENDED])
def test_resume_rejects_changed_selected_or_skipped_source(tmp_path, filings, changed):
    source(tmp_path, ORIGINAL)
    source(tmp_path, AMENDED, instant='2023-05-25')
    result = scan_selected_source(OBLIGATION, filings, cache_root=tmp_path)
    source(tmp_path, changed, instant='2023-06-30')
    with pytest.raises(ValueError, match='Cached source changed'):
        verify_source_selection(result, cache_root=tmp_path)


def test_resume_rejects_newly_available_source(tmp_path, filings):
    result = scan_selected_source(OBLIGATION, filings, cache_root=tmp_path)
    verify_source_selection(result, cache_root=tmp_path)
    source(tmp_path, AMENDED)
    with pytest.raises(ValueError, match='newly available source'):
        verify_source_selection(result, cache_root=tmp_path)


def test_resume_rejects_injected_source_path(tmp_path, filings):
    source(tmp_path, AMENDED)
    result = scan_selected_source(OBLIGATION, filings, cache_root=tmp_path)
    result['source_selection'][0]['path'] = str(tmp_path / 'another.xml')
    with pytest.raises(ValueError, match='path does not match'):
        verify_source_selection(result, cache_root=tmp_path)


@pytest.mark.parametrize('changed', ['source_complete', 'source_sha256', 'selection'])
def test_resumed_frame_cannot_disagree_with_its_hashed_source_assessment(tmp_path, filings, monkeypatch, changed):
    import csv
    import json
    from pipeline.programme.core import sha
    from scripts import run_context_census as census
    from scripts.run_context_cohort_inventory import resume_source_assessments

    monkeypatch.setattr(census, 'ROOT', tmp_path)
    cache = tmp_path / 'data/raw/filings/bdc_xbrl'
    source(cache, AMENDED)
    result = scan_selected_source(OBLIGATION, filings, cache_root=cache)
    prior = tmp_path / 'prior'
    docs = prior / 'documents'
    docs.mkdir(parents=True)
    document = docs / 'source.json'
    document.write_text(json.dumps(result), encoding='utf-8')
    inputs = {'fixture': 'same-input'}
    (prior / 'request.json').write_text(json.dumps({'input_sha256': inputs}), encoding='utf-8')
    row = dict(cik=CIK, quarter=QUARTER, accession=AMENDED, source_complete='True',
        source_sha256=result['sha256'], selection=result['selection'], P=0, A=0, U=0,
        document=document.name, evidence_sha256=sha(document))
    row[changed] = 'False' if changed == 'source_complete' else 'different'
    with (prior / 'source_assessments.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    with pytest.raises(ValueError, match='assessment identity/count mismatch'):
        resume_source_assessments(prior, inputs, [OBLIGATION])


@pytest.mark.needs_cache
@pytest.mark.parametrize('cik,accession,quarter', [
    ('1803498', '000180349823000012', '2023-03-31'),
    ('1950803', '000119312526224111', '2026-03-31'),
])
def test_large_cached_instances_retain_context_and_field_assessability(cik, accession, quarter):
    path = Path(__file__).resolve().parents[1] / 'data/raw/filings/bdc_xbrl' / cik / (accession + '.xml')
    if not path.is_file():
        pytest.skip('Diagnosed large source not cached')
    contexts = scan_instance(path, cik, quarter)
    assert contexts['source_complete'], contexts['errors']
    assert contexts['target_instant_contexts'] > 0
    fields = read_field_document(path, cik)
    assert fields['complete'], fields['errors']
    assert fields['facts']
