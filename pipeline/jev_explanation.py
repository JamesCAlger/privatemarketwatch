"""Deterministic investigation summaries, never invented model rationales."""
from decimal import Decimal

from pipeline.jev_bundles import decimal_text, number
from pipeline.jev_screening import fingerprint


def explain_receipt(bundle: dict, receipt: dict) -> dict:
    if receipt.get('bundle_fingerprint') != fingerprint(bundle):
        raise ValueError('Receipt belongs to a different bundle')
    if receipt.get('receipt_id') != fingerprint({k: v for k, v in receipt.items() if k != 'receipt_id'}):
        raise ValueError('Receipt changed after creation')
    if receipt.get('production_clearance_allowed') is not False or receipt.get('b1_work_suppressed') is not False:
        raise ValueError('Only isolated shadow receipts are supported')
    route = receipt['route']
    if route not in {'b1', 'pending', 'candidate_clearance'}:
        raise ValueError('Unknown shadow route')
    opening = {'b1': 'B1 review retained.', 'pending': 'Classification pending; B1 work retained.',
               'candidate_clearance': 'Shadow clearance candidate; B1 work retained.'}[route]
    model = receipt.get('model_result')
    model_bound = isinstance(model, dict) and model.get('bundle_fingerprint') == fingerprint(bundle)
    observed = model_bound and model.get('status') == 'success'
    comparisons, citation = [], None
    if observed:
        model_text = ('Recorded Jev answer: ' + str(model.get('decision')) +
                      '; provider decision/source confidence ' + str(model.get('decision_confidence')) +
                      '/' + str(model.get('source_confidence')) + '.')
        matches = [c for c in bundle['source_candidates'] if c['evidence_id'] == model.get('source_id')]
        if len(matches) == 1:
            candidate = matches[0]
            citation = {'source_path': bundle.get('filing', {}).get('path'),
                        'source_sha256': bundle.get('filing', {}).get('sha256'),
                        'evidence_id': candidate['evidence_id'], 'report_date': candidate.get('report_date'),
                        'note_markers': sorted({n['marker'] for n in candidate.get('notes', [])}),
                        'selection_basis': 'model_selected_not_independently_certified'}
            for field in bundle['rule']['fields']:
                value = candidate.get('source_values', {}).get(field, {})
                source, published = number(value.get('amount')), number(bundle['output_position'].get(field))
                unit = number(value.get('display_unit'))
                resolved = (source is not None and published is not None and unit is not None and unit > 0
                            and value.get('currency') == 'USD'
                            and bundle['output_position'].get(field + '_currency') == 'USD'
                            and not value.get('blocking_reasons'))
                comparisons.append({'field': field, 'published': decimal_text(published),
                    'selected_source': decimal_text(source), 'currency': value.get('currency'),
                    'display_unit': decimal_text(unit),
                    'agrees_at_display_precision': abs(published - source) <= unit / Decimal(2) if resolved else None})
    elif model is None:
        model_text = 'No model observation is recorded for this bundle.'
    elif not model_bound:
        model_text = 'Model observation is unavailable or not bound to this bundle; no source comparison is inferred.'
    else:
        model_text = 'Model observation status: ' + str(model.get('status')) + '.'
    reasons = list(receipt['reasons'])
    summary = opening + ' ' + model_text + ' Routing reasons: ' + ', '.join(reasons) + '.'
    for comparison in comparisons:
        agrees = comparison['agrees_at_display_precision']
        if agrees is None:
            summary += ' ' + comparison['field'] + ': numeric comparison unresolved.'
        else:
            summary += (' ' + comparison['field'] + ': output USD ' + comparison['published']
                        + ', model-selected source USD ' + comparison['selected_source']
                        + ('; agrees' if agrees else '; differs') + ' at displayed precision.')
    return {'schema_version': 'jev-factual-explanation.v1', 'summary': summary,
            'flag': receipt['flag'], 'receipt_id': receipt['receipt_id'],
            'bundle_fingerprint': receipt['bundle_fingerprint'], 'route': route, 'reasons': reasons,
            'comparisons': comparisons, 'selected_source_citation': citation,
            'holdings_sha256': bundle.get('provenance', {}).get('holdings_sha256'),
            'independent_review_fingerprint': receipt.get('independent_review_fingerprint'),
            'explanation_basis': 'Recorded routing facts and recomputed arithmetic; no model rationale inferred.',
            'production_clearance_allowed': False, 'b1_work_suppressed': False}
