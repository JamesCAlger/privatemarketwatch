import copy
import pytest
from pipeline.jev_anchor_baseline import compare_context_anchor


@pytest.fixture
def packet():
    return {'evidence_status': {'status': 'ready_for_model'}, 'rule': {'fields': ['cost']},
            'output_position': {'src_context_id': 'ctx', 'cik': '0000000001', 'report_date': '2026-03-31',
                                'bdc_investment_identifier': 'Acme First Lien Revolver', 'cost': '-1000'},
            'source_candidates': [{'evidence_id': 't0r1', 'report_date': '2026-03-31',
                'identity_evidence': {'contexts': {'ctx': {'instant': '2026-03-31', 'entity_identifier': '1',
                    'dimensions': [{'axis': 'us-gaap:InvestmentIdentifierAxis', 'text': 'Acme First Lien Revolver'}]}}},
                'source_values': {'cost': {'amount': '-1000', 'display_unit': '1000', 'currency': 'USD'}}}]}


def test_selects_without_reference_or_model_and_never_certifies(packet):
    observed = compare_context_anchor(packet)
    assert observed['status'] == 'anchor_consistent'
    assert observed['source_id'] == 't0r1'
    assert not observed['production_clearance_allowed']
    assert not observed['independent_identity_verified']


@pytest.mark.parametrize('change', ['duplicate', 'identifier', 'period', 'scope', 'class', 'instrument', 'blocked'])
def test_conflicts_or_ambiguous_anchor_remain_unresolved(packet, change):
    candidate = packet['source_candidates'][0]
    context = candidate['identity_evidence']['contexts']['ctx']
    if change == 'duplicate':
        packet['source_candidates'].append(copy.deepcopy(candidate))
    elif change == 'identifier':
        context['dimensions'][0]['text'] = 'Other tranche'
    elif change == 'period':
        context['instant'] = '2025-12-31'
    elif change == 'scope':
        context['dimensions'].append({'axis': 'OwnerAxis', 'text': 'JV'})
    elif change == 'class':
        candidate['identity_evidence']['output_class_compatible'] = False
    elif change == 'instrument':
        candidate['identity_evidence']['output_instrument_compatible'] = False
    else:
        packet['evidence_status']['status'] = 'blocked'
    assert compare_context_anchor(packet)['status'] == 'unresolved'


def test_value_change_cannot_select_a_different_candidate(packet):
    packet['output_position']['cost'] = '-9000'
    other = copy.deepcopy(packet['source_candidates'][0])
    other['evidence_id'] = 't0r2'
    other['identity_evidence']['contexts']['other'] = other['identity_evidence']['contexts'].pop('ctx')
    other['source_values']['cost']['amount'] = '-9000'
    packet['source_candidates'].append(other)
    result = compare_context_anchor(packet)
    assert result['source_id'] == 't0r1'
    assert result['status'] == 'anchor_mismatch'
