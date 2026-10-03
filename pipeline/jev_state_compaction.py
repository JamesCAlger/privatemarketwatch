"""Optional lossless request encoding experiment, never a source-evidence filter."""
from copy import deepcopy

CELL_COLUMNS = ['column', 'span', 'text', 'inline_facts']


def compact_request(request):
    result = deepcopy(request)
    state = result['state']
    if 'evidence_encoding' in state or 'context_dictionary' in state:
        raise ValueError('Already encoded or conflicting keys')
    contexts = {}
    for candidate in state['source_candidates']:
        identity = candidate.get('identity_evidence', {})
        if 'context_refs' in identity:
            raise ValueError('Conflicting context reference key')
        if 'contexts' in identity:
            original = identity.pop('contexts')
            identity['context_refs'] = list(original)
            for key, value in original.items():
                if key in contexts and contexts[key] != value:
                    raise ValueError('Contradictory source context definitions')
                contexts[key] = value
    for table in state['source_tables']:
        for row in table['rows']:
            row['cells'] = [[cell[k] for k in CELL_COLUMNS] if set(cell) == set(CELL_COLUMNS) else cell
                            for cell in row['cells']]
    state['context_dictionary'] = contexts
    state['evidence_encoding'] = {
        'version': 'lossless-grid.v1', 'cell_array_columns': CELL_COLUMNS,
        'instructions': 'Each array in a source row cells list uses cell_array_columns in order. Dictionary cells are unchanged. Resolve each identity_evidence.context_refs entry from context_dictionary. No source facts, values, notes or identity evidence were omitted.'}
    return result


def expand_request(request):
    result = deepcopy(request)
    state = result['state']
    encoding = state.pop('evidence_encoding')
    if encoding['version'] != 'lossless-grid.v1' or encoding['cell_array_columns'] != CELL_COLUMNS:
        raise ValueError('Unknown evidence encoding')
    contexts = state.pop('context_dictionary')
    for candidate in state['source_candidates']:
        identity = candidate.get('identity_evidence', {})
        if 'context_refs' in identity:
            identity['contexts'] = {key: contexts[key] for key in identity.pop('context_refs')}
    for table in state['source_tables']:
        for row in table['rows']:
            decoded = []
            for cell in row['cells']:
                if isinstance(cell, list):
                    if len(cell) != len(CELL_COLUMNS):
                        raise ValueError('Malformed compact cell')
                    cell = dict(zip(CELL_COLUMNS, cell))
                decoded.append(cell)
            row['cells'] = decoded
    return result
