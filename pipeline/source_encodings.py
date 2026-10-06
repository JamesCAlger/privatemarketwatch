"""Reviewed filer encodings shared by staging and accounting-scope consumers.

SQL operates on columns, not Python row loops. Only exact reviewed identifiers
and standalone reporting-entity suffixes are admitted. A borrower's name cannot
become a reporting entity by containing an entity label.
"""
from pathlib import Path
import json
import re


def load_encodings(wrapper_directory=None):
    if wrapper_directory is None:
        from pipeline.config import OVERRIDES_DIR
        wrapper_directory=OVERRIDES_DIR/'bdc_xbrl_wrappers'
    result={}
    for path in sorted(Path(wrapper_directory).glob('*.json')):
        wrapper=json.loads(path.read_text(encoding='utf-8'))
        encoding=wrapper.get('source_encodings')
        if encoding is None:
            continue
        if wrapper.get('schema_version')!='bdc-xbrl-wrapper.v3':
            raise ValueError('Source encodings require wrapper v3: '+str(path))
        if not isinstance(encoding,dict) or set(encoding)-{'cash_identifiers','reporting_entity_suffixes','reporting_entity_identifier_suffixes',
                'detached_schedule_labels','principal_usd_reference','legal_entity_members',
                'foreign_unit_values'}:
            raise ValueError('Invalid source encodings: '+str(path))
        cik=wrapper.get('cik','')
        if len(cik)!=10 or not cik.isdigit() or cik in result:
            raise ValueError('Invalid or duplicate encoding CIK: '+str(path))
        for key,values in encoding.items():
            if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v.strip() for v in values):
                raise ValueError('Invalid encoding values: '+str(path))
            if len(set(' '.join(v.lower().split()) for v in values))!=len(values):
                raise ValueError('Duplicate encoding values: '+str(path))
            if (key.startswith('reporting_entity_') or key=='detached_schedule_labels') and any('|' in v or '=' in v for v in values):
                raise ValueError('Reporting suffix must be one bare dimension segment: '+str(path))
            if key=='detached_schedule_labels' and len(values)!=1:
                raise ValueError('A filer has one detached-schedule label: '+str(path))
            if key=='legal_entity_members' and any(_member_mapping(v) is None for v in values):
                raise ValueError('Legal entity member must read "axis=Member -> label": '+str(path))
            if key=='foreign_unit_values' and values!=['reported_in_usd']:
                raise ValueError('The only admitted foreign unit reading is reported_in_usd: '+str(path))
            if key=='principal_usd_reference' and values!=['fred_h10']:
                raise ValueError('The only admitted principal FX reference is fred_h10: '+str(path))
        result[cik]=encoding
    return result


def _member_mapping(value):
    """('axis=member', 'label') from 'axis=Member -> Label', both normalised; None if malformed."""
    parts=[' '.join(p.lower().split()) for p in value.split('->')]
    if len(parts)!=2 or not all(parts):
        return None
    segment,label=parts
    if segment.count('=')!=1 or '|' in segment or '|' in label or '=' in label:
        return None
    return segment,label


def _literal(value):
    return "'"+value.replace("'","''")+"'"


def _normal(expression):
    return "lower(trim(regexp_replace(coalesce(CAST("+expression+" AS VARCHAR),''),'\\s+',' ','g')))"


def _cik_condition(expression,cik):
    return "lpad(regexp_replace(CAST("+expression+" AS VARCHAR),'[^0-9]','','g'),10,'0')="+_literal(cik)


def cash_identifier_expression(cik,identifier,encodings=None):
    """Exact full identifier match, restricted to its filing CIK."""
    configured=load_encodings() if encodings is None else encodings
    parts=[]
    for key,encoding in sorted(configured.items()):
        identifiers=encoding.get('cash_identifiers',[])
        if identifiers:
            values=','.join(_literal(' '.join(v.lower().split())) for v in identifiers)
            parts.append('('+_cik_condition(cik,key)+' AND '+_normal(identifier)+' IN ('+values+'))')
    return '('+' OR '.join(parts)+')' if parts else 'false'


def reporting_suffix_expression(cik,dimensions,encodings=None):
    """Return canonical members for exact bare segments after the first one."""
    configured=load_encodings() if encodings is None else encodings
    cases=[]
    for key,encoding in sorted(configured.items()):
        # A detached-schedule label is a reporting-entity segment this module
        # itself appends (tag_detached_schedules); it resolves like a filed one.
        labels=encoding.get('reporting_entity_suffixes',[])+encoding.get('detached_schedule_labels',[])
        legacy=encoding.get('reporting_entity_identifier_suffixes',[])
        members=[_member_mapping(v) for v in encoding.get('legal_entity_members',[])]
        if not labels and not legacy and not members:
            continue
        matched=[]
        # An explicit axis member after the identifier (for example
        # legalentityaxis=...JVLPMember) names the same reporting entity as the
        # reviewed label it maps to.
        for segment,label in members:
            later="string_split(coalesce(CAST("+dimensions+" AS VARCHAR),''),'|')[2:]"
            matched.append('CASE WHEN list_contains(list_transform('+later+',x -> '+_normal('x')+'),'+_literal(segment)+')'
                ' THEN ['+_literal(label)+'] ELSE []::VARCHAR[] END')
        if labels:
            values=','.join(_literal(' '.join(v.lower().split())) for v in labels)
            segments="string_split(coalesce(CAST("+dimensions+" AS VARCHAR),''),'|')[2:]"
            matched.append('list_filter(list_transform('+segments+',x -> '+_normal('x')+'),x -> x IN ('+values+'))')
        if legacy:
            # Reviewed legacy InvestmentIdentifierAxis forms (BCRED wrapper quirk
            # bcred_legacy_typed_reporting_portfolio): the portfolio label is its
            # own segment, separated from a non-empty borrower by a comma, by a
            # space-ordinal-space, or (2023-09-30 through 2024-03-31 only) by a
            # bare single space with no comma/digit/space immediately before it --
            # at the end, or (2023-03-31 only) at the start. Borrower legal-form
            # words are NOT required: LLLP, LLP, Co., S.a r.l., S.p.A, bare Bidco
            # and plain names all appear in reviewed contexts.
            # Admitting the bare-space form makes BOTH guards below load-bearing
            # for that form specifically (they were dead against comma/ordinal
            # alone, which is why an earlier pass at this dropped them): without
            # the own-interest guard, the fund's own "BCRED Emerald JV LP" would
            # match the bare-space alternative; without the trailing joint guard,
            # "Acme LLC and Verdelite JV LP" would too. The leading-form joint
            # veto is unrelated and was already needed, because
            # "Emerald JV LP, and Acme LLC" matches the leading pattern.
            # RE2: no lookaround.
            member=_normal("split_part(CAST("+dimensions+" AS VARCHAR),'|',1)")
            for label in legacy:
                label=' '.join(label.lower().split())
                lab=re.escape(label)
                terminal=r'^investmentidentifieraxis=.+?(?:,\s*|,?\s+[0-9]+\s+)'+lab+r'(?: [0-9]+)?$'
                bare=r'^investmentidentifieraxis=.+[^,0-9 ] '+lab+r'(?: [0-9]+)?$'
                leading=r'^investmentidentifieraxis='+lab+r',\s*.+$'
                own_interest=r'^investmentidentifieraxis=[a-z]+ '+lab+r'(?: [0-9]+)?$'
                leading_joint=r'^investmentidentifieraxis='+lab+r',\s*and\b'
                trailing_joint=r'\band,?\s+'+lab+r'(?: [0-9]+)?$'
                matched.append('CASE WHEN (regexp_matches('+member+','+_literal(terminal)+') OR regexp_matches('+member+','+_literal(bare)+') OR regexp_matches('+member+','+_literal(leading)+'))'
                    ' AND NOT regexp_matches('+member+','+_literal(own_interest)+')'
                    ' AND NOT regexp_matches('+member+','+_literal(leading_joint)+')'
                    ' AND NOT regexp_matches('+member+','+_literal(trailing_joint)+')'
                    ' THEN ['+_literal(label)+'] ELSE []::VARCHAR[] END')
        matching='list_concat('+','.join(matched)+')' if len(matched)>1 else matched[0]
        members="array_to_string(list_transform(list_sort(list_distinct("+matching+")),x -> 'reporting_entity='||x),'|')"
        cases.append('WHEN '+_cik_condition(cik,key)+" THEN coalesce("+members+",'')")
    return "CASE "+' '.join(cases)+" ELSE '' END" if cases else "''"


# Position contexts of one schedule are numbered contiguously by the filing
# software; a second schedule in the notes starts far later. HPS 0001838126:
# largest gap inside the main schedule 4, gap to the joint-venture schedule
# 1,353 to 2,699 across 2023-12-31..2026-03-31 (investigation 2026-10-05).
DETACHED_MIN_CONTEXT_GAP=200


def derived_segment_pattern(encodings=None):
    """Regex for a trailing detached-schedule segment appended by this module, or None.

    Consumers that key on the FILED dimension member (for example the inline-XBRL
    field overlay) must remove the pipeline-derived label first.
    """
    configured=load_encodings() if encodings is None else encodings
    labels=sorted({' '.join(v.split()) for e in configured.values() for v in e.get('detached_schedule_labels',[])})
    if not labels:
        return None
    return r'(?i)\s*\|\s*(?:'+'|'.join(re.escape(l).replace(r'\ ',r'\s+') for l in labels)+r')\s*$'


def tag_detached_schedules(con,table='bdc_raw',encodings=None):
    """Mark a filer's detached position schedules as their own reporting entity.

    Only for filers whose wrapper declares ``detached_schedule_labels``. Within
    one filing and period, position contexts are ordered by the number ending
    ``src_context_id``; every context from the first jump of at least
    DETACHED_MIN_CONTEXT_GAP onward gets the label appended to ``dimensions_raw``
    as a bare segment. The accounting scope then reads it as an underlying
    schedule: the rows are retained and flagged, never deleted. A row inside the
    main block that merely lacks a filer tag is left alone. Contexts without a
    trailing number are ignored. Returns rows tagged per CIK.
    """
    configured=load_encodings() if encodings is None else encodings
    counts={}
    present={row[0] for row in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=?",[table]).fetchall()}
    for key,encoding in sorted(configured.items()):
        labels=encoding.get('detached_schedule_labels',[])
        if not labels:
            continue
        if not {'cik','accession_number','period','src_context_id','dimensions_raw'}<=present:
            # Rows without source contexts (HTML-extracted periods) carry no order to read.
            counts[key]=0
            continue
        label=' '.join(labels[0].split())
        suffix=' | '+label
        scope=_cik_condition('cik',key)
        period="coalesce(CAST(period AS VARCHAR)[:10],'')"
        con.execute("""CREATE OR REPLACE TEMP TABLE _detached_contexts AS
            WITH positions AS (
                SELECT DISTINCT CAST(accession_number AS VARCHAR) AS accession,"""+period+""" AS period_key,
                    CAST(src_context_id AS VARCHAR) AS context,
                    TRY_CAST(regexp_extract(CAST(src_context_id AS VARCHAR),'([0-9]+)$',1) AS BIGINT) AS ordinal
                FROM """+table+""" WHERE """+scope+"""),
            gaps AS (
                SELECT *,ordinal-lag(ordinal) OVER (PARTITION BY accession,period_key ORDER BY ordinal) AS gap
                FROM positions WHERE ordinal IS NOT NULL),
            starts AS (
                SELECT accession,period_key,min(ordinal) FILTER (WHERE gap>=?) AS first_detached
                FROM gaps GROUP BY ALL)
            SELECT accession,period_key,context FROM gaps JOIN starts USING(accession,period_key)
            WHERE ordinal>=first_detached""",[DETACHED_MIN_CONTEXT_GAP])
        before=con.execute("SELECT count(*) FROM "+table+" WHERE "+scope+
            " AND ends_with(coalesce(CAST(dimensions_raw AS VARCHAR),''),?)",[suffix]).fetchone()[0]
        con.execute("UPDATE "+table+" SET dimensions_raw=coalesce(CAST(dimensions_raw AS VARCHAR),'')||? "
            "WHERE "+scope+" AND NOT ends_with(coalesce(CAST(dimensions_raw AS VARCHAR),''),?) "
            "AND (CAST(accession_number AS VARCHAR),"+period+",CAST(src_context_id AS VARCHAR)) IN "
            "(SELECT (accession,period_key,context) FROM _detached_contexts)",[suffix,suffix])
        after=con.execute("SELECT count(*) FROM "+table+" WHERE "+scope+
            " AND ends_with(coalesce(CAST(dimensions_raw AS VARCHAR),''),?)",[suffix]).fetchone()[0]
        con.execute("DROP TABLE _detached_contexts")
        counts[key]=after-before
    return counts
