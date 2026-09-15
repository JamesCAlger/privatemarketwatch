"""Resolve field unit references against cached XBRL definitions, without FX.

Unit identifiers are opaque and case-sensitive. Their spelling is never a
currency declaration. The original references and source hashes stay in facts.
"""
from pathlib import Path
import logging
import re

from lxml import etree
import pandas as pd

from pipeline.programme.core import sha

XBRLI = 'http://www.xbrl.org/2003/instance'
ISO4217 = 'http://www.xbrl.org/2003/iso4217'
logger = logging.getLogger(__name__)


def unit_definition(unit):
    measures = unit.findall(f'{{{XBRLI}}}measure')
    unresolved = dict(unit_kind='unresolved', currency=None)
    if len(measures) != 1 or unit.find(f'{{{XBRLI}}}divide') is not None:
        return unresolved
    measure = measures[0]
    value = (measure.text or '').strip()
    prefix, separator, name = value.partition(':')
    namespace = measure.nsmap.get(prefix if separator else None)
    if not separator:
        name = prefix
    if namespace == ISO4217 and re.fullmatch(r'[A-Z]{3}', name):
        return dict(unit_kind='monetary', currency=name)
    if namespace == XBRLI and name in ('pure', 'shares'):
        return dict(unit_kind=name, currency=None)
    return unresolved


def document_units(path, cik):
    """Return unambiguous units only from a document with matching entities."""
    path = Path(path)
    if not path.is_file():
        return {}, '', 'source_unavailable'
    before = sha(path)
    try:
        tree = etree.parse(str(path), etree.XMLParser(resolve_entities=False,
            no_network=True, load_dtd=False, huge_tree=True))
    except etree.XMLSyntaxError:
        if sha(path) != before:
            raise ValueError('Unit source changed while reading: ' + str(path))
        return {}, before, 'source_unparseable'
    if tree.docinfo.doctype:
        raise ValueError('DTD is not permitted in a monetary unit source')
    if tree.getroot().tag != f'{{{XBRLI}}}xbrl':
        return {}, before, 'source_not_xbrl'
    entities = {(e.text or '').strip().lstrip('0') for e in
        tree.findall(f'{{{XBRLI}}}context/{{{XBRLI}}}entity/{{{XBRLI}}}identifier')}
    if not entities or entities != {str(cik).lstrip('0')}:
        result = ({}, before, 'source_entity_unresolved')
    else:
        units, repeated = {}, set()
        for unit in tree.findall(f'{{{XBRLI}}}unit'):
            name = unit.get('id')
            if name in units:
                repeated.add(name)
            units[name] = unit_definition(unit)
        for name in repeated:
            units[name] = dict(unit_kind='unresolved', currency=None)
        result = (units, before, 'source_units_read')
    if sha(path) != before:
        raise ValueError('Unit source changed while reading: ' + str(path))
    return result


def resolve_bdc_units(con, cache_dir):
    """Enrich the caller's bdc_raw table through two set-based unit joins."""
    docs = con.execute("""SELECT DISTINCT CAST(cik AS VARCHAR),CAST(accession_number AS VARCHAR)
        FROM bdc_raw WHERE nullif(trim(CAST(cost_unit AS VARCHAR)),'') IS NOT NULL
            OR nullif(trim(CAST(fair_value_unit AS VARCHAR)),'') IS NOT NULL
        ORDER BY 1,2""").fetchall()
    records = []
    for index, (cik, accession) in enumerate(docs, 1):
        safe = bool(cik and cik.isdigit() and accession
            and re.fullmatch(r'[0-9]{10}-?[0-9]{2}-?[0-9]{6}', accession))
        if safe:
            path = Path(cache_dir) / str(int(cik)) / (accession.replace('-', '') + '.xml')
            units, source_sha, status = document_units(path, cik)
        else:
            units, source_sha, status = {}, '', 'source_identity_unavailable'
        # A document sentinel retains source availability even for missing IDs.
        records.append((cik, accession, None, None, status, source_sha))
        for unit_id, definition in units.items():
            currency = definition['currency'] if definition['unit_kind'] == 'monetary' else None
            records.append((cik, accession, unit_id, currency,
                'resolved' if currency else 'unit_unresolved', source_sha))
        if index % 100 == 0:
            logger.info('Resolved cached monetary unit documents: %d/%d', index, len(docs))
    lookup = pd.DataFrame(records, columns=['cik','accession','unit_ref','currency','status','source_sha256']).astype('string')
    con.register('_monetary_unit_lookup', lookup)
    con.execute("""CREATE TEMP TABLE _bdc_resolved_units AS SELECT r.*,
        CASE WHEN nullif(trim(CAST(r.fair_value_unit AS VARCHAR)),'') IS NULL THEN ''
             ELSE coalesce(f.currency,'UNRESOLVED') END AS _resolved_fv_currency,
        CASE WHEN nullif(trim(CAST(r.cost_unit AS VARCHAR)),'') IS NULL THEN ''
             ELSE coalesce(c.currency,'UNRESOLVED') END AS _resolved_cost_currency,
        CAST(json_merge_patch(coalesce(TRY_CAST(r.src_facts AS JSON),'{}'::JSON),
            json_object('_financial_units',json_object(
                'source_sha256',coalesce(d.source_sha256,''),
                'fair_value',json_object('unit_ref',r.fair_value_unit,'currency',f.currency,
                    'status',CASE WHEN nullif(trim(CAST(r.fair_value_unit AS VARCHAR)),'') IS NULL
                        THEN 'assumed_usd' ELSE coalesce(f.status,d.status,'unit_unresolved') END),
                'cost',json_object('unit_ref',r.cost_unit,'currency',c.currency,
                    'status',CASE WHEN nullif(trim(CAST(r.cost_unit AS VARCHAR)),'') IS NULL
                        THEN 'assumed_usd' ELSE coalesce(c.status,d.status,'unit_unresolved') END)))) AS VARCHAR) AS _unit_facts
        FROM bdc_raw r
        LEFT JOIN _monetary_unit_lookup f ON CAST(r.cik AS VARCHAR)=f.cik
            AND CAST(r.accession_number AS VARCHAR)=f.accession AND CAST(r.fair_value_unit AS VARCHAR)=f.unit_ref
        LEFT JOIN _monetary_unit_lookup c ON CAST(r.cik AS VARCHAR)=c.cik
            AND CAST(r.accession_number AS VARCHAR)=c.accession AND CAST(r.cost_unit AS VARCHAR)=c.unit_ref
        LEFT JOIN _monetary_unit_lookup d ON CAST(r.cik AS VARCHAR)=d.cik
            AND CAST(r.accession_number AS VARCHAR)=d.accession AND d.unit_ref IS NULL""")
    con.execute('DROP TABLE bdc_raw')
    con.execute('CREATE TABLE bdc_raw AS SELECT * EXCLUDE(_unit_facts) REPLACE(_unit_facts AS src_facts) FROM _bdc_resolved_units')
    con.execute('DROP TABLE _bdc_resolved_units')
    con.unregister('_monetary_unit_lookup')
