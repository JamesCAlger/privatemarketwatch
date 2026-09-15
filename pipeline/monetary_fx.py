"""Admitted source-unit decisions and pinned, offline FRED H.10 FV conversions.

Unit spelling is not an adjudication. Conversion is unlocked either by a
manifest-admitted decision bound to the original observation, value and
document, or (owner decision 2026-09-15) automatically when the cached XBRL
instance itself defines the fact's unit as a single ISO-4217 measure other
than USD. That automatic decision is derived from the document's unit
definition and hash, never from unit-reference spelling; unresolved units
still require a manual decision. The single FX provider is the Federal
Reserve H.10 release as published by FRED (USD per unit, one date per quote).
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import json
from pathlib import Path
import re

import duckdb
import pandas as pd

from pipeline.programme.core import digest, sha
from pipeline.rule_admission import admitted, reject_contract

PROVIDER='FRED'


def resolved_unit_decisions(frame):
    """Derive automatic FV unit adjudications from the document's own unit definitions.

    A row qualifies only when staging resolved the fact's unit from the cached
    XBRL instance to one ISO-4217 monetary measure other than USD and the
    instance hash is recorded. The decision id is deterministic per row so a
    retained conversion replays byte-identically; for retained rows the source
    value is taken from the retained event rather than the converted amount.
    """
    if frame.empty or 'src_facts' not in frame: return []
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        con.register('h',frame[['row_id','fair_value','src_facts']])
        rows=con.execute("""WITH facts AS (
                SELECT row_id,fair_value,TRY_CAST(src_facts AS JSON) AS facts FROM h
            ), units AS (
                SELECT row_id,fair_value,
                    json_extract(facts,'$._financial_fx.fair_value') AS previous,
                    json_extract_string(facts,'$._financial_units.fair_value.status') AS status,
                    json_extract_string(facts,'$._financial_units.fair_value.currency') AS currency,
                    json_extract_string(facts,'$._financial_units.source_sha256') AS document_sha256
                FROM facts)
            SELECT row_id,'unit:'||row_id AS decision_id,'fair_value' AS field,
                coalesce(json_extract_string(previous,'$.source_value'),CAST(fair_value AS VARCHAR)) AS source_value,
                currency,document_sha256
            FROM units
            WHERE status='resolved' AND regexp_full_match(coalesce(currency,''),'[A-Z]{3}') AND currency<>'USD'
              AND regexp_full_match(coalesce(document_sha256,''),'[0-9a-f]{64}')
              AND (previous IS NOT NULL OR TRY_CAST(fair_value AS DECIMAL(38,12)) IS NOT NULL)
            ORDER BY row_id""").fetchall()
    keys=('row_id','decision_id','field','source_value','currency','document_sha256')
    return [dict(zip(keys,row)) for row in rows]


def load_inputs(directory):
    """Read optional promoted inputs; never infer approval from file placement.

    A quote contains date, quote_id, usd_per_unit and a relative source path/hash.
    An adjudication contains decision_id, row_id, field, source_value, currency and
    document_sha256. Empty or absent inputs leave foreign FV unavailable.
    """
    directory=Path(directory)
    result={'quotes':[], 'decisions':[], 'inputs':{}}
    for filename,key in (('quotes.json','quotes'),('unit_adjudications.json','decisions')):
        path=directory/filename
        if not path.is_file(): continue
        manifest=directory/'admission_manifest.json'
        manifest_hash=sha(manifest) if manifest.is_file() else None
        if not admitted(path,directory,allow_legacy=False): continue
        if manifest_hash is None or sha(manifest)!=manifest_hash:
            raise ValueError('Monetary admission manifest changed while loading')
        result['inputs'][str(manifest)]=manifest_hash
        before=sha(path)
        try:
            data=json.loads(path.read_text(encoding='utf-8-sig'))
            if data.get('format_version')!=1 or not isinstance(data.get(key),list):
                raise ValueError('Invalid monetary input format: '+filename)
            result[key]=data[key]
            if key=='quotes':
                from datetime import date
                seen=set()
                for quote in result[key]:
                    date.fromisoformat(quote['date'])
                    if quote.get('provider')!=PROVIDER or not quote.get('quote_id') or quote['quote_id'] in seen:
                        raise ValueError('Invalid provider or duplicate quote identity')
                    seen.add(quote['quote_id'])
                    if not isinstance(quote.get('usd_per_unit'),dict) or not quote['usd_per_unit']:
                        raise ValueError('Provider observation lacks currency legs')
                    for currency,value in quote['usd_per_unit'].items():
                        rate=Decimal(str(value))
                        if not re.fullmatch('[A-Z]{3}',currency) or not rate.is_finite() or rate<=0:
                            raise ValueError('Invalid provider currency/rate')
                    source=quote['source']
                    source_path=(directory/source['path']).resolve()
                    if not source_path.is_relative_to(directory.resolve()) or not source_path.is_file():
                        raise ValueError('FX quote source must be a retained local package file')
                    if sha(source_path)!=source['sha256']:
                        raise ValueError('FX quote source hash mismatch')
                    quote['source_sha256']=source['sha256']
                    result['inputs'][str(source_path)]=source['sha256']
            else:
                required={'decision_id','row_id','field','source_value','currency','document_sha256'}
                if any(not isinstance(d,dict) or not required<=set(d) or not d['decision_id'] or
                       not d['row_id'] or d['field']!='fair_value' or
                       not re.fullmatch('[A-Z]{3}',d['currency']) or
                       not re.fullmatch('[0-9a-f]{64}',d['document_sha256']) or
                       not Decimal(str(d['source_value'])).is_finite() for d in result[key]):
                    raise ValueError('Malformed field-specific unit adjudication')
                if len({d['row_id'] for d in result[key]})!=len(result[key]):
                    raise ValueError('Ambiguous FV unit adjudication')
            if sha(path)!=before: raise ValueError('Monetary input changed while reading')
            result['inputs'][str(path)]=before
        except (ValueError,KeyError,TypeError,ArithmeticError):
            reject_contract(path,'Invalid monetary conversion input')
            raise
    return result


def apply_fair_value(frame,*,quotes=(),decisions=()):
    """Vectorized conversion after field-specific unit adjudication.

    Python iterates only the small currency/date reference keys. Monetary
    observations use Arrow decimal kernels and DuckDB joins. USD storage is
    DOUBLE, so rounding into that declared type occurs only after conversion.
    Original amount, tag, adjudication and provider observation remain in facts.
    """
    if frame.empty: return frame
    retained=frame['src_facts'].astype('string').str.contains('"_financial_fx"',regex=False,na=False)
    # Manual decisions win; document-resolved units fill the rest automatically.
    explicit={d.get('row_id') for d in decisions if isinstance(d,dict)}
    decisions=list(decisions)+[d for d in resolved_unit_decisions(frame) if d['row_id'] not in explicit]
    if not decisions:
        if retained.any():
            raise ValueError('Retained FX conversion has no admitted decision; rebuild from cached source')
        return frame
    from datetime import date
    from scripts.programme_closeout.fx import convert
    import pyarrow as pa
    import pyarrow.compute as pc

    required={'decision_id','row_id','field','source_value','currency','document_sha256'}
    if any(not required<=set(d) or not d['decision_id'] or
           d['field']!='fair_value' or
           not re.fullmatch('[A-Z]{3}',d['currency']) or
           not re.fullmatch('[0-9a-f]{64}',d['document_sha256']) for d in decisions):
        raise ValueError('Unit adjudication lacks observation/value/document identity')
    if len({d['row_id'] for d in decisions})!=len(decisions):
        raise ValueError('Ambiguous FV unit adjudication')
    quote_ids=set()
    for q in quotes:
        date.fromisoformat(q['date'])
        if q.get('provider')!=PROVIDER: raise ValueError('Unsupported FX provider')
        if not q.get('quote_id') or q['quote_id'] in quote_ids or not q.get('source_sha256'):
            raise ValueError('Unpinned or duplicate FX quote identity')
        quote_ids.add(q['quote_id'])
        if not isinstance(q.get('usd_per_unit'),dict) or not q['usd_per_unit']:
            raise ValueError('FX observation lacks currency legs')
        for currency,value in q['usd_per_unit'].items():
            rate=Decimal(str(value))
            if not re.fullmatch('[A-Z]{3}',currency) or not rate.is_finite() or rate<=0:
                raise ValueError('Invalid provider currency/rate')
    adjudications=pd.DataFrame(decisions)[sorted(required)].astype('string')
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        con.register('h',frame);con.register('decisions',adjudications)
        con.register('retained_fx',frame.loc[retained,['row_id','src_facts']])
        orphaned=con.execute("""SELECT count(*) FROM retained_fx r ANTI JOIN decisions d USING(row_id)
            WHERE json_extract(TRY_CAST(r.src_facts AS JSON),'$._financial_fx.fair_value') IS NOT NULL""").fetchone()[0]
        if orphaned:
            raise ValueError('Retained FX conversion has no admitted decision; rebuild from cached source')
        con.execute("""CREATE TABLE selected AS SELECT h.row_id,cast(h.report_date AS VARCHAR)[:10] AS report_date,
            d.currency,d.decision_id,d.document_sha256,d.source_value,
            CAST(h.fair_value AS VARCHAR) AS amount,CAST(h.fair_value_currency AS VARCHAR) AS tagged_currency,
            json_extract(TRY_CAST(h.src_facts AS JSON),'$._financial_fx.fair_value') AS previous,
            json_extract_string(TRY_CAST(h.src_facts AS JSON),'$._financial_units.source_sha256') AS document_hash
            FROM h JOIN decisions d USING(row_id)""")
        # An admitted decision cannot silently act on another value/document.
        invalid=con.execute("""SELECT count(*) FROM selected WHERE document_hash IS DISTINCT FROM document_sha256
            OR (previous IS NULL AND (TRY_CAST(amount AS DECIMAL(38,12)) IS NULL
                OR TRY_CAST(amount AS DECIMAL(38,12)) IS DISTINCT FROM TRY_CAST(source_value AS DECIMAL(38,12))))
            OR (previous IS NOT NULL AND (json_extract_string(previous,'$.decision_id') IS DISTINCT FROM decision_id
                OR json_extract_string(previous,'$.resolved_currency') IS DISTINCT FROM currency
                OR tagged_currency IS DISTINCT FROM CASE
                    WHEN json_extract_string(previous,'$.final_value') IS NOT NULL THEN 'USD' ELSE currency END
                OR TRY_CAST(amount AS DOUBLE) IS DISTINCT FROM TRY_CAST(json_extract_string(previous,'$.final_value') AS DOUBLE)
                OR json_extract_string(previous,'$.source_value') IS DISTINCT FROM source_value))""").fetchone()[0]
        if invalid: raise ValueError('FV unit adjudication does not match retained observation evidence; rebuild from cached source')
        con.execute('CREATE TABLE pending AS SELECT * FROM selected WHERE previous IS NULL')
        pairs=con.execute('SELECT DISTINCT currency,report_date FROM selected ORDER BY ALL').fetchall()
        factors=[]
        for currency,report_date in pairs:
            with localcontext() as ctx:
                ctx.prec=60
                conversion=convert(1,currency,report_date,quotes)
                if conversion.get('quote_id'):
                    chosen=next(q for q in quotes if q['quote_id']==conversion['quote_id'])
                    conversion['quote_inputs']=dict(source_sha256=chosen['source_sha256'],
                        provider=chosen['provider'],quote_date=chosen['date'],
                        usd_per_unit=str(chosen['usd_per_unit'][currency]),
                        series=str((chosen.get('series') or {}).get(currency,'')))
                factor=conversion.get('value')
                # 28 fractional decimal places precede the final DOUBLE cast.
                factor=str(Decimal(factor).quantize(Decimal('1e-28'))) if factor is not None else None
            factors.append((currency,report_date,factor,json.dumps(conversion),digest(conversion)))
        factor_frame=pd.DataFrame(factors,columns=['currency','report_date','factor','conversion','reference_sha256']).astype('string')
        con.register('factors',factor_frame)
        reference_schema=json.dumps(dict(value='VARCHAR',method='VARCHAR',quote_id='VARCHAR',
            quote_date='VARCHAR',age_days='BIGINT',rate_USD_per_source='VARCHAR',quote_inputs=dict(
                source_sha256='VARCHAR',provider='VARCHAR',quote_date='VARCHAR',
                usd_per_unit='VARCHAR',series='VARCHAR')))
        changed=con.execute("""SELECT count(*) FROM selected s JOIN factors f USING(currency,report_date)
            WHERE s.previous IS NOT NULL AND (
                json_extract_string(s.previous,'$.reference_sha256') IS DISTINCT FROM f.reference_sha256
                OR json_transform(json_extract(s.previous,'$.conversion'),?) IS DISTINCT FROM
                   json_transform(f.conversion,?))""",[reference_schema,reference_schema]).fetchone()[0]
        if changed:
            raise ValueError('Retained FX reference changed; rebuild from cached source')
        pending=con.execute("""SELECT p.row_id,p.amount,f.factor FROM pending p JOIN factors f
            USING(currency,report_date) ORDER BY p.row_id""").fetch_arrow_table()
        if not len(pending): return frame
        # decimal256 multiplication retains wide intermediates; no per-row UDF.
        amounts=pc.cast(pending['amount'],pa.decimal256(38,20))
        rates=pc.cast(pending['factor'],pa.decimal256(36,28))
        values=pc.multiply(amounts,rates)
        converted=pa.table({'row_id':pending['row_id'],
            'final_value':pc.cast(values,pa.float64()),'decimal_value':pc.cast(values,pa.string())})
        con.register('converted',converted)
        con.execute("""CREATE TABLE result AS SELECT p.row_id,c.final_value,
            CASE WHEN c.final_value IS NOT NULL THEN 'USD' ELSE p.currency END AS final_currency,
            json_object('decision_id',p.decision_id,'document_sha256',p.document_sha256,
                'reference_sha256',f.reference_sha256,
                'source_value',p.source_value,'tagged_currency',p.tagged_currency,'resolved_currency',p.currency,
                'final_value',CAST(c.final_value AS VARCHAR),'decimal_value',c.decimal_value,
                'conversion',TRY_CAST(f.conversion AS JSON)) AS event
            FROM pending p JOIN factors f USING(currency,report_date) JOIN converted c USING(row_id)""")
        output=con.execute("""SELECT h.* REPLACE(
            CASE WHEN r.row_id IS NOT NULL THEN r.final_value ELSE TRY_CAST(h.fair_value AS DOUBLE) END AS fair_value,
            CASE WHEN r.row_id IS NOT NULL THEN r.final_currency ELSE h.fair_value_currency END AS fair_value_currency,
            CASE WHEN r.row_id IS NOT NULL THEN CAST(json_merge_patch(coalesce(TRY_CAST(h.src_facts AS JSON),'{}'::JSON),
                json_object('_financial_fx',json_object('fair_value',r.event))) AS VARCHAR) ELSE h.src_facts END AS src_facts)
            FROM h LEFT JOIN result r USING(row_id)""").fetchdf()
    if len(output)!=len(frame): raise ValueError('FX normalization changed observation grain')
    return output
