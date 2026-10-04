"""Describe explicit table headers; never decide economic identity or inclusion."""
import re
from datetime import datetime


LABELS = {
    'issuer': {'portfolio company', 'issuer', 'company', 'name of issuer'},
    'instrument': {'investment type', 'type of investment', 'investment'},
    'cost': {'cost', 'amortized cost', 'amortised cost'},
    'fair_value': {'fair value', 'market value'},
    'unfunded_commitment': {'unfunded commitment', 'unfunded commitments', 'total unfunded commitments'},
    'commitment_expiration': {'commitment expiration date'},
}


def _rollforward_band(row):
    """Require two dated FV columns and both movement columns in one band."""
    matches = {}
    dated = []
    for cell in row:
        label = ' '.join(re.sub(r'\([a-z0-9]{1,2}\)', '', cell.get('text', ''), flags=re.I).split())
        normalized = label.casefold()
        field = ({'name of investment': 'issuer', 'gross addition': 'gross_addition',
                  'gross additions': 'gross_addition', 'gross reduction': 'gross_reduction',
                  'gross reductions': 'gross_reduction'}).get(normalized)
        evidence = {k: cell[k] for k in ('column', 'span', 'text')}
        if field:
            matches.setdefault(field, []).append(evidence)
        date_match = re.fullmatch(r'Fair Value at ([A-Za-z]+ \d{1,2}, \d{4})', label, re.I)
        if date_match:
            try:
                date = datetime.strptime(date_match[1], '%B %d, %Y').date().isoformat()
            except ValueError:
                continue
            dated.append((date, evidence))
    if not {'issuer', 'gross_addition', 'gross_reduction'} <= matches.keys() or len(dated) != 2:
        return None
    # Preserve uncertain orientation instead of inferring beginning/end roles.
    if dated[0][0] >= dated[1][0] or dated[0][1]['column'] >= dated[1][1]['column']:
        return None
    matches['beginning_fair_value'] = [{**dated[0][1], 'header_date': dated[0][0]}]
    matches['ending_fair_value'] = [{**dated[1][1], 'header_date': dated[1][0]}]
    return matches


def table_disclosure_role(table):
    """A descriptive header finding, not proof of owner, scope or row validity."""
    evidence, roles = [], set()
    for row_index, row in enumerate(table.get('rows', [])[:8]):
        rollforward = _rollforward_band(row)
        if rollforward:
            evidence.append({'table_index': table.get('table_index'), 'row_index': row_index,
                             'matching_cells': rollforward, 'indicated_roles': ['investment_rollforward']})
            roles.add('investment_rollforward')
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
