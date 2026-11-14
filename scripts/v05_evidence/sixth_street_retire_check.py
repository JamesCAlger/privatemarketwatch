"""Sixth Street Specialty Lending (0001508655) D-252 retirement checks. Committed copy of the fund agent scratch script.
Usage: python scripts/v05_evidence/sixth_street_retire_check.py <label> verify -   (exit 1 on any failure; every plant must fail)

Read-only deterministic checks behind the D-252 retirements of fund 0001508655 (agent:fund-tslx-20261114).

    python retire_check.py <label> build <out.json>     # run every check and its plants, write the store
    python retire_check.py <label> verify <store.json>  # re-run the checks of a store (plants included)

Each check recomputes the verdict's own claim on the quarter's published rows, each read on its own printed line (the
inline-XBRL <tr> that carries the fair-value fact of the row's own context; a continuation line takes the company cell of
the group above). A plant (a realistic wrong value put in one row) must make the check fail.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, 'scripts/v05_evidence')
import campaign_retirement_check as chk  # noqa: E402
from fund_gate import page_text  # noqa: E402

from functools import lru_cache

from fund_gate import normalise  # noqa: E402

INSTR = re.compile(r'^(first|second|secured|unsecured|subordinated|series|class|common|preferred|warrants?|trust|ordinary|membership|partnership|'
                   r'convertible|abl|revolving|roll|super|\(|earnout|co-invest|unitranche|term|delayed|structured|senior|\d{1,3}(,\d{3})* (units|shares|class|ordinary)|\d+ )', re.I)
FV = 'us-gaap:InvestmentOwnedAtFairValue'
CTX = re.compile(r'name="us-gaap:InvestmentOwnedAtFairValue"[^>]*contextRef="([^"]+)"|contextRef="([^"]+)"[^>]*name="us-gaap:InvestmentOwnedAtFairValue"')


def is_issuer_cell(cells):
    first = cells[0]
    if len(cells) < 4 or not re.search(r'[A-Za-z]', first):
        return False
    if re.match(r'^\d', first):
        return bool(re.search(r'(Inc|LLC|Corp|Ltd|LP|L\.P\.|Limited|Holdings|Stores)\b', first))
    return not INSTR.match(first)


@lru_cache(maxsize=8)
def printed_map(acc):
    raw = open('data/raw/filings/bdc_html/1508655/%s.html' % acc.replace('-', ''), encoding='utf-8', errors='replace').read()
    out = {}
    issuer = None
    marks = set()
    for m in re.finditer(r'<tr\b.*?</tr>', raw, flags=re.S | re.I):
        seg = m.group(0)
        cells = [normalise(re.sub(r'<[^>]+>', ' ', c)) for c in re.findall(r'<td\b.*?</td>', seg, flags=re.S | re.I)]
        cells = [c for c in cells if c not in ('', '$', '%', ')')]
        if not cells:
            continue
        if is_issuer_cell(cells):
            issuer = re.sub(r'(\s*\(\d+\))+\s*$', '', cells[0]).strip()
            marks = set(re.findall(r'\((\d{1,2})\)', cells[0]))
        if FV not in seg:
            continue
        line = re.sub(r'\s+', ' ', normalise(re.sub(r'<[^>]+>', ' ', seg))).strip()
        for a, b in CTX.findall(seg):
            out.setdefault(a or b, dict(issuer=issuer, line=line, cells=cells, marks=marks | set(re.findall(r'\((\d{1,2})\)', ' '.join(cells[:2])))))
    return out


def norm_issuer(s):
    s = (s or '').strip().lower()
    s = re.sub(r'[\s.,]+$', '', s)
    s = s.replace('é', 'e')
    return s

import types as _t
pl = _t.SimpleNamespace(printed_map=printed_map, norm_issuer=norm_issuer)

CIK = '0001508655'
VERDICTS = Path('data/output/review_queue/verdicts')
FINDINGS = [
    # review_id, rule, quarter, engine, claim label
    ('RVQ_REV_96801ceaf022', 'C206', '2023-09-30', 'row_validation'),
    ('RVQ_REV_a889ab1f9ae5', 'C206', '2024-09-30', 'row_validation'),
    ('RVQ_REV_bb3026d65e3f', 'C206', '2025-03-31', 'row_validation'),
    ('RVQ_REV_9f3cb55c402a', 'X10', '2023-09-30', 'row_validation'),
    ('RVQ_BLK_651d2f079e7e', 'E07', '2025-12-31', 'oracle'),
]
MARKER = re.compile(r'\bpar\b|due\s*\d|initial acquisition date|reference rate|interest rate|\d+\.\d+\s*%|first-?lien|second-?lien|\$\s*\d', re.I)


def load_rows(con, label, q):
    P = 'scratch/fund_sandbox/%s/output/private_markets_holdings.parquet' % label
    cur = con.execute(f"""SELECT row_id, accession_number acc, src_context_id ctx, issuer_name, CAST(instrument_description AS VARCHAR) instr,
        position_key, fair_value, CAST(maturity_date AS VARCHAR)[:7] mat, asset_category, accounting_record_class arc
        FROM read_parquet('{P}') WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{CIK}' AND CAST(report_date AS VARCHAR)[:10]='{q}'
        AND source ILIKE '%bdc%' AND coalesce(accounting_record_class,'') <> 'underlying_schedule'""")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def c206(rows):
    fails, tested = [], 0
    for r in rows:
        if MARKER.search(r['issuer_name'] or ''):
            fails.append((r['row_id'], 'issuer_name carries instrument/date/rate text: %s' % (r['issuer_name'] or '')[:60]))
            continue
        hit = pl.printed_map(r['acc']).get(r['ctx'])
        if not hit:
            continue
        tested += 1
        pub, prt = pl.norm_issuer(r['issuer_name']), pl.norm_issuer(hit['issuer'])
        if pub != prt and not prt.startswith(pub + ',') and not prt.replace('é', 'e').startswith(pub):
            fails.append((r['row_id'], "published '%s', printed company cell '%s'" % (r['issuer_name'], hit['issuer'])))
    return not fails, tested, fails


def b02(rows):
    fails = []
    mp = [r for r in rows if (r['issuer_name'] or '').lower().startswith('madison park')]
    if len(mp) < 2:
        fails.append(('', 'fewer than two Madison Park rows'))
    keys = [r['position_key'] for r in mp]
    if len(set(keys)) != len(keys):
        fails.append(('', 'Madison Park rows share a position key'))
    series = {re.search(r'20\d\d\s*-?\s*\d+A', r['instr'] or '') and re.sub(r'\s', '', re.search(r'20\d\d\s*-?\s*\d+A', r['instr'] or '').group(0)) for r in mp}
    if len(series) != len(mp) or None in series:
        fails.append(('', 'the series (65A / 72A) is not distinct on every row'))
    counts = {}
    for r in rows:
        if r['position_key'] and (r['fair_value'] or 0) != 0:
            counts[r['position_key']] = counts.get(r['position_key'], 0) + 1
    dup = [k for k, v in counts.items() if v > 1]
    if dup:
        fails.append(('', '%d position keys repeated among valued rows' % len(dup)))
    for r in mp:
        ok, why = chk.row_fv({'row_id': r['row_id'], 'src_context_id': r['ctx'], 'accession_number': r['acc'], 'cik': CIK,
                              'fair_value': r['fair_value'], 'report_date': None}, require_fact=True) if False else (True, '')
        hit = pl.printed_map(r['acc']).get(r['ctx'])
        if not hit:
            fails.append((r['row_id'], 'no printed fair-value line'))
            continue
        nums = [int(x.replace(',', '')) for x in re.findall(r'(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?![\d.%])', hit['line'])]
        if int(round((r['fair_value'] or 0) / 1000)) not in nums:
            fails.append((r['row_id'], 'fair value %s is not a number on its printed line' % r['fair_value']))
    return not fails, len(mp), fails


def x10(rows):
    fails, tested = [], 0
    for r in rows:
        hit = pl.printed_map(r['acc']).get(r['ctx'])
        if not hit or r['asset_category'] != 'LOAN':
            continue
        m = re.search(r'due\s*(\d{1,2})/(\d{4})', hit['line'])
        if not m:
            continue
        tested += 1
        exp = '%s-%02d' % (m.group(2), int(m.group(1)))
        if (r['mat'] or '') != exp:
            fails.append((r['row_id'], "published maturity %s, printed due %s" % (r['mat'], exp)))
    return not fails, tested, fails


def e07(q):
    crows = chk.quarter_rows(chk._con(), 'scratch/fund_sandbox/%s/output/private_markets_holdings.parquet' % LABEL, CIK, q)
    res = chk.check_quarter('fv_conservation', crows, CIK, q, anchors=(3347317.0, 3347317000.0))
    pl_ = []
    for name, prows in chk.plants('fv_conservation', crows, CIK, q):
        r2 = chk.check_quarter('fv_conservation', prows, CIK, q, anchors=(3347317.0, 3347317000.0))
        pl_.append((name, r2['ok']))
    return res['ok'], res['detail'].get('n_tested', 0), [(f.get('row_id', ''), str(f)[:100]) for f in res['fails']][:5], pl_, crows


def run(rule, rows, q):
    if rule == 'C206':
        return c206(rows)
    if rule == 'B02':
        return b02(rows)
    if rule == 'X10':
        return x10(rows)


def plants(rule, rows, q):
    out = []
    if rule == 'C206':
        tested = [r for r in rows if pl.printed_map(r['acc']).get(r['ctx'])]
        a = [dict(r) for r in rows]
        i = a.index(next(x for x in a if x['row_id'] == tested[0]['row_id']))
        a[i]['issuer_name'] = pl.printed_map(a[i]['acc'])[a[i]['ctx']]['line'][:90]
        out.append(('issuer_name replaced by the concatenated printed line', a))
        b = [dict(r) for r in rows]
        b[i]['issuer_name'] = 'Another Company, Inc.'
        out.append(('issuer_name replaced by another company', b))
    elif rule == 'B02':
        mp = [i for i, r in enumerate(rows) if (r['issuer_name'] or '').lower().startswith('madison park')]
        a = [dict(r) for r in rows]
        a[mp[1]]['position_key'] = a[mp[0]]['position_key']
        out.append(('two series share one position key', a))
        b = [dict(r) for r in rows]
        b[mp[0]]['fair_value'] = (b[mp[0]]['fair_value'] or 0) + 7000
        out.append(('fair value shifted by 7,000', b))
    elif rule == 'X10':
        i = next(i for i, r in enumerate(rows) if r['asset_category'] == 'LOAN' and pl.printed_map(r['acc']).get(r['ctx']) and 'due' in pl.printed_map(r['acc'])[r['ctx']]['line'] and r['mat'])
        a = [dict(r) for r in rows]
        a[i]['mat'] = '%04d-%s' % (int(a[i]['mat'][:4]) + 1, a[i]['mat'][5:])
        out.append(('maturity shifted one year', a))
    return out


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == '__main__':
    LABEL, mode, target = sys.argv[1], sys.argv[2], sys.argv[3]
    con = duckdb.connect()
    results = []
    for rid, rule, q, engine in FINDINGS:
        QUARTER = q
        rows = load_rows(con, LABEL, q)
        if rule == 'E07':
            ok, n, fails, res_plants, crows = e07(q)
        else:
            ok, n, fails = run(rule, rows, q)
            res_plants = [(name, run(rule, prows, q)[0]) for name, prows in plants(rule, rows, q)]
        bad_plants = [n_ for n_, passed in res_plants if passed]
        print('%s %s %s: %s tested=%s fails=%d plants_failed_check=%d/%d %s' % (rid, rule, q, 'PASS' if ok else 'FAIL', n, len(fails),
              len(res_plants) - len(bad_plants), len(res_plants), '; '.join(f[1] for f in fails[:3])[:200]), flush=True)
        results.append(dict(review_id=rid, rule=rule, q=q, engine=engine, ok=ok and not bad_plants, tested=n, rows=len(rows), plants=res_plants,
                            cited=[r['row_id'] for r in rows]))
    if mode == 'verify':
        sys.exit(0 if all(r['ok'] for r in results) else 1)
    if mode == 'build':
        Path(target).write_text(json.dumps(results, indent=1, default=str), encoding='utf-8')
        print('wrote', target)
