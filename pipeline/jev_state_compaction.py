"""Optional lossless request encoding experiment, never a source-evidence filter."""
from copy import deepcopy

CELL_COLUMNS = ['column', 'span', 'text', 'inline_facts']


def _encoded_tables(state, version):
    tables = list(state['source_tables'])
    if version == 'lossless-grid.v2':
        tables.extend(note['continuation_table'] for note in state.get('source_notes', [])
                      if 'continuation_table' in note)
    return tables


def compact_request(request, *, version='lossless-grid.v1'):
    if version not in {'lossless-grid.v1', 'lossless-grid.v2'}:
        raise ValueError('Unknown evidence encoding')
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
    for table in _encoded_tables(state, version):
        for row in table['rows']:
            encoded = []
            for cell in row['cells']:
                if set(cell) == set(CELL_COLUMNS):
                    cell = [cell[k] for k in CELL_COLUMNS]
                elif version == 'lossless-grid.v2' and set(cell) == set(CELL_COLUMNS[:3]):
                    cell = [cell[k] for k in CELL_COLUMNS[:3]]
                encoded.append(cell)
            row['cells'] = encoded
    state['context_dictionary'] = contexts
    state['evidence_encoding'] = {
        'version': version, 'cell_array_columns': CELL_COLUMNS,
        'instructions': 'Each array in a source row cells list uses cell_array_columns in order. Dictionary cells are unchanged. Resolve each identity_evidence.context_refs entry from context_dictionary. No source facts, values, notes or identity evidence were omitted.'}
    if version == 'lossless-grid.v2':
        state['evidence_encoding']['instructions'] += (
            ' Arrays also occur in source_notes.continuation_table.rows cells. '
            'Three-element arrays contain column, span and text with no inline_facts key; '
            'four-element arrays additionally contain inline_facts. Empty cell text is preserved.')
    return result


def expand_request(request):
    result = deepcopy(request)
    state = result['state']
    encoding = state.pop('evidence_encoding')
    version = encoding['version']
    if version not in {'lossless-grid.v1', 'lossless-grid.v2'} or encoding['cell_array_columns'] != CELL_COLUMNS:
        raise ValueError('Unknown evidence encoding')
    contexts = state.pop('context_dictionary')
    for candidate in state['source_candidates']:
        identity = candidate.get('identity_evidence', {})
        if 'context_refs' in identity:
            identity['contexts'] = {key: contexts[key] for key in identity.pop('context_refs')}
    for table in _encoded_tables(state, version):
        for row in table['rows']:
            decoded = []
            for cell in row['cells']:
                if isinstance(cell, list):
                    if len(cell) not in ({3, 4} if version == 'lossless-grid.v2' else {4}):
                        raise ValueError('Malformed compact cell')
                    cell = dict(zip(CELL_COLUMNS, cell))
                decoded.append(cell)
            row['cells'] = decoded
    return result
