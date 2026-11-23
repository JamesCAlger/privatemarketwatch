"""Exact, reviewed source-context tranche identities, opt-in per filer.

These keys describe positions, never borrowers. A mapped row is isolated from
unmapped rows so an intermediate unreviewed row cannot join distinct tranches.
No published columns or source identifiers are rewritten.
"""
from __future__ import annotations

import duckdb
import pandas as pd

from pipeline.source_encodings import load_encodings


def parse_context_identity(value: str) -> tuple[str, str, str]:
    source, key = value.split(" => ", 1)
    accession, context = source.split(" ", 1)
    if not key.strip():
        raise ValueError("Position identity key cannot be blank")
    return accession, context, key.strip()


def scoped_declarations(frame: pd.DataFrame, encodings=None) -> list[tuple[str, str, str, str]]:
    """Canonical declarations for prepared BDC funds, independent of order."""
    encodings = load_encodings() if encodings is None else encodings
    rows = frame.loc[frame.source.eq("bdc")] if "source" in frame else frame
    ciks = set(rows.cik.astype(str).str.replace(r"[^0-9]", "", regex=True).str.zfill(10).unique())
    return sorted((cik, *parse_context_identity(value)) for cik in ciks
                  for value in encodings.get(cik, {}).get("position_identity_contexts", []))


def context_identity_keys(frame: pd.DataFrame, encodings=None) -> dict[int, str]:
    """Resolve reviewed rows with a SQL join; returned IDs are frame offsets."""
    encodings = load_encodings() if encodings is None else encodings
    declarations = []
    for cik, encoding in encodings.items():
        for value in encoding.get("position_identity_contexts", []):
            accession, context, key = parse_context_identity(value)
            declarations.append((cik, accession, context, cik + ":" + key))
    if not declarations or frame.empty:
        return {}
    required = {"cik", "accession_number", "src_context_id"}
    if not required.issubset(frame.columns):
        configured = {row[0] for row in declarations}
        if "cik" in frame and frame.cik.astype(str).str.zfill(10).isin(configured).any():
            raise ValueError("Reviewed position identities require accession and source context provenance")
        return {}
    declared = pd.DataFrame(declarations, columns=["cik", "accession", "context", "identity_key"])
    if declared.duplicated(["cik", "accession", "context"]).any():
        raise ValueError("A source context has more than one reviewed position identity")
    columns = sorted(required | ({"source"} if "source" in frame else set()))
    rows = frame[columns].reset_index(drop=True).copy()
    rows["uid"] = range(len(rows))
    with duckdb.connect() as con:
        con.register("rows", rows)
        con.register("declared", declared)
        result = con.execute("""
            SELECT r.uid, d.identity_key FROM rows r JOIN declared d
              ON lpad(CAST(r.cik AS VARCHAR), 10, '0') = d.cik
             AND CAST(r.accession_number AS VARCHAR) = d.accession
             AND CAST(r.src_context_id AS VARCHAR) = d.context
        """ + (" WHERE r.source = 'bdc'" if "source" in rows else "") + " ORDER BY r.uid").fetchall()
    return {int(uid): key for uid, key in result}


def compatible(keys: dict[int, str], a: int | None, b: int | None) -> bool:
    """Both unreviewed or the same reviewed tranche; never cross the boundary."""
    return keys.get(a) == keys.get(b)


def adjacent_identity_pairs(frame: pd.DataFrame, keys: dict[int, str], scopes) -> list[tuple[int, int]]:
    """Unique equal-key rows in adjacent quarters, within accounting scope.

    Ambiguous duplicate rows in a quarter fail closed, including comparative
    contexts. A key never licenses same-quarter or missing-quarter joins.
    """
    if not keys:
        return []
    reviewed = frame.iloc[list(keys)][["cik", "source", "report_date"]].copy()
    reviewed["uid"] = list(keys)
    reviewed["identity_key"] = list(keys.values())
    reviewed["scope"] = [scopes[uid] for uid in keys]
    with duckdb.connect() as con:
        con.register("reviewed", reviewed)
        ambiguous = con.execute("""
            SELECT identity_key FROM reviewed
            WHERE TRY_CAST(report_date AS DATE) IS NOT NULL
            GROUP BY cik, source, scope, identity_key,
                     date_trunc('quarter', TRY_CAST(report_date AS DATE))
            HAVING count(*) > 1 LIMIT 1
        """).fetchone()
        if ambiguous:
            raise ValueError("Reviewed position identity is ambiguous within a quarter: " + ambiguous[0])
        return [(int(a), int(b)) for a, b in con.execute("""
            WITH dated AS (
                SELECT *, date_trunc('quarter', TRY_CAST(report_date AS DATE)) AS quarter
                FROM reviewed
            ), unique_rows AS (
                SELECT * FROM dated WHERE quarter IS NOT NULL
                QUALIFY count(*) OVER (
                    PARTITION BY cik, source, scope, identity_key, quarter
                ) = 1
            )
            SELECT a.uid, b.uid FROM unique_rows a JOIN unique_rows b
              ON a.cik = b.cik AND a.source = b.source AND a.scope = b.scope
             AND a.identity_key = b.identity_key
             AND b.quarter = a.quarter + INTERVAL '3 months'
            ORDER BY a.uid, b.uid
        """).fetchall()]


def reconcile_financial_matches(matches, holdings, *, preserve_indices=(), emit_missing=False, endpoint_uids=None):
    """Enforce reviewed source identities in financial pairs, independently of PIDs.

    Private Tier-A aliases retain the member used to construct each endpoint.
    Exact value and, when needed, carried terms resolve candidates; ambiguous
    reviewed endpoints fail closed. Ordinary unreviewed pairs are unchanged.
    """
    keys = context_identity_keys(holdings)
    if not keys:
        return matches
    from pipeline.matching_contract import scope_sql

    mapped_funds = {str(holdings.iloc[i].cik).zfill(10) for i in keys}
    needed = {'cik', 'source', 'entity_name', 'report_date', 'accession_number', 'src_context_id',
              'bdc_investment_identifier', 'bdc_dimensions_raw', 'is_subsidiary', 'row_id',
              'issuer_name', 'fair_value', 'cost', 'principal_amount', 'interest_rate',
              'basis_spread', 'shares_held', 'index_classification', 'asset_category',
              'issuer_category', 'maturity_date', 'maturity_precision', 'instrument_description', 'coupon_type'}
    fund_mask = holdings.cik.astype(str).str.zfill(10).isin(mapped_funds)
    rows = holdings.loc[fund_mask,
                        sorted(needed & set(holdings.columns))].reset_index(drop=True).copy()
    rows['_review_original_uid'] = pd.RangeIndex(len(holdings))[fund_mask.to_numpy()]
    keys = context_identity_keys(rows)
    rows['_review_uid'] = range(len(rows))
    pairs = matches.loc[matches.cik.astype(str).str.zfill(10).isin(mapped_funds)].copy()
    pairs['_review_midx'] = pairs.index
    for side in ('begin', 'end'):
        alias = '_identity_' + side + '_name'
        if alias not in pairs:
            pairs[alias] = pairs[side + '_issuer_name']
        else:
            pairs[alias] = pairs[alias].fillna(pairs[side + '_issuer_name'])
        if side == 'end':
            forced = pairs.match_method.astype(str).str.endswith('_override')
            pairs.loc[forced, alias] = pairs.loc[forced, 'end_issuer_name']
    with duckdb.connect() as con:
        con.register('review_holdings', rows)
        con.register('review_pairs', pairs)
        scope = scope_sql(rows.columns, row_id='_review_uid')
        scopes = con.execute('SELECT ' + scope + ' FROM review_holdings ORDER BY _review_uid').fetchnumpy()
        scopes = next(iter(scopes.values()))
        licensed = adjacent_identity_pairs(rows, keys, scopes)
        candidates = []
        for side in ('begin', 'end'):
            raw = (' OR lower(trim(CAST(h.bdc_investment_identifier AS VARCHAR)))='
                   f'lower(trim(CAST(p._identity_{side}_name AS VARCHAR)))') if 'bdc_investment_identifier' in rows else ''
            # Any conflicting carried term vetoes a tie-break. Agreement in
            # several amounts never outvotes a contradictory spread or rate.
            terms = []
            for field in ('principal_amount', 'cost', 'basis_spread', 'interest_rate'):
                if field in rows and side + '_' + field in pairs:
                    terms.append(f"CASE WHEN TRY_CAST(p.{side}_{field} AS DOUBLE) IS NOT NULL AND TRY_CAST(h.{field} AS DOUBLE) IS NOT NULL AND TRY_CAST(p.{side}_{field} AS DOUBLE)!=TRY_CAST(h.{field} AS DOUBLE) THEN 1 ELSE 0 END")
            score = '+'.join(terms) or '0'
            candidates.extend(con.execute(f"""
                SELECT p._review_midx, '{side}', h._review_uid, {score} AS score
                FROM review_pairs p JOIN review_holdings h
                  ON lpad(CAST(p.cik AS VARCHAR),10,'0')=lpad(CAST(h.cik AS VARCHAR),10,'0')
                 AND p.source=h.source
                 AND TRY_CAST(p.{side}_report_date AS DATE)=TRY_CAST(h.report_date AS DATE)
                 AND TRY_CAST(p.{side}_fair_value AS DOUBLE)=TRY_CAST(h.fair_value AS DOUBLE)
                 AND (lower(trim(CAST(h.issuer_name AS VARCHAR)))=lower(trim(CAST(p._identity_{side}_name AS VARCHAR))){raw})
            """).fetchall())
    # The loop is restricted to candidate pairs touching the small opt-in map.
    candidate_frame = pd.DataFrame(candidates, columns=['midx', 'side', 'uid', 'score'])
    scoped_indices = set(candidate_frame.loc[candidate_frame.uid.isin(keys), 'midx'])
    candidates = candidate_frame.loc[candidate_frame.midx.isin(scoped_indices)].itertuples(index=False, name=None)
    selected = {}
    grouped = {}
    preserve = set(preserve_indices)
    for midx, side, uid, score in candidates:
        if midx in scoped_indices and midx not in preserve:
            grouped.setdefault((int(midx), side), []).append((int(uid), int(score)))
    if len(grouped) > 10000:
        raise ValueError('Reviewed financial reconciliation exceeds bounded candidate limit')
    for endpoint, choices in grouped.items():
        if len(choices) > 1:
            choices = [(uid, conflicts) for uid, conflicts in choices if conflicts == 0]
        choices = [uid for uid, _ in choices]
        if len(choices) != 1:
            if any(uid in keys for uid, _ in grouped[endpoint]):
                raise ValueError('Reviewed financial endpoint is ambiguous')
        else:
            selected[endpoint] = choices[0]
    from pipeline.matching_contract import bounds_sql
    from pipeline.position_matching import _maturity_veto_sql, _inst_subtype_sql
    possible = set(licensed)
    possible.update((selected[(midx, 'begin')], selected[(midx, 'end')])
                    for midx in scoped_indices
                    if (midx, 'begin') in selected and (midx, 'end') in selected)
    allowed = set()
    if possible:
        for field in ('maturity_date', 'instrument_description', 'principal_amount', 'basis_spread', 'index_classification'):
            if field not in rows:
                rows[field] = None
        low, high = bounds_sql(rows.columns)
        overlap = '(b.lo<=e.hi AND e.lo<=b.hi)'
        maturity = _maturity_veto_sql('b.lo', 'e.lo', 'b.pa', 'e.pa', 'b.bs', 'e.bs', overlap=overlap)
        with duckdb.connect() as con:
            con.register('source_rows', rows)
            con.register('possible', pd.DataFrame(sorted(possible), columns=['b', 'e']))
            con.execute(f'''CREATE VIEW reviewed_terms AS SELECT *, {low} AS lo,{high} AS hi,
                TRY_CAST(principal_amount AS DOUBLE) AS pa,TRY_CAST(basis_spread AS DOUBLE) AS bs,
                {_inst_subtype_sql('instrument_description')} AS subtype FROM source_rows''')
            allowed = set(con.execute(f'''SELECT p.b,p.e FROM possible p
                JOIN reviewed_terms b ON p.b=b._review_uid JOIN reviewed_terms e ON p.e=e._review_uid
                WHERE {maturity} AND (b.subtype IS NULL OR e.subtype IS NULL OR b.subtype=e.subtype)
                AND (coalesce(CAST(b.index_classification AS VARCHAR),'')='' OR coalesce(CAST(e.index_classification AS VARCHAR),'')=''
                     OR b.index_classification=e.index_classification)''').fetchall())
    result = matches.copy()
    valid_edges = set()
    drops = []
    fields = ('issuer_name', 'fair_value', 'cost', 'principal_amount', 'interest_rate', 'basis_spread', 'shares_held')
    metadata = ('index_classification', 'asset_category', 'issuer_category', 'maturity_date', 'coupon_type')
    changed_columns = {side + '_' + field for side in ('begin', 'end') for field in fields
                       if side + '_' + field in result and field in rows}
    changed_columns.update(field for field in metadata if field in result and field in rows)
    for column in changed_columns:
        result[column] = result[column].astype(object)
    priority = lambda midx: (not str(matches.at[midx, 'match_method']).endswith('_override'),
                             str(matches.at[midx, 'match_method']), midx)
    for midx in sorted(scoped_indices, key=priority):
        if midx in preserve:
            continue
        b, e = selected.get((midx, 'begin')), selected.get((midx, 'end'))
        if b not in keys and e not in keys:
            continue
        if (not compatible(keys, b, e) or b is None or e is None or scopes[b] != scopes[e] or (b, e) not in allowed):
            drops.append(midx)
            continue
        if (b, e) in valid_edges:
            drops.append(midx)
            continue
        valid_edges.add((b, e))
        if endpoint_uids is not None:
            endpoint_uids[(midx, 'begin')] = int(rows.iloc[b]['_review_original_uid'])
            endpoint_uids[(midx, 'end')] = int(rows.iloc[e]['_review_original_uid'])
        for side, uid in (('begin', b), ('end', e)):
            for field in fields:
                col = side + '_' + field
                if col in result and field in rows:
                    result.at[midx, col] = rows.iloc[uid][field]
        for field in metadata:
            if field in result and field in rows:
                result.at[midx, field] = rows.iloc[e][field]
    result = result.drop(index=drops)
    if emit_missing:
        additions = []
        for b, e in licensed:
            if (b, e) in valid_edges or (b, e) not in allowed:
                continue
            begin, end = rows.iloc[b], rows.iloc[e]
            item = {col: None for col in result.columns}
            for col in ('cik', 'source', 'entity_name'):
                if col in result and col in rows:
                    item[col] = end[col]
            for side, row in (('begin', begin), ('end', end)):
                date = pd.Timestamp(row.report_date)
                item[side + '_report_date'] = str(date.date())
                item[side + '_quarter'] = f'{date.year}q{date.quarter}'
                for field in fields:
                    if side + '_' + field in result and field in rows:
                        item[side + '_' + field] = row[field]
            for field in metadata:
                if field in result and field in rows:
                    item[field] = end[field]
            item.update(match_method='REVIEWED_context_identity', match_key=keys[b], match_score=1.0, span_months=3)
            additions.append(item)
        if additions:
            result = pd.concat([result, pd.DataFrame(additions)], ignore_index=True)
    return result
