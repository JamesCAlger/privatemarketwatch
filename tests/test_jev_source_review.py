from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from scripts.review_jev_sources import exact_context_facts, issuer_search_terms, review_source_path


def test_blocked_packet_can_locate_exact_cached_accession(tmp_path):
    packet = {'output_position': {'cik': '0000000123', 'accession_number': '0000000123-26-000001'}}
    assert review_source_path(tmp_path, packet) == (tmp_path / 'data/raw/filings/bdc_html/123/000000012326000001.html').resolve()


def test_declared_review_source_cannot_escape_cache(tmp_path):
    with pytest.raises(ValueError, match='cached BDC'):
        review_source_path(tmp_path, {'filing': {'path': str(tmp_path / 'outside.html')}})


@pytest.mark.parametrize('accession', ['../../outside', None, '123'])
def test_invalid_accession_cannot_form_a_review_path(tmp_path, accession):
    with pytest.raises(ValueError, match='source identity'):
        review_source_path(tmp_path, {'output_position': {'cik': '123', 'accession_number': accession}})


@pytest.mark.parametrize('identifier', [None, '', ' '])
def test_missing_context_does_not_match_unlabelled_document_elements(identifier):
    soup = BeautifulSoup('<html><ix:nonFraction name="cost">999</ix:nonFraction></html>', 'lxml')
    assert exact_context_facts(soup, identifier) == (None, [])


def test_context_search_is_exact():
    soup = BeautifulSoup('<div id="ctx">Selected</div><ix:nonFraction contextRef="ctx">1</ix:nonFraction>'
                         '<ix:nonFraction contextRef="ctx2">2</ix:nonFraction>', 'lxml')
    context, facts = exact_context_facts(soup, 'ctx')
    assert context.text == 'Selected'
    assert [f.text for f in facts] == ['1']


@pytest.mark.parametrize('value', [None, '', '   ', float('nan')])
def test_missing_issuer_has_no_wildcard_or_literal_none_search(value):
    assert issuer_search_terms(value) == ('', [])


def test_visible_issuer_search_still_normalizes_real_names():
    assert issuer_search_terms(' LTC   Ally Inc. ') == ('ltc ally inc.', ['ltc', 'ally'])
