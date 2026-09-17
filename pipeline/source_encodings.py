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
        if not isinstance(encoding,dict) or set(encoding)-{'cash_identifiers','reporting_entity_suffixes','reporting_entity_identifier_suffixes'}:
            raise ValueError('Invalid source encodings: '+str(path))
        cik=wrapper.get('cik','')
        if len(cik)!=10 or not cik.isdigit() or cik in result:
            raise ValueError('Invalid or duplicate encoding CIK: '+str(path))
        for key,values in encoding.items():
            if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v.strip() for v in values):
                raise ValueError('Invalid encoding values: '+str(path))
            if len(set(' '.join(v.lower().split()) for v in values))!=len(values):
                raise ValueError('Duplicate encoding values: '+str(path))
            if key.startswith('reporting_entity_') and any('|' in v or '=' in v for v in values):
                raise ValueError('Reporting suffix must be one bare dimension segment: '+str(path))
        result[cik]=encoding
    return result


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
        labels=encoding.get('reporting_entity_suffixes',[])
        legacy=encoding.get('reporting_entity_identifier_suffixes',[])
        if not labels and not legacy:
            continue
        matched=[]
        if labels:
            values=','.join(_literal(' '.join(v.lower().split())) for v in labels)
            segments="string_split(coalesce(CAST("+dimensions+" AS VARCHAR),''),'|')[2:]"
            matched.append('list_filter(list_transform('+segments+',x -> '+_normal('x')+'),x -> x IN ('+values+'))')
        if legacy:
            # Reviewed legacy InvestmentIdentifierAxis forms (BCRED wrapper quirk
            # bcred_legacy_typed_reporting_portfolio): the portfolio label is its
            # own segment, separated from a non-empty borrower by a comma or by a
            # space-ordinal-space, at the end or (2023-03-31 only) at the start.
            # Borrower legal-form words are NOT required: LLLP, LLP, Co., S.a r.l.,
            # S.p.A, bare Bidco and plain names all appear in reviewed contexts.
            # The separator requirement alone keeps the fund's own LP interest
            # ("BCRED Emerald JV LP") and trailing joint-borrower forms
            # ("Acme LLC and Verdelite JV LP") parent: neither has a comma or an
            # ordinal immediately before the label. Only the leading form needs an
            # explicit veto, because "Emerald JV LP, and Acme LLC" matches it.
            # RE2: no lookaround.
            member=_normal("split_part(CAST("+dimensions+" AS VARCHAR),'|',1)")
            for label in legacy:
                label=' '.join(label.lower().split())
                lab=re.escape(label)
                terminal=r'^investmentidentifieraxis=.+?(?:,\s*|,?\s+[0-9]+\s+)'+lab+r'(?: [0-9]+)?$'
                leading=r'^investmentidentifieraxis='+lab+r',\s*.+$'
                leading_joint=r'^investmentidentifieraxis='+lab+r',\s*and\b'
                matched.append('CASE WHEN (regexp_matches('+member+','+_literal(terminal)+') OR regexp_matches('+member+','+_literal(leading)+'))'
                    ' AND NOT regexp_matches('+member+','+_literal(leading_joint)+')'
                    ' THEN ['+_literal(label)+'] ELSE []::VARCHAR[] END')
        matching='list_concat('+','.join(matched)+')' if len(matched)>1 else matched[0]
        members="array_to_string(list_transform(list_sort(list_distinct("+matching+")),x -> 'reporting_entity='||x),'|')"
        cases.append('WHEN '+_cik_condition(cik,key)+" THEN coalesce("+members+",'')")
    return "CASE "+' '.join(cases)+" ELSE '' END" if cases else "''"
