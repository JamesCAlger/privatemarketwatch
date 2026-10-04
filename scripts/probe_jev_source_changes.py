"""Exercise changed real-source structures offline; mutations are synthetic."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import build_bundle, parse_source
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.review_jev_sources import review_source_path

CASES = {'fortress': 'ROW-0a3fe5a6482a78b9', 'onex': 'ROW-1a734ef6a228d65a',
         'oaktree': 'ROW-1c2a72c58fbc2d87'}
SOURCE_IDS = {'ROW-0a3fe5a6482a78b9': 't10r32', 'ROW-1a734ef6a228d65a': 't8r22',
              'ROW-1c2a72c58fbc2d87': 't13r24'}


def mutate(raw, packet, mode):
    if mode == 'unchanged':
        return raw
    soup = BeautifulSoup(raw.decode('utf-8'), 'lxml')
    if mode == 'insert_navigation_table':
        navigation = BeautifulSoup('<table><tr><td>Navigation</td></tr></table>', 'lxml').table
        soup.body.insert(0, navigation)
        return str(soup).encode('utf-8')
    if mode in {'currency_alias', 'currency_namespace_conflict', 'currency_namespace_missing'}:
        modified = 0
        for measure in soup.find_all(re.compile(r'(?:^|:)measure$')):
            if measure.get_text(strip=True).split(':')[-1] != 'USD':
                continue
            measure.string = 'pilotcurrency:USD'
            if mode != 'currency_namespace_missing':
                measure['xmlns:pilotcurrency'] = ('http://www.xbrl.org/2003/iso4217'
                    if mode == 'currency_alias' else 'urn:unrelated-unit')
            modified += 1
        if not modified:
            raise ValueError('No currency measures changed')
        return str(soup).encode('utf-8')
    tables = [t for t in soup.find_all('table') if any(tr.find(['td', 'th']) for tr in t.find_all('tr'))]
    coordinates = {(c['table_index'], c['row_index']) for c in packet['source_candidates']}
    target = next(c for c in packet['source_candidates'] if c['evidence_id'] == SOURCE_IDS[packet['flag']['row_id']])
    if mode == 'target_issuer_alias':
        coordinates = {(target['table_index'], target['row_index'])}
    modified = 0
    for ti, ri in sorted(coordinates):
        rows = [tr for tr in tables[ti].find_all('tr') if tr.find(['td', 'th'])]
        row = rows[ri]
        if mode == 'target_issuer_alias':
            column = 0
            for cell in row.find_all(['td', 'th']):
                if column == target['headers']['issuer']['column']:
                    if cell.find('ix:nonfraction'):
                        raise ValueError('Issuer mutation would alter numeric evidence')
                    cell.clear()
                    cell.append('Alternate Legal Name LLC')
                    modified += 1
                    break
                column += int(cell.get('colspan', 1))
        elif mode == 'unsupported_rowspan':
            row.find(['td', 'th'])['rowspan'] = '2'
            modified += 1
        elif mode in {'unknown_numeric_transform', 'unresolved_currency'}:
            for fact in row.find_all('ix:nonfraction'):
                if mode == 'unknown_numeric_transform':
                    fact['format'] = 'future:unrecognized-decimal'
                else:
                    fact['unitref'] = 'missing-currency-declaration'
                modified += 1
        elif mode == 'missing_context_reference':
            for fact in row.find_all('ix:nonfraction'):
                fact['contextref'] = 'missing-position-context'
                modified += 1
        elif mode in {'nil_monetary_fact', 'continued_monetary_fact', 'excluded_monetary_content', 'invalid_monetary_sign'}:
            for fact in row.find_all('ix:nonfraction'):
                if mode == 'nil_monetary_fact':
                    fact['xsi:nil'] = 'true'
                elif mode == 'continued_monetary_fact':
                    fact['continuedat'] = 'unsupported-fragment'
                elif mode == 'invalid_monetary_sign':
                    fact['sign'] = '+'
                else:
                    excluded = soup.new_tag('ix:exclude')
                    for child in list(fact.contents):
                        excluded.append(child.extract())
                    fact.append(excluded)
                modified += 1
        elif mode in {'conflicting_context_date', 'missing_context_instant', 'missing_context_entity'}:
            for fact in row.find_all('ix:nonfraction'):
                context = soup.find(id=fact.get('contextref'))
                name = 'identifier' if mode == 'missing_context_entity' else 'instant'
                instant = context.find(re.compile(r'(?:^|:)' + name + '$')) if context else None
                if instant:
                    if mode == 'conflicting_context_date':
                        instant.string = '1999-12-31'
                    else:
                        instant.decompose()
                    modified += 1
        else:
            raise ValueError('Unknown mutation')
    if not modified:
        raise ValueError('Mutation did not exercise source evidence')
    return str(soup).encode('utf-8')


def candidate_content(packet):
    # Ignore coordinate shifts, but preserve every candidate's identity and values.
    return sorted(json.dumps({'values': c['source_values'], 'identity': c['identity_evidence']},
                             sort_keys=True) for c in packet['source_candidates'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--case', choices=CASES, required=True)
    parser.add_argument('--context-probe', action='store_true')
    parser.add_argument('--retrieval-probe', action='store_true')
    parser.add_argument('--inline-probe', action='store_true')
    parser.add_argument('--currency-probe', action='store_true')
    parser.add_argument('--label', default='24')
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    if not args.label.isdigit():
        raise ValueError('Numeric experiment label required')
    if sum((args.context_probe, args.retrieval_probe, args.inline_probe, args.currency_probe)) > 1:
        raise ValueError('Choose one probe family')
    paths = list((run / 'current_development_packets_20').glob('*_' + CASES[args.case] + '.json'))
    if len(paths) != 1:
        raise ValueError('Expected one frozen packet')
    packet = read(paths[0])
    source = review_source_path(repo, packet)
    if source.stat().st_size > 40 * 1024 * 1024 or sha(source) != packet['filing']['sha256']:
        raise ValueError('Source changed or exceeds limit')
    raw = source.read_bytes()
    records = []
    modes = ('unchanged', 'missing_context_reference', 'missing_context_instant', 'missing_context_entity') if args.context_probe else (
        'unchanged', 'insert_navigation_table', 'unsupported_rowspan',
        'unknown_numeric_transform', 'unresolved_currency', 'conflicting_context_date')
    if args.retrieval_probe:
        modes = ('unchanged', 'target_issuer_alias')
    if args.inline_probe:
        modes = ('unchanged', 'nil_monetary_fact', 'continued_monetary_fact',
                 'excluded_monetary_content', 'invalid_monetary_sign')
    if args.currency_probe:
        modes = ('unchanged', 'currency_alias', 'currency_namespace_conflict', 'currency_namespace_missing')
    for mode in modes:
        print('Source-change probe:', args.case, mode, flush=True)
        altered = mutate(raw, packet, mode)
        parsed = parse_source(altered)
        result = build_bundle(packet['flag'], [deepcopy(packet['output_position'])], packet['provenance'],
                              parsed_source=parsed, source_metadata={'sha256': hashlib.sha256(altered).hexdigest()})
        positive = mode in {'unchanged', 'insert_navigation_table', 'currency_alias'}
        ready = result['evidence_status']['status'] == 'ready_for_model'
        equivalent = candidate_content(result) == candidate_content(packet)
        passed = (ready and equivalent) if positive else not ready
        expected = 'ready_equivalent' if positive else 'blocked'
        if mode == 'target_issuer_alias':
            expected = 'blocked_or_anchor_retained'
            passed = not ready or SOURCE_IDS[CASES[args.case]] in {c['evidence_id'] for c in result['source_candidates']}
        records.append({'mutation': mode, 'expected': expected,
                        'passed': passed, 'actual_status': result['evidence_status']['status'],
                        'candidate_content_unchanged': equivalent, 'candidates': len(result['source_candidates']),
                        'blocking_reasons': result['evidence_status']['blocking_reasons'],
                        'candidate_blockers': {c['evidence_id']: c['blocking_reasons'] for c in result['source_candidates']},
                        'source_sha256': hashlib.sha256(altered).hexdigest()})
        del parsed, altered, result
    report = {'case': args.case, 'row_id': CASES[args.case], 'records': records,
              'passed': sum(r['passed'] for r in records), 'probes': len(records),
              'builder_sha256': builder_hash, 'api_calls': 0,
              'production_clearance_enabled': False,
              'limitation': 'Synthetic mutations of existing development filings, not observed future layouts or independent candidate-recall validation.'}
    prefix = 'source_retrieval_' if args.retrieval_probe else ('source_context_' if args.context_probe else 'source_changes_')
    if args.inline_probe:
        prefix = 'source_inline_'
    if args.currency_probe:
        prefix = 'source_currency_'
    if sha(ROOT / 'pipeline/jev_bundles.py') != builder_hash:
        raise ValueError('Builder changed during probe')
    write(run / (prefix + args.label + '_' + args.case + '.json'), report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
