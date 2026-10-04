from bs4 import BeautifulSoup
import pytest

from pipeline.jev_explicit_notes import resolve_explicit_notes, IX, ARC


def html():
    return f'''<html xmlns:ix="{IX}"><body><table><tr><td>
    <ix:nonFraction id="f1" name="g:FairValue" contextRef="current">0</ix:nonFraction>
    </td></tr></table><div>(13) <ix:footnote id="n1">Current investments use unobservable valuation inputs.</ix:footnote></div>
    <div>(13) <ix:footnote id="n2">Comparative investments use different valuation inputs.</ix:footnote></div>
    <ix:relationship arcrole="{ARC}" fromRefs="f1" toRefs="n1"/>
    </body></html>'''


def inspect(text):
    return resolve_explicit_notes(BeautifulSoup(text, 'lxml'), ['f1'])['records'][0]


def test_explicit_link_keeps_comparative_note_separate_and_does_not_certify():
    soup = BeautifulSoup(html(), 'lxml')
    before = str(soup)
    result = resolve_explicit_notes(soup, ['f1'])
    record = result['records'][0]
    assert record['status'] == 'explicit_links_resolved'
    assert record['fact_context_id'] == 'current'
    assert [(n['note_id'], n['marker']) for n in record['notes']] == [('n1', '13')]
    assert not any(result[k] for k in ('notes_applied', 'notes_complete', 'period_scope_assigned',
                                     'position_identity_verified', 'production_clearance_enabled'))
    assert str(soup) == before


@pytest.mark.parametrize('old,new,reason', [
    ('id="f1"', 'id="other"', 'missing_or_duplicate_fact_id'),
    ('id="n2"', 'id="n1"', 'missing_or_duplicate_note_id'),
    ('toRefs="n1"', 'toRefs="missing"', 'missing_or_duplicate_note_id'),
    ('toRefs="n1"', 'toRefs=""', 'invalid_note_targets'),
    ('toRefs="n1"', 'toRefs="n1 n1"', 'invalid_note_targets'),
    ('fromRefs="f1"', 'fromRefs="other"', 'no_explicit_relationship'),
    (f'arcrole="{ARC}"', 'arcrole="custom"', 'unsupported_relationship'),
    ('toRefs="n1"', 'toRefs="n1" linkrole="custom"', 'unsupported_relationship'),
    ('id="n1"', 'id="n1" continuedAt="later"', 'unsupported_note_continuation'),
    ('id="n1"', 'id="n1" continuedAt=""', 'unsupported_note_continuation'),
    ('id="n1"', 'id="n1" footnoteRole="custom"', 'unsupported_note_element_or_role'),
    ('id="n1"', 'id="n1" style="display:none"', 'hidden_note'),
    ('id="f1"', 'id="f1" hidden', 'hidden_fact'),
    ('contextRef="current"', '', 'unsupported_fact_continuation_or_context'),
    ('id="f1"', 'id="f1" continuedAt="later"', 'unsupported_fact_continuation_or_context'),
    ('(13) <ix:footnote id="n1"', '<ix:footnote id="n1"', 'unresolved_numbered_note_container'),
    ('toRefs="n1"', 'toRefs="n1 n2"', 'conflicting_linked_note_text'),
    (f'xmlns:ix="{IX}"', 'xmlns:ix="urn:not-inline-xbrl"', 'unsupported_fact_element'),
])
def test_bad_or_unsupported_links_abstain(old, new, reason):
    result = inspect(html().replace(old, new))
    assert result['status'] == 'unresolved'
    assert reason in result['blockers']


def test_duplicate_fact_id_does_not_use_first_match():
    result = inspect(html().replace('</body>', '<div id="f1">other</div></body>'))
    assert 'missing_or_duplicate_fact_id' in result['blockers']


def test_namespace_alias_is_supported():
    result = inspect(html().replace('xmlns:ix=', 'xmlns:i=').replace('ix:', 'i:'))
    assert result['status'] == 'explicit_links_resolved'


def test_hidden_parent_note_abstains():
    result = inspect(html().replace('<div>(13)', '<div style="visibility:hidden">(13)', 1))
    assert 'hidden_note' in result['blockers']


def test_multi_note_container_is_not_inferred():
    text = html().replace('</ix:footnote></div>', '</ix:footnote>', 1).replace('<div>(13) <ix:footnote id="n2"', '(13) <ix:footnote id="n2"')
    assert 'unresolved_numbered_note_container' in inspect(text)['blockers']


def test_numbered_container_with_unrelated_text_is_not_inferred():
    text = html().replace('</ix:footnote></div>', '</ix:footnote> Unrelated disclosure.</div>', 1)
    assert 'unresolved_numbered_note_container' in inspect(text)['blockers']


def test_aliased_hidden_ancestor_is_refused():
    text = html().replace('xmlns:ix=', 'xmlns:i=').replace('ix:', 'i:')
    text = text.replace('<div>(13)', '<i:hidden><div>(13)', 1).replace('</i:footnote></div>', '</i:footnote></div></i:hidden>', 1)
    assert 'hidden_note' in inspect(text)['blockers']


def test_excluded_note_text_is_not_interpreted_as_the_fact_note():
    text = html().replace('Current investments', '<ix:exclude>Hidden instruction</ix:exclude> Current investments')
    assert 'unsupported_note_exclusion' in inspect(text)['blockers']


@pytest.mark.parametrize('ids', [[], ['f1', 'f1'], ['f1'] * 101, [''], 'f1'])
def test_invalid_selection_refused(ids):
    with pytest.raises(ValueError):
        resolve_explicit_notes(BeautifulSoup(html(), 'lxml'), ids)
