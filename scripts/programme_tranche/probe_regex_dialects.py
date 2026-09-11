"""Bounded in-memory test of the regex engines used by wrapper sections."""
import json
from pathlib import Path
import re
import time

import duckdb

from pipeline.programme.core import atomic_json, record
from pipeline.staging_bdc import _expand_placeholders

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'scratch/2026-09-10_verification_investigation/regex_dialects.json'


def main():
    started = time.monotonic()
    paths = sorted((ROOT/'data/overrides/bdc_xbrl_wrappers').glob('*.json'))
    assert len(paths) < 500
    cases, samples = [], []
    with duckdb.connect(':memory:') as con:
        for path in paths:
            if 'reference' in path.name:
                continue
            raw = json.loads(path.read_text(encoding='utf-8'))
            staging = raw.get('staging') or {}
            fields = {key: value for key, value in staging.items()
                      if key in ('hierarchy_prefix_re', 'hierarchy_issuer_re',
                                 'hierarchy_instrument_re', 'hierarchy_trailing_re')}
            fields.update({'leaf_guard.'+key: value for key, value in (staging.get('leaf_guard') or {}).items()
                           if key in ('marker_re', 'evidence_re', 'issuer_re', 'instrument_re', 'type_industry_prefix_re')})
            for key, pattern in fields.items():
                assert time.monotonic()-started < 30
                if not isinstance(pattern, str) or not pattern:
                    continue
                item = dict(wrapper=path.name, field=key)
                try:
                    re.compile(pattern)
                    item['python'] = 'valid'
                except re.error as error:
                    item['python'] = str(error)
                try:
                    con.execute('SELECT regexp_matches(?, ?)', ['', pattern]).fetchone()
                    item['duckdb'] = 'valid'
                except duckdb.Error as error:
                    item['duckdb'] = str(error)
                try:
                    con.execute('SELECT regexp_matches(?, ?)',
                                ['', _expand_placeholders(pattern, {})]).fetchone()
                    item['duckdb_after_existing_unicode_decode'] = 'valid'
                except duckdb.Error as error:
                    item['duckdb_after_existing_unicode_decode'] = str(error)
                cases.append(item)
        path = ROOT/'data/overrides/bdc_xbrl_wrappers/0001572694.json'
        pattern = json.loads(path.read_text(encoding='utf-8'))['staging']['hierarchy_issuer_re']
        for separator in ('-', '\u2013', '\u2014', '\ufffd'):
            value = 'Investment 1st Lien/Senior Secured Debt - 90.0% United States '+separator+' 80.0% Acme LLC Industry Software'
            extracted = con.execute('SELECT regexp_extract(?, ?, 1)', [value, pattern]).fetchone()[0]
            assert extracted == 'Acme LLC', repr(extracted)
            samples.append(dict(separator_codepoint=ord(separator), extracted=extracted))
        negatives = []
        for invalid in ('[invalid(', r'(?<=a)b', r'(a)\1', r'\x{NOT_HEX}'):
            try:
                con.execute('SELECT regexp_matches(?, ?)', ['ab', invalid]).fetchone()
            except duckdb.Error as error:
                negatives.append(dict(pattern=invalid, rejected=True, error=str(error)))
            else:
                raise AssertionError('Invalid RE2 pattern was accepted: '+invalid)
    result = dict(staging_patterns_checked=len(cases), cases=cases,
                  duckdb_failures=[case for case in cases if case['duckdb'] != 'valid'],
                  runtime_preprocessed_failures=[case for case in cases if case['duckdb_after_existing_unicode_decode'] != 'valid'],
                  dialect_mismatches=[case for case in cases if case['python'] != case['duckdb']],
                  affected_wrapper=record(ROOT, path.relative_to(ROOT).as_posix()),
                  extraction_samples=samples, rejection_cases=negatives,
                  elapsed_seconds=time.monotonic()-started)
    atomic_json(OUT, result)
    print(str(len(cases))+' staging patterns; '+str(len(result['runtime_preprocessed_failures']))+' errors after existing Unicode decode; '+str(len(result['dialect_mismatches']))+' raw dialect mismatches', flush=True)


if __name__ == '__main__':
    main()
