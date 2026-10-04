"""Describe explicit table headers; never decide economic identity or inclusion."""
import re


LABELS = {
    'issuer': {'portfolio company', 'issuer', 'company', 'name of issuer'},
    'instrument': {'investment type', 'type of investment', 'investment'},
    'cost': {'cost', 'amortized cost', 'amortised cost'},
    'fair_value': {'fair value', 'market value'},
    'unfunded_commitment': {'unfunded commitment', 'unfunded commitments', 'total unfunded commitments'},
    'commitment_expiration': {'commitment expiration date'},
}


def table_disclosure_role(table):
    """A descriptive header finding, not proof of owner, scope or row validity."""
    evidence, roles = [], set()
    for row_index, row in enumerate(table.get('rows', [])[:8]):
        matches = {}
        for cell in row:
            label = re.sub(r'\(\d{1,2}\)', '', cell.get('text', ''))
            label = ' '.join(label.casefold().split())
            for field, values in LABELS.items():
                if label in values:
                    matches.setdefault(field, []).append({k: cell[k] for k in ('column', 'span', 'text')})
        if not {'issuer', 'instrument', 'fair_value'} <= matches.keys():
            continue
        found = set()
        if 'cost' in matches:
            found.add('position_values')
        if 'unfunded_commitment' in matches and 'commitment_expiration' in matches:
            found.add('unfunded_commitments')
        if not found:
            continue
        evidence.append({'table_index': table.get('table_index'), 'row_index': row_index,
                         'matching_cells': matches, 'indicated_roles': sorted(found)})
        roles.update(found)
    ambiguous_headers = any(len(cells) != 1 for e in evidence for cells in e['matching_cells'].values())
    role = ('unknown' if not roles else 'ambiguous' if len(roles) != 1 or ambiguous_headers
            else next(iter(roles)))
    if table.get('unsupported_layout'):
        role = 'unknown'
    return {'role': role, 'evidence': evidence,
            'ownership_scope_verified': False, 'economic_identity_verified': False,
            'inclusion_decision': None,
            'limitation': 'Describes explicit headers only. A source-value match does not prove unique published exposure.'}
