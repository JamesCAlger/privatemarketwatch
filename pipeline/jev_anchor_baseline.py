"""Context-anchor comparator for shadow evaluation, never an audit/clearance.

Unlike the numeric baseline with a reviewed source ID, this selects a candidate
without a reference label or model answer. It still shares builder evidence and
the pipeline's context provenance, so it cannot certify independent identity,
candidate recall, owner scope or note completeness.
"""
from pipeline.jev_bundles import clean, number


def compare_context_anchor(bundle):
    result = {'method': 'context-anchor.v2', 'status': 'unresolved', 'source_id': None,
              'reasons': [], 'production_clearance_allowed': False,
              'independent_identity_verified': False}
    output = bundle.get('output_position', {})
    if bundle.get('evidence_status', {}).get('status') != 'ready_for_model':
        result['reasons'].append('bundle_blocked')
        return result
    context_id = output.get('src_context_id')
    identifier = clean(output.get('bdc_investment_identifier'))
    if not context_id or not identifier:
        result['reasons'].append('missing_context_anchor')
        return result
    matches = [c for c in bundle['source_candidates']
               if context_id in c.get('identity_evidence', {}).get('contexts', {})]
    if len(matches) != 1:
        result['reasons'].append('context_anchor_not_unique')
        return result
    candidate = matches[0]
    identity = candidate['identity_evidence']
    context = identity['contexts'][context_id]
    result['source_id'] = candidate['evidence_id']
    if (candidate.get('blocking_reasons') or identity.get('blocking_reasons')
            or identity.get('output_class_compatible') is False
            or identity.get('output_instrument_compatible') is False):
        result['reasons'].append('source_evidence_conflict')
    if (context.get('instant') != output.get('report_date')
            or candidate.get('report_date') != output.get('report_date')
            or candidate.get('period_evidence', {}).get('conflict')):
        result['reasons'].append('period_conflict')
    if clean(context.get('entity_identifier')).lstrip('0') != clean(output.get('cik')).lstrip('0'):
        result['reasons'].append('entity_conflict')
    dimensions = context.get('dimensions', [])
    # No claim that context equality resolves additional owner/JV dimensions.
    if (len(dimensions) != 1 or dimensions[0].get('axis', '').split(':')[-1] != 'InvestmentIdentifierAxis'
            or clean(dimensions[0].get('text')) != identifier):
        result['reasons'].append('identifier_or_scope_not_exact')
    if result['reasons']:
        return result
    comparisons = {}
    for field in bundle['rule']['fields']:
        value = candidate['source_values'].get(field, {})
        source, published, unit = number(value.get('amount')), number(output.get(field)), number(value.get('display_unit'))
        if None in (source, published, unit) or unit <= 0 or value.get('currency') != 'USD':
            result['reasons'].append('unresolved_value:' + field)
            continue
        comparisons[field] = abs(source - published) <= unit / 2
    result['comparisons'] = comparisons
    if not result['reasons']:
        result['status'] = 'anchor_consistent' if all(comparisons.values()) else 'anchor_mismatch'
    return result
