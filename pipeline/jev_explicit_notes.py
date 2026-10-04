"""Resolve explicit inline-XBRL fact/footnote links without assigning SOI scope.

Optional pilot diagnostic. A link establishes which note a fact references; it
does not establish that all relevant notes or positions have been retrieved.
"""
from collections import defaultdict
import re

from pipeline.jev_bundles import clean, _hidden_cell_content, _NOTE_DEFINITION, _qname_namespace

IX = 'http://www.xbrl.org/2013/inlineXBRL'
ARC = 'http://www.xbrl.org/2003/arcrole/fact-footnote'
ROLE = 'http://www.xbrl.org/2003/role/footnote'
LINK = 'http://www.xbrl.org/2003/role/link'


def _kind(node, local):
    return node.name.split(':')[-1].lower() == local and _qname_namespace(node, node.name) == IX


def _hidden(node):
    return (_hidden_cell_content(node)
            or any(_kind(n, 'hidden') for n in [node, *node.parents])
            or any(_kind(n, 'hidden') for n in node.find_all(True)))


def _numbered_container(note):
    for node in [note, *list(note.parents)[:4]]:
        if node.name in {'html', 'body', '[document]'} or node.find('table'):
            break
        text = clean(node.get_text(' ', strip=True))
        if len(text) > 5000:
            break
        match = _NOTE_DEFINITION.match(text)
        nested = [n for n in node.find_all(True) if _kind(n, 'footnote')]
        if match and ((node is note and not nested) or (len(nested) == 1 and nested[0] is note
                       and clean(match[3]) == clean(note.get_text(' ', strip=True)))):
            marker = (match[1] or match[2]).lower()
            if match[1] and re.fullmatch(r'[+^#*]+', marker):
                marker = '(' + marker + ')'
            return node, marker, text
    return None, None, None


def resolve_explicit_notes(soup, fact_ids):
    """Retain source IDs and refuse ambiguous or unsupported selected links.

    Accept at most 100 explicitly selected fact IDs; scan a bounded document
    once. No inherited period, ownership or bundle-ready claim is produced.
    """
    if (not isinstance(fact_ids, (list, tuple)) or not 1 <= len(fact_ids) <= 100
            or any(not isinstance(f, str) or not f or len(f) > 200 for f in fact_ids)
            or len(set(fact_ids)) != len(fact_ids)):
        raise ValueError('One to 100 unique explicit fact IDs required')
    nodes = soup.find_all(True)
    if len(nodes) > 500000:
        raise ValueError('Document element cap exceeded')
    by_id, relationships = defaultdict(list), []
    for node in nodes:
        if node.get('id'):
            by_id[str(node['id'])].append(node)
        if node.name.split(':')[-1].lower() == 'relationship':
            relationships.append(node)
    if len(relationships) > 2000:
        raise ValueError('Relationship cap exceeded')
    links = defaultdict(list)
    references = 0
    selected = set(fact_ids)
    for index, relation in enumerate(relationships):
        sources, targets = str(relation.get('fromrefs', '')).split(), str(relation.get('torefs', '')).split()
        references += len(sources) + len(targets)
        if references > 100000:
            raise ValueError('Relationship reference cap exceeded')
        for source in selected.intersection(sources):
            links[source].append((index, relation, targets))
    records = []
    for fact_id in fact_ids:
        blockers, notes = [], []
        facts = by_id[fact_id]
        fact = facts[0] if len(facts) == 1 else None
        if fact is None:
            blockers.append('missing_or_duplicate_fact_id')
        elif not (_kind(fact, 'nonfraction') or _kind(fact, 'nonnumeric')):
            blockers.append('unsupported_fact_element')
        elif _hidden(fact):
            blockers.append('hidden_fact')
        if fact is not None and (fact.has_attr('continuedat') or not fact.get('contextref')):
            blockers.append('unsupported_fact_continuation_or_context')
        if not links[fact_id]:
            blockers.append('no_explicit_relationship')
        for index, relation, targets in links[fact_id]:
            if (not _kind(relation, 'relationship') or relation.get('arcrole') != ARC
                    or relation.get('linkrole', LINK) != LINK):
                blockers.append('unsupported_relationship')
                continue
            if not targets or len(targets) > 50 or len(set(targets)) != len(targets):
                blockers.append('invalid_note_targets')
                continue
            for target in targets:
                matches = by_id[target]
                if len(matches) != 1:
                    blockers.append('missing_or_duplicate_note_id')
                    continue
                note = matches[0]
                if not _kind(note, 'footnote') or note.get('footnoterole', ROLE) != ROLE:
                    blockers.append('unsupported_note_element_or_role')
                    continue
                if any(n.has_attr('continuedat') for n in [note, *note.find_all(True)]):
                    blockers.append('unsupported_note_continuation')
                    continue
                if any(_kind(n, 'exclude') for n in note.find_all(True)):
                    blockers.append('unsupported_note_exclusion')
                    continue
                container, marker, text = _numbered_container(note)
                if container is None:
                    blockers.append('unresolved_numbered_note_container')
                    continue
                if _hidden(container):
                    blockers.append('hidden_note')
                    continue
                notes.append({'fact_id': fact_id, 'note_id': target, 'marker': marker,
                              'text': text, 'relationship_index': index, 'arcrole': ARC})
        markers = defaultdict(set)
        for note in notes:
            markers[note['marker']].add(note['text'])
        if any(len(values) > 1 for values in markers.values()):
            blockers.append('conflicting_linked_note_text')
        records.append({'fact_id': fact_id,
                        'fact_context_id': fact.get('contextref') if fact else None,
                        'fact_name': fact.get('name') if fact else None,
                        'status': 'unresolved' if blockers else 'explicit_links_resolved',
                        'blockers': sorted(set(blockers)), 'notes': notes})
    return {'schema': 'jev-explicit-notes.v1', 'records': records,
            'notes_applied': False, 'notes_complete': False, 'period_scope_assigned': False,
            'position_identity_verified': False, 'production_clearance_enabled': False}
