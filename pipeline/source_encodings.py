"""Reviewed filer encodings shared by staging and accounting-scope consumers.

SQL operates on columns, not Python row loops. Only exact reviewed identifiers
and standalone reporting-entity suffixes are admitted. A borrower's name cannot
become a reporting entity by containing an entity label.
"""
from pathlib import Path
import json
import re


_UNTAGGED_VALUE_RE=re.compile('[0-9]{10}-[0-9]{2}-[0-9]{6} [^ ]+ (fair_value|cost|principal_amount) -?[0-9]+(\\.[0-9]+)?( [A-Z]{3})?')
_ACCESSION_RE=re.compile('[0-9]{10}-[0-9]{2}-[0-9]{6}')
_CONTEXT_IDENTIFIER_RE=re.compile('[0-9]{10}-[0-9]{2}-[0-9]{6} [^ ]+ => .*[A-Za-z].*')
_MISDATED_CONTEXT_RE=re.compile('[0-9]{10}-[0-9]{2}-[0-9]{6} [^ ]+ [0-9]{4}-[0-9]{2}-[0-9]{2} -> [0-9]{4}-[0-9]{2}-[0-9]{2}')


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
                'foreign_unit_values','filed_rate_reading','pik_only_tag_reading','rate_only_contexts',
                'reference_rate_columns','reference_rate_codes','printed_margin_reading',
                'equity_instrument_labels','unspecified_reference_labels','page_labelled_contexts','misdated_contexts','investments_total_excludes','fair_value_concepts','untagged_values','context_identifiers','unfunded_rows','schedule_row_tags','rate_tag_reading','untagged_pik','par_tagged_as_units','units_tagged_as_par','cost_in_two_units','industry_columns',
                'pct_tagged_as_ratio','section_total_reading','investments_total_includes_cash','bracketed_unsigned_values',
                'whole_dollar_scale_filings','net_assets_concepts','printed_rows_without_context'}:
            raise ValueError('Invalid source encodings: '+str(path))
        cik=wrapper.get('cik','')
        if len(cik)!=10 or not cik.isdigit() or cik in result:
            raise ValueError('Invalid or duplicate encoding CIK: '+str(path))
        for key,values in encoding.items():
            if key=='printed_rows_without_context':
                # Rows printed with no XBRL context, declared from the printed line (owner ruling
                # 2026-10-18, OVR-T8Y-R2; pipeline.printed_rows). Objects, not strings.
                from pipeline.printed_rows import entry_errors
                if not isinstance(values,list) or not values:
                    raise ValueError('printed_rows_without_context lists declared rows: '+str(path))
                for entry in values:
                    errors=entry_errors(entry)
                    if errors:
                        raise ValueError('Invalid printed row ('+'; '.join(errors)+'): '+str(path))
                seen=[(e['accession'],' '.join(e['issuer'].lower().split()),' '.join(e['instrument'].lower().split())) for e in values]
                if len(set(seen))!=len(seen):
                    raise ValueError('Duplicate printed row: '+str(path))
                continue
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
            if key=='filed_rate_reading' and values not in (['all_in'],['cash_leg']):
                raise ValueError('Filed rate reading must be all_in or cash_leg: '+str(path))
            if key=='units_tagged_as_par' and any(not _ACCESSION_RE.fullmatch(v) for v in values):
                raise ValueError('units_tagged_as_par lists accession numbers: '+str(path))
            if key=='pct_tagged_as_ratio' and any(not _ACCESSION_RE.fullmatch(v) for v in values):
                raise ValueError('pct_tagged_as_ratio lists accession numbers: '+str(path))
            if key=='bracketed_unsigned_values' and any(not _ACCESSION_RE.fullmatch(v) for v in values):
                raise ValueError('bracketed_unsigned_values lists accession numbers: '+str(path))
            if key=='net_assets_concepts' and any(not re.fullmatch('[A-Za-z][A-Za-z0-9]*',v) for v in values):
                raise ValueError('A net-assets concept is one local name, no prefix: '+str(path))
            if key=='whole_dollar_scale_filings' and any(not _ACCESSION_RE.fullmatch(v) for v in values):
                raise ValueError('whole_dollar_scale_filings lists accession numbers: '+str(path))
            if key=='par_tagged_as_units' and any(v not in ('rows_near_cost','rows_within_twice_cost','rated_rows_near_cost') and not _ACCESSION_RE.fullmatch(v) for v in values):
                raise ValueError('par_tagged_as_units lists accession numbers or a row mode: '+str(path))
            if key=='rate_only_contexts' and values!=['adopt_adjacent']:
                raise ValueError('The only admitted rate-only context handling is adopt_adjacent: '+str(path))
            if key=='pik_only_tag_reading' and values not in (['coupon'],['margin'],['coupon','margin']):
                raise ValueError('PIK-only tag reading must be coupon, margin, or coupon then margin: '+str(path))
            if key=='reference_rate_codes' and not _codes_are_unambiguous(values):
                raise ValueError('Reference rate code must read "CODE=BENCHMARK", optionally "to" or "from" a date, '
                    'with one meaning per code on any date: '+str(path))
            if key=='printed_margin_reading' and values!=['cash_plus_pik']:
                raise ValueError('The only admitted printed margin reading is cash_plus_pik: '+str(path))
            if key=='unspecified_reference_labels' and not encoding.get('reference_rate_columns'):
                raise ValueError('Unspecified reference labels need reference_rate_columns: '+str(path))
            if key=='printed_margin_reading' and not encoding.get('reference_rate_columns'):
                raise ValueError('A printed margin reading needs reference_rate_columns: '+str(path))
            if key=='page_labelled_contexts' and any(not re.fullmatch(r'[a-z0-9]+axis(?:\+[a-z0-9]+axis)*',v) for v in values):
                raise ValueError('A page-labelled context reads "axis+axis", lower-case local names: '+str(path))
            if key=='misdated_contexts' and any(not _MISDATED_CONTEXT_RE.fullmatch(v) for v in values):
                raise ValueError('A misdated context reads "ACCESSION CONTEXT YYYY-MM-DD -> YYYY-MM-DD": '+str(path))
            if key=='fair_value_concepts' and any(not re.fullmatch('[A-Za-z][A-Za-z0-9]*',v) for v in values):
                raise ValueError('A fair-value concept is one local name, no prefix: '+str(path))
            if key=='context_identifiers' and any(not _CONTEXT_IDENTIFIER_RE.fullmatch(v) for v in values):
                raise ValueError('A context identifier reads "ACCESSION CONTEXT => IDENTIFIER": '+str(path))
            if key=='untagged_values' and any(not _UNTAGGED_VALUE_RE.fullmatch(v) for v in values):
                raise ValueError('An untagged value reads "ACCESSION CONTEXT fair_value|cost|principal_amount NUMBER": '+str(path))
            if key=='schedule_row_tags' and set(values)-{'cost_or_percent_unrounded','cost_or_percent','quantity_or_percent','not_commitment_only'}:
                raise ValueError('A schedule row test is cost_or_percent_unrounded, cost_or_percent, quantity_or_percent or not_commitment_only: '+str(path))
            if key=='rate_tag_reading' and values not in (['coupon_with_margins'],['cash_rate_with_plain_spread']):
                raise ValueError('A rate tag reading is coupon_with_margins or cash_rate_with_plain_spread: '+str(path))
            if key=='untagged_pik' and values!=['none']:
                raise ValueError('The only admitted untagged PIK reading is none: '+str(path))
            if key=='unfunded_rows' and values!=['net_of_tagged_commitment']:
                raise ValueError('The only admitted unfunded row handling is net_of_tagged_commitment: '+str(path))
            # Cash-class rows (by issuer-name pattern) the filer counts inside its filed investments
            # total; read by the fund gate's totals comparison only (owner ruling 2026-10-17, D-202).
            if key=='investments_total_includes_cash':
                for v in values:
                    try:
                        re.compile(v)
                    except re.error:
                        raise ValueError('investments_total_includes_cash lists issuer-name patterns: '+str(path))
                if encoding.get('investments_total_excludes'):
                    raise ValueError('investments_total_includes_cash contradicts investments_total_excludes: '+str(path))
            if key=='investments_total_excludes' and values!=['cash_rows']:
                raise ValueError('The only admitted exclusion from the investments total is cash_rows: '+str(path))
            if key=='cost_in_two_units' and values!=['foreign_is_par']:
                raise ValueError('The only admitted reading of a cost in two units is foreign_is_par: '+str(path))
            if key=='foreign_unit_values' and values!=['reported_in_usd']:
                raise ValueError('The only admitted foreign unit reading is reported_in_usd: '+str(path))
            if key=='principal_usd_reference' and values!=['fred_h10']:
                raise ValueError('The only admitted principal FX reference is fred_h10: '+str(path))
            if key=='section_total_reading' and values!=['label_then_total']:
                raise ValueError('The only admitted section total reading is label_then_total: '+str(path))
        result[cik]=encoding
    return result


_CODE_RE=re.compile(r'([A-Za-z]{1,8})=([A-Z]{2,12})(?: (to|from) ([0-9]{4}-[0-9]{2}-[0-9]{2}))?')


def _codes_are_unambiguous(values):
    """Each entry parses, and a code defined more than once has one 'to' and one later 'from'."""
    parsed=[_CODE_RE.fullmatch(v) for v in values]
    if not all(parsed):
        return False
    by_code={}
    for match in parsed:
        by_code.setdefault(match.group(1).upper(),[]).append((match.group(3),match.group(4)))
    for bounds in by_code.values():
        if len(bounds)==1:
            continue
        ends=dict(bounds)
        if len(bounds)!=2 or set(ends)!={'to','from'} or ends['to']>=ends['from']:
            return False
    return True


def reference_rate_reading(cik,encodings=None,report_date=None):
    """The filer's own reference-rate column, or None: {'columns': header labels, 'codes': {code: benchmark}}.

    From the wrapper's ``reference_rate_columns`` (printed header labels, compared in lower case
    with single spaces) and ``reference_rate_codes`` ('SR=SOFR'). Codes alone name no column.
    A code dated 'to' or 'from' a day ('C=CDOR to 2024-03-31') applies only to report dates on
    that side of it, both ends included; without a ``report_date`` a dated code is not read.
    """
    configured=load_encodings() if encodings is None else encodings
    encoding=configured.get(re.sub(r'[^0-9]','',str(cik or '')).zfill(10),{})
    columns=frozenset(' '.join(v.lower().split()) for v in encoding.get('reference_rate_columns',[]))
    if not columns:
        return None
    day=str(report_date or '')[:10]
    codes={}
    for code,name,side,bound in (_CODE_RE.fullmatch(v).groups() for v in encoding.get('reference_rate_codes',[])):
        if side is None or (day and (day<=bound if side=='to' else day>=bound)):
            codes[code.upper()]=name
    # Labels the filer prints in that column that name no single benchmark (Ares 'Base Rate': "commonly
    # based on the Federal Funds Rate or the Prime Rate"). The loan floats; its benchmark is not stated.
    unspecified=frozenset(' '.join(v.lower().split()) for v in encoding.get('unspecified_reference_labels',[]))
    return {'columns':columns,'codes':codes,'unspecified':unspecified}


def industry_columns(cik,encodings=None):
    """Printed header labels (lower case, single spaces) of the column that holds each row's industry, or an empty set."""
    configured=load_encodings() if encodings is None else encodings
    encoding=configured.get(re.sub(r'[^0-9]','',str(cik or '')).zfill(10),{})
    return frozenset(' '.join(v.lower().split()) for v in encoding.get('industry_columns',[]))


_WHOLE_DOLLAR_CACHE={}


def whole_dollar_scale_filing(filing_meta,encodings=None):
    """True for a filing listed under the filer's whole_dollar_scale_filings: its schedule is printed in
    whole dollars and part of its facts carry decimals -3 (a scale they should not have), so the parser
    reads every investment fact at decimals 0 (pipeline.bdc_filings._normalize_mixed_decimals_monetary_facts).
    TCW Direct Lending VIII, 10-Q 2023-03-31. Off for every filing not listed."""
    cik=re.sub(r'[^0-9]','',str((filing_meta or {}).get('cik','') or '')).zfill(10)
    accession=str((filing_meta or {}).get('accession_number','') or '').strip()
    if encodings is None:
        if 'listed' not in _WHOLE_DOLLAR_CACHE:
            _WHOLE_DOLLAR_CACHE['listed']={c:frozenset(e['whole_dollar_scale_filings']) for c,e in load_encodings().items()
                                           if e.get('whole_dollar_scale_filings')}
        listed=_WHOLE_DOLLAR_CACHE['listed']
    else:
        listed={c:frozenset(e['whole_dollar_scale_filings']) for c,e in encodings.items() if e.get('whole_dollar_scale_filings')}
    return accession in listed.get(cik,frozenset())


def section_total_label_first(cik,encodings=None):
    """True where the wrapper sets section_total_reading label_then_total: the filer prints a section's
    own total as '<section> Total' ('First Lien Debt Total', APS BDC), which then closes the section."""
    configured=load_encodings() if encodings is None else encodings
    encoding=configured.get(re.sub(r'[^0-9]','',str(cik or '')).zfill(10),{})
    return encoding.get('section_total_reading')==['label_then_total']


def printed_margin_funds(encodings=None):
    """{cik10} whose wrappers set printed_margin_reading: the spread tag is the cash margin where the page prints cash and PIK apart."""
    configured=load_encodings() if encodings is None else encodings
    return {cik for cik,encoding in configured.items() if encoding.get('printed_margin_reading')}


def equity_instrument_expression(cik,instrument,encodings=None):
    """True where the row's whole instrument description is one of the fund's reviewed equity labels.

    For a filer that prints equity under a label no keyword recognises ("LLC interest",
    "Investment partnership") and tags the unit count as a principal, which the field heuristic
    then reads as a loan. An exact match on the fund's own label; a borrower name cannot trigger it."""
    configured=load_encodings() if encodings is None else encodings
    parts=[]
    for key,encoding in sorted(configured.items()):
        labels=encoding.get('equity_instrument_labels',[])
        if labels:
            values=','.join(_literal(' '.join(v.lower().split())) for v in labels)
            parts.append('('+_cik_condition(cik,key)+' AND '+_normal(instrument)+' IN ('+values+'))')
    return '('+' OR '.join(parts)+')' if parts else 'false'


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


def par_tagged_as_units_expression(cik,accession,encodings=None):
    """True for a row of a filing whose wrapper says the par column was tagged with the share-count concept.

    HPS Corporate Lending's 10-Q for 2026-03-31 tags the par of 696 of 835 positions as
    InvestmentOwnedBalanceShares; the filings before and after use the principal concept. Listed
    per filing (source_encodings.par_tagged_as_units), so another quarter is not touched."""
    configured=load_encodings() if encodings is None else encodings
    parts=[]
    for key,encoding in sorted(configured.items()):
        filings=[v for v in encoding.get('par_tagged_as_units',[]) if _ACCESSION_RE.fullmatch(v)]
        if filings:
            values=','.join(_literal(v) for v in filings)
            parts.append('('+_cik_condition(cik,key)+' AND trim(CAST('+accession+' AS VARCHAR)) IN ('+values+'))')
    return '('+' OR '.join(parts)+')' if parts else 'false'


def units_tagged_as_par_expression(cik,accession,encodings=None):
    """True for a row of a filing whose wrapper says equity unit counts were tagged with the principal concept.

    Blue Owl Credit Income's 10-Q for 2023-09-30 tags the units of 33 of its 44 equity rows as
    InvestmentOwnedBalancePrincipalAmount ('Minerva Holdco ... Series A Preferred Stock ... 100,000');
    the filings before and after use the share-count concept. Listed per filing."""
    configured=load_encodings() if encodings is None else encodings
    parts=[]
    for key,encoding in sorted(configured.items()):
        filings=encoding.get('units_tagged_as_par',[])
        if filings:
            values=','.join(_literal(v) for v in filings)
            parts.append('('+_cik_condition(cik,key)+' AND trim(CAST('+accession+' AS VARCHAR)) IN ('+values+'))')
    return '('+' OR '.join(parts)+')' if parts else 'false'


def pct_tagged_as_ratio_expression(cik,accession,encodings=None):
    """True for a row of a filing whose wrapper says percent of net assets is tagged as a ratio above 1.

    The shared row rule multiplies a tagged percent by 100 only up to 0.50, so a ratio between 0.5 and 50
    is published as if it were already in percent. Ares Core Infrastructure Fund's first two filings hold
    one levered position each: printed '224.22 %', tagged 2.2422 (10-Q 2024-09-30); printed '216.77 %',
    tagged 2.1677 (10-K 2024-12-31). Listed per filing."""
    configured=load_encodings() if encodings is None else encodings
    parts=[]
    for key,encoding in sorted(configured.items()):
        filings=encoding.get('pct_tagged_as_ratio',[])
        if filings:
            values=','.join(_literal(v) for v in filings)
            parts.append('('+_cik_condition(cik,key)+' AND trim(CAST('+accession+' AS VARCHAR)) IN ('+values+'))')
    return '('+' OR '.join(parts)+')' if parts else 'false'


def par_tagged_as_units_rows_expression(cik,encodings=None,mode='rows_near_cost'):
    """True for a fund whose wrapper says single rows tag their par as a share count ('rows_near_cost').

    BCRED's CLO subordinated notes, Blue Owl's Pluralsight loans and others carry the par under
    InvestmentOwnedBalanceShares in filings that otherwise use the principal concept. The caller
    takes the count as the par only where it lies near the row's cost, so a count filed at
    another scale or in another currency is left alone and stays a finding."""
    configured=load_encodings() if encodings is None else encodings
    parts=[_cik_condition(cik,key) for key,encoding in sorted(configured.items())
        if mode in encoding.get('par_tagged_as_units',[])]
    return '('+' OR '.join(parts)+')' if parts else 'false'


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
                # After a comma the filer also misspells the label with the ordinal fused into it:
                # 'Emerald JV LP2', 'Emerald JV LP. 2', 'Verdelite JV 2LP 1' (2026-10-06, decision
                # D-023). Only the comma form is loosened; a comma before the label is what keeps the
                # fund's own 'BCRED Emerald JV LP' interest out.
                head,_,last=label.rpartition(' ')
                loose=(re.escape(head)+' [0-9]?' if head else '')+re.escape(last)+r'\.?'
                misspelled=r'^investmentidentifieraxis=.+?,\s*'+loose+r'(?: ?[0-9]+)?$'
                terminal=r'^investmentidentifieraxis=.+?(?:,\s*|,?\s+[0-9]+\s+)'+lab+r'(?: [0-9]+)?$'
                bare=r'^investmentidentifieraxis=.+[^,0-9 ] '+lab+r'(?: [0-9]+)?$'
                leading=r'^investmentidentifieraxis='+lab+r',\s*.+$'
                own_interest=r'^investmentidentifieraxis=[a-z]+ '+lab+r'(?: [0-9]+)?$'
                leading_joint=r'^investmentidentifieraxis='+lab+r',\s*and\b'
                trailing_joint=r'\band,?\s+'+loose+r'(?: ?[0-9]+)?$'
                matched.append('CASE WHEN (regexp_matches('+member+','+_literal(terminal)+') OR regexp_matches('+member+','+_literal(misspelled)+') OR regexp_matches('+member+','+_literal(bare)+') OR regexp_matches('+member+','+_literal(leading)+'))'
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


RATE_FIELDS=('interest_rate','basis_spread','pik_rate')


def adopt_rate_only_contexts(con,table='bdc_raw',encodings=None):
    """Join a filer's rate facts to the position they belong to when they sit on their own context.

    Only for filers whose wrapper sets ``rate_only_contexts`` to ``['adopt_adjacent']``. Ares files
    some loans with the value on one context and the rate, spread and PIK on the neighbouring
    one, under a slightly different member name. A pair needs, within one filing and period:
    a context with rate facts and no value, cost or principal; a context with a value and a
    principal and no rate facts; context numbers that differ by one; the same first 16 letters
    and digits of the identifier; and no second candidate on either side under that key. The
    value row takes the rate fields (named in ``dedupe_filled_fields``, with the facts merged
    into ``src_facts``) and the rate-only row is removed. Returns rows joined per CIK.
    """
    configured=load_encodings() if encodings is None else encodings
    counts={}
    present={row[0] for row in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=?",[table]).fetchall()}
    needed={'cik','accession_number','period','src_context_id','investment_identifier','fair_value','cost',
        'principal_amount','src_facts','dedupe_filled_fields',*RATE_FIELDS}
    for key,encoding in sorted(configured.items()):
        if not encoding.get('rate_only_contexts'):
            continue
        if not needed<=present:
            counts[key]=0
            continue
        scope=_cik_condition('cik',key)
        blank=lambda name: "nullif(trim(CAST("+name+" AS VARCHAR)),'') IS NULL"
        any_rate=' OR '.join('NOT ('+blank(name)+')' for name in RATE_FIELDS)
        no_rate=' AND '.join(blank(name) for name in RATE_FIELDS)
        con.execute("""CREATE OR REPLACE TEMP TABLE _rate_pairs AS
            WITH base AS (
                SELECT CAST(accession_number AS VARCHAR) AS accession,coalesce(CAST(period AS VARCHAR)[:10],'') AS period_key,
                    CAST(src_context_id AS VARCHAR) AS context,
                    TRY_CAST(regexp_extract(CAST(src_context_id AS VARCHAR),'([0-9]+)$',1) AS BIGINT) AS ordinal,
                    left(regexp_replace(lower(CAST(investment_identifier AS VARCHAR)),'[^a-z0-9]','','g'),16) AS issuer_key,
                    ("""+blank('fair_value')+" AND "+blank('cost')+" AND "+blank('principal_amount')+" AND ("+any_rate+""")) AS rate_only,
                    (NOT ("""+blank('fair_value')+") AND NOT ("+blank('principal_amount')+") AND "+no_rate+""") AS value_only,
                    """+','.join('CAST('+name+' AS VARCHAR) AS '+name for name in RATE_FIELDS)+""",CAST(src_facts AS VARCHAR) AS facts
                FROM """+table+" WHERE "+scope+"""),
            givers AS (SELECT *,count(*) OVER (PARTITION BY accession,period_key,issuer_key) AS n FROM base WHERE rate_only),
            takers AS (SELECT *,count(*) OVER (PARTITION BY accession,period_key,issuer_key) AS n FROM base WHERE value_only)
            SELECT t.accession,t.period_key,t.context AS taker,g.context AS giver,g.facts AS giver_facts,
                """+','.join('g.'+name+' AS '+name for name in RATE_FIELDS)+"""
            FROM givers g JOIN takers t USING(accession,period_key,issuer_key)
            WHERE g.n=1 AND t.n=1 AND length(g.issuer_key)>=8 AND abs(g.ordinal-t.ordinal)=1""")
        joined=con.execute("SELECT count(*) FROM _rate_pairs").fetchone()[0]
        if joined:
            filled="concat_ws(',',"+','.join("CASE WHEN nullif(trim(p."+name+"),'') IS NOT NULL THEN '"+name+"' END"
                for name in RATE_FIELDS)+")"
            match=(scope+" AND CAST("+table+".accession_number AS VARCHAR)=p.accession"
                " AND coalesce(CAST("+table+".period AS VARCHAR)[:10],'')=p.period_key")
            con.execute("UPDATE "+table+" SET "+','.join(name+"=p."+name for name in RATE_FIELDS)+","
                "dedupe_filled_fields=concat_ws(',',nullif(trim(CAST("+table+".dedupe_filled_fields AS VARCHAR)),''),"+filled+"),"
                "src_facts=CAST(json_merge_patch(coalesce(TRY_CAST(nullif(trim(CAST("+table+".src_facts AS VARCHAR)),'') AS JSON),'{}'::JSON),"
                "coalesce(TRY_CAST(nullif(trim(p.giver_facts),'') AS JSON),'{}'::JSON)) AS VARCHAR) "
                "FROM _rate_pairs p WHERE "+match+" AND CAST("+table+".src_context_id AS VARCHAR)=p.taker")
            con.execute("DELETE FROM "+table+" USING _rate_pairs p WHERE "+match+
                " AND CAST("+table+".src_context_id AS VARCHAR)=p.giver")
        con.execute("DROP TABLE _rate_pairs")
        counts[key]=joined
    return counts
