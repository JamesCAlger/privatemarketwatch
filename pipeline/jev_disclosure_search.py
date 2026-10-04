"""Bounded table navigation across disclosure roles, never position adjudication."""
from collections import Counter
from copy import deepcopy
import re
import unicodedata

from pipeline.jev_disclosure_role import table_disclosure_role


def _tokens(value):
    return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', value).casefold())


def anchor_issuer_seeds(search):
    """Read a separate issuer column at exact-context anchors, without name repair.

    Combined investment descriptions and unknown headers cannot supply a seed.
    Returned source text is only a query, never certified entity identity.
    """
    seeds, refusals = {}, []
    for row in search['matches']:
        if not row['matched_context_anchors']:
            continue
        coordinate = {'table_index': row['table_index'], 'row_index': row['row_index']}
        role = row['header_role']
        if row['unsupported_layout'] or role['role'] not in {'position_values', 'unfunded_commitments'}:
            refusals.append({**coordinate, 'reason': 'no_separate_issuer_header_role'})
            continue
        if not row.get('role_header_rows') or any(c.get('hidden_source_content')
                for header in row['role_header_rows'] for c in header['cells']):
            refusals.append({**coordinate, 'reason': 'missing_or_hidden_role_header'})
            continue
        headers = {(c['column'], c['span']) for e in role['evidence']
                   for c in e['matching_cells'].get('issuer', [])}
        if len(headers) != 1:
            refusals.append({**coordinate, 'reason': 'ambiguous_issuer_column'})
            continue
        lo, span = next(iter(headers))
        cells = [c for c in row['source_cells'] if c['column'] >= lo and c['column'] + c['span'] <= lo + span
                 and c.get('text', '').strip()]
        if len(cells) != 1 or cells[0].get('hidden_source_content'):
            refusals.append({**coordinate, 'reason': 'missing_ambiguous_or_hidden_issuer_cell'})
            continue
        phrase = cells[0]['text']
        tokens = _tokens(phrase)
        if len(phrase) > 200 or len(tokens) < 2 or not any(any(c.isalpha() for c in t) for t in tokens):
            refusals.append({**coordinate, 'reason': 'unsupported_source_issuer_phrase'})
            continue
        key = ' '.join(tokens)
        if key not in seeds:
            if len(seeds) >= 16:
                raise ValueError('Source issuer seed cap exceeded')
            seeds[key] = {'phrase': phrase, 'origins': []}
        seeds[key]['origins'].append({**coordinate, 'source_cell': deepcopy(cells[0]),
                                      'context_anchors': list(row['matched_context_anchors'])})
    return {'seeds': list(seeds.values()), 'refusals': refusals, 'identity_verified': False,
            'limitation': 'Exact source issuer-column text for navigation; no suffix stripping, issuer repair, aliases or combined investment-name parsing.'}


def disclosure_search(parsed, *, issuer_phrases, context_ids=(), max_matches=100):
    """Retain lexical mentions and exact-context anchors in every parsed table.

    Caller supplies search phrases and must record where they came from. Names,
    periods, amounts, header roles and matching contexts do not prove identity.
    Unknown/comparative/hidden rows are retained, not promoted or filtered away.
    """
    if not 0 <= len(issuer_phrases) <= 16 or not 1 <= max_matches <= 100:
        raise ValueError('Bounded search phrases and match limit required')
    phrases = {}
    for phrase in issuer_phrases:
        if not isinstance(phrase, str) or len(phrase) > 200:
            raise ValueError('Invalid issuer phrase')
        tokens = _tokens(phrase)
        if len(tokens) < 2 or not any(any(c.isalpha() for c in token) for token in tokens):
            raise ValueError('Issuer phrase needs at least two tokens including letters')
        normalized = ' ' + ' '.join(tokens) + ' '
        if normalized in phrases:
            raise ValueError('Duplicate normalized issuer phrase')
        phrases[normalized] = phrase
    if len(context_ids) > 100 or any(not isinstance(c, str) or not c.strip() for c in context_ids):
        raise ValueError('Invalid context anchors')
    anchors = set(context_ids)
    if not phrases and not anchors:
        raise ValueError('At least one issuer phrase or exact context anchor required')
    tables = parsed.get('tables', [])
    if len(tables) > 1000 or sum(len(t.get('rows', [])) for t in tables) > 10000:
        raise ValueError('Source inventory cap exceeded')
    if len({t['table_index'] for t in tables}) != len(tables):
        raise ValueError('Repeated source table coordinate')
    records, found_anchors, role_counts = [], set(), Counter()
    for table in tables:
        role = table_disclosure_role(table)
        role_counts[role['role']] += 1
        for ri, row in enumerate(table.get('rows', [])):
            if len(row) > 300:
                raise ValueError('Source row cell cap exceeded')
            raw_text = ' '.join(c.get('text', '') for c in row)
            if len(raw_text) > 50000:
                raise ValueError('Source row text cap exceeded')
            normalized = ' ' + ' '.join(_tokens(raw_text)) + ' '
            matched_phrases = [phrase for value, phrase in phrases.items() if value in normalized]
            row_contexts = sorted({f['context_id'] for c in row for f in c.get('inline_facts', [])
                                   if f.get('context_id')})
            matched_anchors = sorted(anchors.intersection(row_contexts))
            found_anchors.update(matched_anchors)
            if not matched_phrases and not matched_anchors:
                continue
            if len(records) >= max_matches:
                raise ValueError('Disclosure match cap exceeded; inventory is incomplete')
            records.append({
                'table_index': table['table_index'], 'row_index': ri,
                'matched_phrases': matched_phrases, 'matched_context_anchors': matched_anchors,
                'source_cells': deepcopy(row), 'header_role': deepcopy(role),
                'role_header_rows': [{'row_index': i, 'cells': deepcopy(table['rows'][i])}
                                     for i in sorted({e['row_index'] for e in role['evidence']})],
                'parsed_report_date': table.get('report_date'),
                'parsed_period_evidence': deepcopy(table.get('period_evidence')),
                'unsupported_layout': bool(table.get('unsupported_layout')),
                'context_ids': row_contexts,
                'context_definitions': {c: deepcopy(parsed.get('contexts', {}).get(c)) for c in row_contexts},
            })
    return {
        'schema_version': 'jev-disclosure-search.v1',
        'issuer_phrases': list(issuer_phrases), 'context_anchors': sorted(anchors),
        'missing_context_anchors': sorted(anchors - found_anchors),
        'tables_scanned': len(tables), 'table_role_counts': dict(role_counts),
        'rows_scanned': sum(len(t.get('rows', [])) for t in tables), 'matches': records,
        'position_identity_verified': False, 'recall_verified': False,
        'ownership_scope_verified': False, 'inclusion_decision': None,
        'limitation': 'Table navigation only. Phrase choice is external; aliases, narrative-only mentions and omitted names can be missed. No sibling identity, source completeness, ownership or row-inclusion certification.',
    }
