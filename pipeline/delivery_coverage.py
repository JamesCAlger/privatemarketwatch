"""Delivery evidence census over the complete exported position history.

This measures published locators; it does not extract another HTML roster or
substitute evidence counts for coverage. DOM targets are checked separately by
the browser census. Large observation populations stay in DuckDB.
"""
from __future__ import annotations

from pathlib import Path

from pipeline.programme.artifacts import literal
from pipeline.programme.core import ContractError, read_json, sha

DISPLAY_FIELDS = ('fair_value', 'cost', 'interest_rate', 'maturity_date', 'gics_sub_industry')
NUMERIC_FIELDS = ('fair_value', 'cost', 'principal_amount', 'shares_held', 'interest_rate',
                  'basis_spread', 'pik_rate', 'pct_of_net_assets')
VERSION = 'delivery-coverage.v2'


def load_history(con, directory):
    """Verify every quarter payload before loading, including empty fund indexes."""
    root = Path(directory).resolve()
    manifest = read_json(root / 'manifest.json')
    files, inputs = [], {str(root / 'manifest.json'): sha(root / 'manifest.json')}
    expected, quarters = 0, []
    if len(set(manifest['funds'])) != len(manifest['funds']):
        raise ContractError('Repeated delivery fund')
    for cik in manifest['funds']:
        if len(cik) != 10 or not cik.isdigit():
            raise ContractError('Invalid delivery fund')
        index_path = root / cik / 'index.json'
        index = read_json(index_path)
        inputs[str(index_path)] = sha(index_path)
        if (index['cik'], index['release_id']) != (cik, manifest['release_id']):
            raise ContractError('History index identity differs')
        for quarter in index['quarters']:
            path = (root / quarter['path']).resolve()
            if path.parent != root / cik or path.name != quarter['quarter'] + '.json':
                raise ContractError('Unsafe quarter path')
            if str(path) in inputs or sha(path) != quarter['sha256']:
                raise ContractError('Repeated or changed history quarter')
            inputs[str(path)] = quarter['sha256']
            files.append(str(path))
            quarters.append((path.as_posix(), cik, quarter['quarter'], quarter['rows']))
            expected += quarter['rows']
            if quarter['rows']==0:
                payload=read_json(path)
                if (payload.get('release_id')!=manifest['release_id'] or payload.get('cik')!=cik
                        or payload.get('quarter')!=quarter['quarter'] or payload.get('rows')!=[]):
                    raise ContractError('Empty history quarter identity differs')
                matches=[item for item in manifest.get('source_statuses',[])
                    if item['cik']==cik and item['quarter']==quarter['quarter']]
                if len(matches)!=1 or payload.get('source_status')!=matches[0]:
                    raise ContractError('Empty history quarter source status differs')
    if not files:
        raise ContractError('Empty history cannot establish delivery coverage')
    # Parse declared types, avoiding sparse JSON/VARCHAR inference differences.
    from pipeline.output_schemas import OUTPUT_SCHEMAS
    schema = OUTPUT_SCHEMAS['private_markets_holdings.csv']
    row_type = 'STRUCT(' + ','.join('"' + k + '" ' + v for k, v in schema.items()) + ', evidence JSON)[]'
    con.execute('CREATE TEMP TABLE delivery_quarters(path VARCHAR,cik VARCHAR,quarter VARCHAR,rows BIGINT)')
    con.executemany('INSERT INTO delivery_quarters VALUES (?,?,?,?)', quarters)
    start = manifest.get('start', min(q[2] for q in quarters))
    end = manifest.get('end', max(q[2] for q in quarters))
    con.execute("""CREATE TEMP TABLE delivery_periods AS SELECT CAST(d+INTERVAL '3 months'-INTERVAL '1 day' AS DATE) AS quarter
        FROM generate_series(date_trunc('quarter',?::DATE),date_trunc('quarter',?::DATE),INTERVAL '3 months') u(d)""", [start,end])
    con.execute("CREATE TEMP TABLE delivery_rows AS SELECT replace(filename,chr(92),'/') AS payload_file,release_id AS payload_release,"
                "cik AS payload_cik,quarter AS payload_quarter,r.* FROM read_json(?,columns={"
                "release_id:'VARCHAR',cik:'VARCHAR',quarter:'VARCHAR',rows:" + literal(row_type) +
                "},filename=true,maximum_object_size=" + str(max(Path(p).stat().st_size for p in files) + 1) +
                "),unnest(rows) u(r)", [files])
    actual, distinct, wrong = con.execute("""SELECT count(*),count(DISTINCT row_id),
        count(*) FILTER(WHERE payload_release IS DISTINCT FROM ? OR payload_cik IS DISTINCT FROM cik
          OR payload_quarter IS DISTINCT FROM CAST(report_date AS VARCHAR)
          OR coalesce(row_id,'')='' OR coalesce(position_id,'')='') FROM delivery_rows""",
        [manifest['release_id']]).fetchone()
    if actual != expected or actual != distinct or actual != manifest['rows'] or wrong:
        raise ContractError('Delivery row population or identity differs')
    if con.execute('SELECT count(*) FROM delivery_rows WHERE report_date NOT IN (SELECT quarter FROM delivery_periods)').fetchone()[0]:
        raise ContractError('History row lies outside declared quarters')
    if con.execute("""SELECT count(*) FROM delivery_quarters q LEFT JOIN
        (SELECT payload_file,payload_cik,payload_quarter,count(*) AS rows FROM delivery_rows GROUP BY ALL) h
        ON h.payload_file=q.path WHERE coalesce(h.rows,0) IS DISTINCT FROM q.rows
          OR (q.rows>0 AND (h.payload_cik IS DISTINCT FROM q.cik OR h.payload_quarter IS DISTINCT FROM q.quarter))""").fetchone()[0]:
        raise ContractError('Delivery quarter population differs')
    return manifest, inputs


def build_census(con, release_id):
    """Validate graph identities, then expose field- and row-weighted populations.

    Every finite non-calculated displayed numeric value is in the reported-or-unknown
    denominator. Missing provenance never removes a value from that denominator.
    Money coverage requires both populated reported amount cells on a row and is
    weighted by absolute FV; numeric row coverage requires all displayed numeric
    cells. Per-field and all-eight-download-field results expose the wider gaps.
    """
    from pipeline.bdc_filings import CANONICAL_CONCEPT
    con.execute('CREATE TEMP TABLE delivery_concepts(field VARCHAR,concept VARCHAR)')
    con.executemany('INSERT INTO delivery_concepts VALUES (?,?)',
        [(field, CANONICAL_CONCEPT[field].lower()) for field in ('fair_value','cost','interest_rate','maturity_date')])
    con.execute("""CREATE TEMP TABLE delivery_evidence AS SELECT h.row_id,e.key AS field,e.value AS payload
        FROM delivery_rows h,json_each(h.evidence) e""")
    con.execute("""CREATE TEMP TABLE delivery_links AS
        SELECT row_id AS owner_row,field AS owner_field,row_id AS target_row,field AS target_field,payload
        FROM delivery_evidence WHERE json_extract_string(payload,'$.status')='direct'
        UNION ALL SELECT row_id,field,json_extract_string(payload,'$.donor_row_id'),'fair_value',
            json_extract(payload,'$.input') FROM delivery_evidence
        WHERE json_extract_string(payload,'$.status')='calculated'
          AND json_extract_string(payload,'$.input.status')='direct'""")
    from pipeline.delivery_calculations import validate_fx_evidence
    validate_fx_evidence(con)
    con.execute("""CREATE TEMP TABLE delivery_graph_errors AS
        SELECT e.row_id,e.field,'invalid_evidence_identity_or_status' AS reason FROM delivery_evidence e
        WHERE json_extract_string(payload,'$.release_id') IS DISTINCT FROM ?
          OR json_extract_string(payload,'$.row_id') IS DISTINCT FROM e.row_id
          OR json_extract_string(payload,'$.field') IS DISTINCT FROM e.field
          OR e.field NOT IN ('fair_value','cost','interest_rate','maturity_date','gics_sub_industry','gics_sector')
          OR coalesce(json_extract_string(payload,'$.status'),'') NOT IN ('direct','calculated','inferred','unavailable')
        UNION ALL SELECT e.row_id,e.field,'invalid_inference' FROM delivery_evidence e
        WHERE json_extract_string(payload,'$.status')='inferred' AND
          (e.field NOT IN ('gics_sector','gics_sub_industry') OR
           coalesce(json_extract_string(payload,'$.decision_id'),'')='' OR
           coalesce(json_extract_string(payload,'$.model'),'')='' OR
           coalesce(json_extract_string(payload,'$.input_text'),'')='' OR
           NOT regexp_full_match(coalesce(json_extract_string(payload,'$.taxonomy_sha256'),''),'[a-f0-9]{64}'))
        UNION ALL SELECT e.row_id,e.field,'invalid_cost_donor' FROM delivery_evidence e
          JOIN delivery_rows h USING(row_id)
          LEFT JOIN delivery_rows d ON d.row_id=json_extract_string(payload,'$.donor_row_id')
        WHERE e.field='cost' AND json_extract_string(payload,'$.status')='calculated' AND
          (json_extract_string(payload,'$.method') IS DISTINCT FROM 'first_observed_fv_proxy'
           OR h.cost_source IS DISTINCT FROM 'first_observed_fv_proxy'
           OR d.row_id IS NULL OR d.cik IS DISTINCT FROM h.cik
           OR d.position_id IS DISTINCT FROM h.position_id OR d.source IS DISTINCT FROM h.source
           OR CAST(d.report_date AS VARCHAR) IS DISTINCT FROM json_extract_string(payload,'$.donor_date')
           OR d.fair_value IS DISTINCT FROM h.cost
           OR json_extract_string(payload,'$.donor_release') IS DISTINCT FROM ?
           OR coalesce(json_extract_string(payload,'$.input.status'),'') NOT IN ('direct','unavailable','calculated')
           OR (json_extract_string(payload,'$.input.status')='calculated' AND NOT EXISTS(
               SELECT 1 FROM delivery_evidence de JOIN delivery_fx_checks fx USING(row_id)
               WHERE de.row_id=d.row_id AND de.field='fair_value' AND fx.valid
                 AND json_contains(de.payload,json_extract(e.payload,'$.input'))
                 AND json_contains(json_extract(e.payload,'$.input'),de.payload))))
        UNION ALL SELECT row_id,'fair_value','invalid_fx_calculation' FROM delivery_fx_checks WHERE NOT valid
        UNION ALL SELECT row_id,field,'unsupported_calculation_field' FROM delivery_evidence
          WHERE json_extract_string(payload,'$.status')='calculated' AND field NOT IN ('cost','fair_value')""",
        [release_id, release_id])
    con.execute("""CREATE TEMP TABLE delivery_link_errors AS
        SELECT l.owner_row AS row_id,l.owner_field AS field,'invalid_direct_link_identity' AS reason
        FROM delivery_links l LEFT JOIN delivery_rows h ON h.row_id=l.target_row
        LEFT JOIN delivery_concepts c ON c.field=l.target_field
        WHERE h.row_id IS NULL OR json_extract_string(payload,'$.release_id') IS DISTINCT FROM ?
          OR json_extract_string(payload,'$.row_id') IS DISTINCT FROM h.row_id
          OR json_extract_string(payload,'$.field') IS DISTINCT FROM l.target_field
          OR json_extract_string(payload,'$.accession_number') IS DISTINCT FROM h.accession_number
          OR NOT regexp_full_match(coalesce(json_extract_string(payload,'$.source_sha256'),''),'[a-f0-9]{64}')
          OR NOT regexp_full_match(coalesce(json_extract_string(payload,'$.href'),''),
              '/data/holdings_history/[0-9]{10}/sources/[0-9-]+-[a-f0-9]{16}[.]html#evidence-[a-f0-9]{24}')
          OR split_part(json_extract_string(payload,'$.href'),'#',1) IS DISTINCT FROM
              '/data/holdings_history/'||h.cik||'/sources/'||h.accession_number||'-'||
              left(json_extract_string(payload,'$.source_sha256'),16)||'.html'
          OR coalesce(json_extract_string(payload,'$.source_text'),'')=''
          OR (coalesce(json_extract_string(payload,'$.locator_kind'),'')<>'admitted_html_bridge'
              AND (json_extract_string(payload,'$.context_id') IS DISTINCT FROM h.src_context_id
                OR c.field IS NULL OR json_extract_string(payload,'$.concept') IS DISTINCT FROM
                  lower(coalesce(nullif(json_extract_string(TRY_CAST(h.src_facts AS JSON),'$.'||l.target_field||'.c'),''),c.concept))))
          OR (l.target_field IN ('fair_value','cost') AND json_extract_string(payload,'$.unit') IS DISTINCT FROM 'usd')
          OR (l.target_field='interest_rate' AND (h.interest_rate_kind IS DISTINCT FROM 'all_in'
              OR json_extract_string(payload,'$.unit') IS DISTINCT FROM 'pure'))
          OR (l.target_field='cost' AND h.cost_source IN ('derived_proxy','first_observed_fv_proxy'))
          OR (json_extract_string(payload,'$.locator_kind')='admitted_html_bridge' AND
              (l.target_field<>'maturity_date' OR NOT list_contains(string_split(coalesce(h.src_field_overrides,''),';'),
                json_extract_string(payload,'$.bridge_anchor'))))""", [release_id])
    fields = tuple(dict.fromkeys((*DISPLAY_FIELDS, 'gics_sector', *NUMERIC_FIELDS)))
    queries = []
    for field in fields:
        numeric = field in NUMERIC_FIELDS
        populated = f'isfinite(h."{field}")' if numeric else f'coalesce(CAST(h."{field}" AS VARCHAR),\'\')<>\'\''
        calculated = 'false'
        if field == 'fair_value':
            calculated = 'EXISTS(SELECT 1 FROM delivery_fx_checks fx WHERE fx.row_id=h.row_id AND fx.valid)'
        elif field == 'cost':
            calculated = "coalesce(h.cost_source,'') IN ('derived_proxy','first_observed_fv_proxy')"
        elif field == 'interest_rate':
            calculated = """coalesce(h.interest_rate_kind='cash'
                AND list_contains(string_split(coalesce(h.src_transforms,''),';'),'interest_rate:cash_plus_pik')
                AND isfinite(h.interest_rate_reported) AND isfinite(h.pik_rate)
                AND h.interest_rate=h.interest_rate_reported+h.pik_rate,false)"""
        inferred = "coalesce(json_extract_string(e.payload,'$.status')='inferred',false)" if field in ('gics_sector','gics_sub_industry') else 'false'
        reported = populated + ' AND NOT (' + calculated + ') AND NOT (' + inferred + ')'
        queries.append(f"""SELECT h.row_id,h.report_date,{literal(field)} AS field,
            {str(field in DISPLAY_FIELDS).lower()} AS displayed,{str(numeric).lower()} AS numeric,
            coalesce({populated},false) AS populated,coalesce({reported},false) AS reported,
            coalesce({populated} AND ({calculated}),false) AS calculated,
            coalesce({populated} AND ({inferred}),false) AS inferred,
            abs(h.fair_value) AS fv_weight,coalesce(json_extract_string(e.payload,'$.status'),'unavailable') AS status,
            e.payload IS NULL AS uses_default,
            NOT EXISTS(SELECT 1 FROM delivery_graph_errors g WHERE g.row_id=h.row_id AND g.field={literal(field)})
            AND NOT EXISTS(SELECT 1 FROM delivery_link_errors l WHERE l.row_id=h.row_id AND l.field={literal(field)}) AS valid
            FROM delivery_rows h LEFT JOIN delivery_evidence e ON e.row_id=h.row_id AND e.field={literal(field)}""")
    con.execute('CREATE TEMP TABLE delivery_fields AS ' + ' UNION ALL '.join(queries))


def verify_documents(con, directory, cache, output):
    """Hash the named source/rendition bytes and prepare exhaustive DOM requests.

    No HTML parsing or fact extraction occurs here. The browser uses only the
    already published anchors, text and inline attributes, never a table reader.
    """
    import json
    root, cache, output = Path(directory), Path(cache), Path(output)
    source_index = root / 'source_documents.json'
    inputs = {str(source_index): sha(source_index)}
    documents = read_json(source_index)
    paths, identities = [], set()
    con.execute('CREATE TEMP TABLE delivery_documents(cik VARCHAR,accession VARCHAR,source_sha256 VARCHAR,href VARCHAR)')
    # Group once. Rescanning half a million JSON locators for every filing is
    # quadratic in the document count and dominates a full-history evaluation.
    con.execute("""CREATE TEMP TABLE delivery_browser_requests AS SELECT doc_href,
        to_json(list(struct_pack(href:=href,source_text:=source_text,context_id:=context_id,
            concept:=concept,locator_kind:=locator_kind,reference_count:=reference_count) ORDER BY href)) AS request
        FROM (SELECT split_part(json_extract_string(payload,'$.href'),'#',1) AS doc_href,
            json_extract_string(payload,'$.href') AS href,
            json_extract_string(payload,'$.source_text') AS source_text,
            json_extract_string(payload,'$.context_id') AS context_id,
            json_extract_string(payload,'$.concept') AS concept,
            json_extract_string(payload,'$.locator_kind') AS locator_kind,count(*) AS reference_count
            FROM delivery_links GROUP BY ALL) GROUP BY doc_href""")
    for doc in documents:
        cik, accession = doc['cik'], doc['accession']
        if not cik.isdigit() or not accession or any(c not in '0123456789-' for c in accession):
            raise ContractError('Invalid source document identity')
        if (cik, accession) in identities:
            raise ContractError('Repeated source document identity')
        identities.add((cik, accession))
        if doc['status'] != 'rendered':
            continue
        source = cache / str(int(cik)) / (accession.replace('-', '') + '.html')
        filename = accession + '-' + doc['source_sha256'][:16] + '.html'
        rendition = root / cik / 'sources' / filename
        for path, expected in ((source, doc['source_sha256']), (rendition, doc['rendition_sha256'])):
            if not path.is_file() or sha(path) != expected:
                raise ContractError('Source or rendition bytes differ: ' + str(path))
            inputs[str(path)] = expected
        href = '/data/holdings_history/' + cik + '/sources/' + filename
        con.execute('INSERT INTO delivery_documents VALUES (?,?,?,?)', [cik, accession, doc['source_sha256'], href])
        # At most one request file per source document; SQL serializes link rows.
        selected = con.execute('SELECT request FROM delivery_browser_requests WHERE doc_href=?', [href]).fetchone()
        if selected and selected[0]:
            target = output / (cik + '-' + accession + '.json')
            target.write_text(selected[0] + '\n', encoding='utf-8')
            paths.append(dict(path=target.name,sha256=sha(target),href=href,rendition_sha256=doc['rendition_sha256']))
        if len(paths) % 50 == 0:
            print('Verified delivery source documents: ' + str(len(paths)), flush=True)
    con.execute("""INSERT INTO delivery_link_errors SELECT l.owner_row,l.owner_field,'unverified_source_document'
        FROM delivery_links l LEFT JOIN delivery_documents d ON d.source_sha256=json_extract_string(payload,'$.source_sha256')
          AND d.href=split_part(json_extract_string(payload,'$.href'),'#',1)
        WHERE d.href IS NULL""")
    con.execute("""UPDATE delivery_fields f SET valid=false WHERE EXISTS
        (SELECT 1 FROM delivery_link_errors e WHERE e.row_id=f.row_id AND e.field=f.field)""")
    return paths, inputs


def metrics(con):
    """Return every quarter as well as overall; an empty denominator is unknown."""
    per_field = con.execute("""SELECT CAST(report_date AS VARCHAR) AS quarter,field,displayed,
        count(*) AS rows,count(*) FILTER(WHERE populated) AS populated,
        count(*) FILTER(WHERE calculated) AS calculated_values,
        count(*) FILTER(WHERE inferred) AS inferred_values,
        count(*) FILTER(WHERE reported) AS reported_or_unknown,
        count(*) FILTER(WHERE reported AND status='direct' AND valid) AS highlighted,
        sum(fv_weight) FILTER(WHERE reported) AS reported_abs_fv,
        sum(fv_weight) FILTER(WHERE reported AND status='direct' AND valid) AS highlighted_abs_fv,
        count(*) FILTER(WHERE NOT valid) AS invalid_evidence
        FROM delivery_fields GROUP BY GROUPING SETS ((report_date,field,displayed),(field,displayed))
        ORDER BY quarter NULLS FIRST,field""").fetchdf().to_json(orient='records')
    con.execute("""CREATE TEMP TABLE delivery_row_coverage AS SELECT row_id,report_date,max(fv_weight) AS fv_weight,
        count(*) FILTER(WHERE displayed AND numeric AND reported) AS numeric_cells,
        count(*) FILTER(WHERE displayed AND numeric AND reported AND NOT(status='direct' AND valid)) AS numeric_gaps,
        count(*) FILTER(WHERE field IN ('fair_value','cost') AND reported) AS amount_cells,
        count(*) FILTER(WHERE field IN ('fair_value','cost') AND reported AND NOT(status='direct' AND valid)) AS amount_gaps
        FROM delivery_fields GROUP BY row_id,report_date""")
    rows = con.execute("""SELECT CAST(report_date AS VARCHAR) AS quarter,count(*) AS holdings_rows,
        count(*) FILTER(WHERE numeric_cells>0) AS numeric_rows,
        count(*) FILTER(WHERE numeric_cells>0 AND numeric_gaps=0) AS highlighted_numeric_rows,
        sum(fv_weight) FILTER(WHERE amount_cells>0) AS amount_abs_fv,
        sum(fv_weight) FILTER(WHERE amount_cells>0 AND amount_gaps=0) AS highlighted_amount_abs_fv,
        count(*) FILTER(WHERE amount_cells>0 AND fv_weight IS NULL) AS unknown_amount_weights
        FROM delivery_row_coverage GROUP BY GROUPING SETS ((report_date),()) ORDER BY quarter NULLS FIRST""").fetchall()
    coverage = []
    for quarter, holdings, numeric, highlighted, fv, linked_fv, unknown in rows:
        n = highlighted / numeric if numeric else None
        a = (linked_fv or 0) / fv if fv and not unknown else None
        coverage.append(dict(quarter=quarter,holdings_rows=holdings,numeric_rows=numeric,
            highlighted_numeric_rows=highlighted,amount_abs_fv=fv,highlighted_amount_abs_fv=linked_fv or 0,
            unknown_amount_weights=unknown,reported_numeric_highlight_row_coverage=n,
            reported_amount_highlight_fv_coverage=a,
            numeric_verdict='UNASSESSABLE' if n is None else 'PASS' if n>=.95 else 'FAIL',
            amount_verdict='UNASSESSABLE' if a is None else 'PASS' if a>=.99 else 'FAIL'))
    import json
    fields = json.loads(per_field)
    observed = {r['quarter'] for r in coverage}
    for (quarter,) in con.execute('SELECT CAST(quarter AS VARCHAR) FROM delivery_periods ORDER BY quarter').fetchall():
        if quarter in observed:
            continue
        coverage.append(dict(quarter=quarter,holdings_rows=0,numeric_rows=0,highlighted_numeric_rows=0,
            amount_abs_fv=None,highlighted_amount_abs_fv=0,unknown_amount_weights=0,
            reported_numeric_highlight_row_coverage=None,reported_amount_highlight_fv_coverage=None,
            numeric_verdict='UNASSESSABLE',amount_verdict='UNASSESSABLE'))
        for field in dict.fromkeys((*DISPLAY_FIELDS,'gics_sector',*NUMERIC_FIELDS)):
            fields.append(dict(quarter=quarter,field=field,displayed=field in DISPLAY_FIELDS,
                rows=0,populated=0,calculated_values=0,inferred_values=0,reported_or_unknown=0,highlighted=0,reported_abs_fv=None,
                highlighted_abs_fv=None,invalid_evidence=0))
    coverage.sort(key=lambda r:r['quarter'] or '')
    fields.sort(key=lambda r:(r['quarter'] or '',r['field']))
    return dict(version=VERSION,coverage=coverage,fields=fields,
        interpretation='Locator coverage only until the complete browser anchor census passes; not source-field accuracy',
        denominator='All finite reported-or-unknown displayed values; explicitly labelled cost proxies and '
        'evidenced cash-plus-PIK calculations excluded from reported-value coverage and counted separately. '
        'Each row needs every populated reported amount/numeric cell highlighted. Amount weighting is absolute row FV. '
        'Missing evidence never removes denominator rows. All eight downloadable numeric fields also reported separately.')
