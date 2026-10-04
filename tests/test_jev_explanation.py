import copy
import pytest

from pipeline.jev_explanation import explain_receipt
from pipeline.jev_screening import fingerprint


def inputs():
    bundle = {'rule': {'fields': ['cost']}, 'output_position': {'cost': '-1000', 'cost_currency': 'USD'},
              'filing': {'path': 'cached.html', 'sha256': 'source'}, 'provenance': {'holdings_sha256': 'holdings'},
              'source_candidates': [{'evidence_id': 't1r2', 'report_date': '2026-03-31', 'notes': [{'marker': '4'}],
                    'comparisons': {'cost': {'agrees_at_display_precision': False}},
                    'source_values': {'cost': {'amount': '-1000', 'currency': 'USD', 'display_unit': '1000'}}}]}
    receipt = {'bundle_fingerprint': fingerprint(bundle), 'route': 'b1', 'reasons': ['low_confidence'],
               'flag': {'row_id': 'ROW-1', 'rule_id': 'C107'}, 'production_clearance_allowed': False,
               'b1_work_suppressed': False, 'independent_review_fingerprint': None,
               'model_result': {'bundle_fingerprint': fingerprint(bundle), 'status': 'success',
                    'source_id': 't1r2', 'decision': 'false_alarm', 'decision_confidence': 0.88, 'source_confidence': 0.74}}
    receipt['receipt_id'] = fingerprint(receipt)
    return bundle, receipt


def resign(receipt):
    receipt['receipt_id'] = fingerprint({k: v for k, v in receipt.items() if k != 'receipt_id'})


def test_summary_distinguishes_answer_arithmetic_and_routing():
    bundle, receipt = inputs()
    result = explain_receipt(bundle, receipt)
    assert 'B1 review retained' in result['summary']
    assert 'false_alarm' in result['summary'] and 'low_confidence' in result['summary']
    assert result['comparisons'][0]['agrees_at_display_precision'] is True
    assert result['selected_source_citation']['note_markers'] == ['4']
    assert result['independent_review_fingerprint'] is None
    assert result['b1_work_suppressed'] is False


def test_changed_receipt_or_bundle_is_rejected():
    bundle, receipt = inputs()
    changed = copy.deepcopy(receipt)
    changed['reasons'] = ['invented_reason']
    with pytest.raises(ValueError, match='changed'):
        explain_receipt(bundle, changed)
    bundle['output_position']['cost'] = '-10000'
    with pytest.raises(ValueError, match='different bundle'):
        explain_receipt(bundle, receipt)


@pytest.mark.parametrize('choice', ['insufficient_evidence', 'nonexistent'])
def test_no_selected_source_means_no_invented_comparison(choice):
    bundle, receipt = inputs()
    receipt['model_result']['source_id'] = choice
    resign(receipt)
    result = explain_receipt(bundle, receipt)
    assert result['comparisons'] == []
    assert result['selected_source_citation'] is None


def test_unbound_model_answer_is_not_explained_as_current_evidence():
    bundle, receipt = inputs()
    receipt['model_result']['bundle_fingerprint'] = 'old'
    resign(receipt)
    result = explain_receipt(bundle, receipt)
    assert result['comparisons'] == []
    assert 'false_alarm' not in result['summary']


def test_pending_record_does_not_invent_provider_failure():
    bundle, receipt = inputs()
    receipt.update(model_result=None, route='pending', reasons=['not_submitted'])
    resign(receipt)
    assert 'No model observation' in explain_receipt(bundle, receipt)['summary']


def test_mismatching_amount_is_visible_even_when_model_says_false_alarm():
    bundle, receipt = inputs()
    bundle['output_position']['cost'] = '-4000'
    receipt['bundle_fingerprint'] = receipt['model_result']['bundle_fingerprint'] = fingerprint(bundle)
    resign(receipt)
    result = explain_receipt(bundle, receipt)
    assert result['comparisons'][0]['agrees_at_display_precision'] is False
    assert 'false_alarm' in result['summary'] and 'differs at displayed precision' in result['summary']


def test_unresolved_currency_is_not_presented_as_arithmetic_agreement():
    bundle, receipt = inputs()
    bundle['output_position']['cost_currency'] = None
    receipt['bundle_fingerprint'] = receipt['model_result']['bundle_fingerprint'] = fingerprint(bundle)
    resign(receipt)
    result = explain_receipt(bundle, receipt)
    assert result['comparisons'][0]['agrees_at_display_precision'] is None
    assert 'numeric comparison unresolved' in result['summary']
