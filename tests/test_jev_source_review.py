from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from scripts.review_jev_sources import context_fact_inventory, exact_context_facts, issuer_search_terms, review_source_path


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


def test_custom_exact_context_facts_keep_original_semantics_and_coordinates():
    soup = BeautifulSoup('<table><tr><td><ix:nonFraction name="filer:NetOfDiscount" contextRef="ctx" '
        'scale="3" sign="-">11</ix:nonFraction></td></tr></table>'
        '<ix:nonFraction name="us-gaap:InvestmentOwnedAtCost" contextRef="different">20</ix:nonFraction>', 'lxml')
    _, facts = exact_context_facts(soup, 'ctx')
    inventory = context_fact_inventory(facts, {id(soup.table): 4})
    assert len(inventory) == 1
    assert inventory[0]['concept'] == 'filer:NetOfDiscount'
    assert inventory[0]['attributes']['sign'] == '-'
    assert inventory[0]['table_index'] == 4
    assert inventory[0]['row_index'] == 0
    assert 'source_amount' not in inventory[0]


def test_unlocated_fact_keeps_nil_and_excluded_markup_without_claiming_a_row():
    soup = BeautifulSoup('<ix:nonFraction contextRef="ctx" xsi:nil="true">'
                         '1<ix:exclude>000</ix:exclude></ix:nonFraction>', 'lxml')
    _, facts = exact_context_facts(soup, 'ctx')
    item = context_fact_inventory(facts, {})[0]
    assert item['table_index'] is None and item['row_index'] is None
    assert item['attributes']['xsi:nil'] == 'true'
    assert '<ix:exclude>000</ix:exclude>' in item['html']


def test_context_inventory_refuses_excess_instead_of_silent_truncation():
    with pytest.raises(ValueError, match='inventory limit'):
        context_fact_inventory([None] * 201, {})


def test_context_inventory_refuses_oversized_markup():
    soup = BeautifulSoup('<ix:nonFraction contextRef="ctx">' + '1' * 20001 + '</ix:nonFraction>', 'lxml')
    _, facts = exact_context_facts(soup, 'ctx')
    with pytest.raises(ValueError, match='markup limit'):
        context_fact_inventory(facts, {})
