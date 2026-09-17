"""Read-only footprint comparison of two sealed identity bundles.

Counts only. A large ratio change on any populated count, or any reporting-entity
label left in parent scope, blocks a freeze until it is explained.
"""
import argparse
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MIN_POPULATION = 100


def _label_regex(label):
    # RE2: no lookaround. Label at string start or after comma/space, optionally
    # followed by a space-separated ordinal or a comma. Admits both "Borrower, Label"
    # and "<borrower> <ordinal> <label>" forms. The own-interest exclusion removes
    # the fund's own LP wrapper (e.g. "BCRED Emerald JV LP"), keeping only true
    # labelled parent-scope positions.
    lab = ' '.join(label.lower().split()).replace('.', '\\.')
    return '(^|[ ,])' + lab + '(,| [0-9]+$|$)'


def _own_interest_exclusion_pattern(labels):
    """Build exclusion pattern for own-interest labels in parent scope.

    For each label, the pattern matches rows where the issuer_name starts with
    "[fund_prefix] [label] [optional_number]$", indicating an own-interest wrapper.
    """
    patterns = []
    for label in sorted(set(labels)):
        lab = ' '.join(label.lower().split()).replace('.', '\\.')
        patterns.append('(^[a-z]+ ' + lab + '( [0-9]+)?$)')
    return '|'.join(patterns)


def compute_footprint(bundle, encodings=None):
    bundle = Path(bundle)
    if encodings is None:
        from pipeline.source_encodings import load_encodings
        encodings = load_encodings()
    out = {}
    with duckdb.connect(config={'threads': 2}) as con:
        h = str(bundle / 'private_markets_holdings.parquet')
        m = str(bundle / 'position_matches.parquet')
        e = str(bundle / 'position_id_edges.parquet')
        l = str(bundle / 'entity_lookup.parquet')
        out['match_method'] = dict(con.execute(
            "SELECT match_method, count(*) FROM read_parquet(?) GROUP BY 1", [m]).fetchall())
        out['edge_type'] = dict(con.execute(
            "SELECT edge_type, count(*) FROM read_parquet(?) GROUP BY 1", [e]).fetchall())
        out['e_fv_outliers'] = con.execute("""SELECT count(*) FILTER (WHERE begin_fair_value > 0 AND end_fair_value > 0
            AND (end_fair_value / begin_fair_value < 0.5 OR end_fair_value / begin_fair_value > 2))
            FROM read_parquet(?) WHERE match_method LIKE 'E_%'""", [m]).fetchone()[0]
        positions, singletons = con.execute("""WITH c AS (SELECT position_id, count(*) n FROM read_parquet(?)
            WHERE position_id IS NOT NULL GROUP BY 1) SELECT count(*), count(*) FILTER (WHERE n = 1) FROM c""", [h]).fetchone()
        out['positions'], out['singletons'] = positions, singletons
        out['scope_rows'] = dict(con.execute(
            "SELECT accounting_record_class, count(*) FROM read_parquet(?) GROUP BY 1", [h]).fetchall())
        out['scope_fv'] = {k: float(v) for k, v in con.execute(
            "SELECT accounting_record_class, coalesce(sum(fair_value), 0) FROM read_parquet(?) GROUP BY 1", [h]).fetchall()}
        out['joint_entities'] = con.execute(
            "SELECT count(DISTINCT entity_id) FROM read_parquet(?) WHERE normalized_name LIKE 'joint:%'", [l]).fetchone()[0]
        labelled = {}
        for cik, enc in sorted(encodings.items()):
            labels = list(enc.get('reporting_entity_suffixes', [])) + list(enc.get('reporting_entity_identifier_suffixes', []))
            if not labels:
                continue
            pattern = '|'.join('(' + _label_regex(x) + ')' for x in sorted(set(labels)))
            exclusion_pattern = _own_interest_exclusion_pattern(labels)
            labelled[cik] = con.execute("""SELECT count(*) FROM read_parquet(?)
                WHERE cik = ? AND accounting_record_class = 'parent_schedule'
                AND regexp_matches(lower(trim(issuer_name)), ?)
                AND NOT regexp_matches(lower(trim(issuer_name)), ?)""",
                [h, cik, pattern, exclusion_pattern]).fetchone()[0]
        out['labelled_parent_rows'] = labelled
    return out


def _flat(fp):
    flat = {}
    for group in ('match_method', 'edge_type', 'scope_rows'):
        for k, v in fp.get(group, {}).items():
            flat[group + '.' + k] = v
    for k in ('positions', 'singletons', 'joint_entities', 'e_fv_outliers'):
        flat[k] = fp.get(k, 0)
    return flat


def compare_footprints(current, prior, max_ratio=2.0):
    flags = []
    cur, pri = _flat(current), _flat(prior)
    for metric in sorted(set(cur) | set(pri)):
        c, p = cur.get(metric, 0), pri.get(metric, 0)
        if max(c, p) < MIN_POPULATION:
            continue
        ratio = (c / p) if p else float('inf')
        if ratio > max_ratio or ratio < 1 / max_ratio:
            flags.append(dict(metric=metric, prior=p, current=c, ratio=ratio, reason='count ratio outside band'))
    for cik, n in sorted(current.get('labelled_parent_rows', {}).items()):
        if n:
            flags.append(dict(metric='labelled_parent_rows.' + cik, prior=prior.get('labelled_parent_rows', {}).get(cik, 0),
                              current=n, ratio=None, reason='reporting-entity label in parent scope'))
    return flags


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--prior', required=True)
    parser.add_argument('--attempt', default='identity-01')
    parser.add_argument('--prior-attempt', default='identity-01')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--max-ratio', type=float, default=2.0)
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    from pipeline.programme.runner import candidate_path
    current = compute_footprint(candidate_path(args.candidate) / 'attempts' / args.attempt / 'bundle')
    prior = compute_footprint(candidate_path(args.prior) / 'attempts' / args.prior_attempt / 'bundle')
    flags = compare_footprints(current, prior, args.max_ratio)
    result = dict(candidate=args.candidate, prior=args.prior, current=current, prior_footprint=prior,
                  flags=flags, status='PASS' if not flags else 'FLAGGED')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    print(result['status'], len(flags), 'flags')
    for f in flags:
        print('  ', f['metric'], f['prior'], '->', f['current'], f['reason'])
    if flags and not args.report_only:
        sys.exit(1)


if __name__ == '__main__':
    main()
