"""Describe a possible header continuation without changing parsed evidence."""
from copy import deepcopy
from datetime import date
import re

FIELDS = ('issuer', 'instrument', 'cost', 'fair_value')
CONCEPTS = {'investmentownedatcost': 'cost', 'investmentownedatfairvalue': 'fair_value'}


def inspect_header_continuation(parsed, table_index, *, cik, period):
    """Require matching adjacent headers and check all standard monetary facts.

    A positive result supports geometry investigation only. It never inherits
    headers, ownership, notes or source-selection authority into a bundle.
    """
    tables = parsed['tables']
    if not isinstance(table_index, int) or not 0 < table_index < len(tables) - 1:
        raise ValueError('Two adjacent source tables are required')
    if (not re.fullmatch(r'\d{1,10}', str(cik)) or int(cik) == 0
            or not isinstance(period, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', period)):
        raise ValueError('Explicit source entity and period required')
    date.fromisoformat(period)
    before, target, after = tables[table_index - 1:table_index + 2]
    blockers = []
    if [t['table_index'] for t in (before, target, after)] != [table_index - 1, table_index, table_index + 1]:
        raise ValueError('Noncanonical table coordinates')
    if target.get('headers'):
        blockers.append('target_already_has_headers')
    if any(t.get('unsupported_layout') for t in (before, target, after)):
        blockers.append('unsupported_geometry')
    if any(t.get('report_date') != period or t.get('period_evidence', {}).get('conflict')
           for t in (before, target, after)):
        blockers.append('unresolved_or_conflicting_table_period')
    if any(not all(f in t.get('headers', {}) for f in FIELDS) for t in (before, after)):
        blockers.append('missing_adjacent_header_fields')
    mapping = {f: deepcopy(before.get('headers', {}).get(f)) for f in FIELDS}
    for field in FIELDS:
        left, right = mapping[field], after.get('headers', {}).get(field)
        if left and right and any(left.get(k) != right.get(k) for k in ('column', 'span', 'text')):
            blockers.append('adjacent_header_disagreement')
        if any(h and h.get('hidden_source_content') for h in (left, right)):
            blockers.append('hidden_header_content')
    facts, counts = [], dict.fromkeys(('cost', 'fair_value'), 0)
    if len(target.get('rows', [])) > 10000:
        raise ValueError('Target row cap exceeded')
    for ri, row in enumerate(target.get('rows', [])):
        for cell in row:
            for fact in cell.get('inline_facts', []):
                field = CONCEPTS.get((fact.get('name') or '').split(':')[-1].lower())
                if not field:
                    continue
                if len(facts) >= 500:
                    raise ValueError('Monetary fact cap exceeded')
                counts[field] += 1
                header = mapping[field]
                aligned = bool(header and cell['column'] >= header['column']
                               and cell['column'] + cell['span'] <= header['column'] + header['span'])
                if not aligned:
                    blockers.append('monetary_fact_outside_proposed_column')
                context = parsed.get('contexts', {}).get(fact.get('context_id'))
                context_ok = bool(context and context.get('instant') == period
                    and str(context.get('entity_identifier', '')).lstrip('0') == str(cik).lstrip('0')
                    and not context.get('conflicting_definitions'))
                if not context_ok:
                    blockers.append('unresolved_or_conflicting_fact_context')
                if cell.get('hidden_source_content') or fact.get('unsupported_features'):
                    blockers.append('hidden_or_unsupported_fact')
                facts.append({'row_index': ri, 'column': cell['column'], 'span': cell['span'],
                              'field': field, 'aligned': aligned, 'context_agrees': context_ok,
                              'fact': deepcopy(fact)})
    if not all(counts.values()):
        blockers.append('missing_standard_monetary_field_facts')
    return {'schema_version': 'jev-header-continuation-probe.v1', 'table_index': table_index,
            'adjacent_tables': [table_index - 1, table_index + 1],
            'status': 'unresolved' if blockers else 'candidate_geometry_consistent',
            'blockers': sorted(set(blockers)), 'proposed_header_map': mapping,
            'monetary_fact_counts': counts, 'facts': facts,
            'headers_applied': False, 'ownership_scope_verified': False,
            'notes_complete': False, 'position_identity_verified': False,
            'limitation': 'Column and monetary local-name/context diagnostic only; not taxonomy validation. Adjacent tables and entity equality do not certify schedule ownership, sibling identity, notes, units or full evidence recall.'}
