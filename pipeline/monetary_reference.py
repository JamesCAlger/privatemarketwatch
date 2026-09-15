"""Normalize independently read source FV into the USD assessment contract.

The candidate supplies correspondence IDs only. Values, source hashes and
currency precision come from the separately collected instance facts. Missing
unit adjudication or FX is an assessability gap, not a missing-extraction claim.
"""
import pandas as pd


def normalize(con,*,quotes=(),decisions=()):
    con.execute("CREATE OR REPLACE TABLE monetary_source_fields AS SELECT * FROM source_fields WHERE field IN ('fair_value','cost')")
    con.execute("""CREATE OR REPLACE TABLE source_fields AS SELECT * REPLACE(
        CASE WHEN field IN ('fair_value','cost') AND reason='ready'
                  AND coalesce(currency,'')<>'USD'
             THEN 'unresolved_USD_monetary_reference' ELSE reason END AS reason)
        FROM source_fields""")
    con.execute("""CREATE OR REPLACE TABLE monetary_reference_audit(
        cik VARCHAR,quarter VARCHAR,accession VARCHAR,context_id VARCHAR,
        decision_id VARCHAR,source_currency VARCHAR,resolved_currency VARCHAR,
        source_value VARCHAR,reference_value VARCHAR,precision_bound VARCHAR,
        method VARCHAR,quote_id VARCHAR,quote_source_sha256 VARCHAR)""")
    if not decisions: return
    import pyarrow as pa
    import pyarrow.compute as pc
    from scripts.programme_closeout.fx import convert

    con.register('monetary_decisions',pd.DataFrame(decisions).astype('string'))
    con.execute("""CREATE OR REPLACE TABLE monetary_selected AS SELECT s.cik,s.quarter,s.accession,s.context_id,
        s.currency AS source_currency,s.reference_value AS source_value,s.precision_bound,
        d.currency AS resolved_currency,d.decision_id,d.document_sha256,d.source_value AS adjudicated_value,
        doc.source_sha256,
        count(*) OVER(PARTITION BY s.cik,s.quarter,s.accession,s.context_id) AS decisions
        FROM monetary_source_fields s JOIN links l USING(cik,quarter,accession,context_id)
        JOIN monetary_decisions d ON d.row_id=l.row_id AND d.field=s.field
        JOIN document_status doc USING(cik,accession)
        WHERE s.field='fair_value' AND s.reason='ready' AND s.variants=1 AND s.fact_count>0""")
    con.execute("""CREATE OR REPLACE TABLE monetary_valid AS SELECT * FROM monetary_selected
        WHERE decisions=1 AND source_sha256=document_sha256
          AND source_value=TRY_CAST(adjudicated_value AS DECIMAL(38,12))""")
    # A rejected source-bound decision never leaves an apparently ready USD
    # reference behind merely because the original tag happened to say USD.
    con.execute("""UPDATE source_fields s SET reason='unresolved_source_unit_adjudication'
        FROM monetary_selected m WHERE s.cik=m.cik AND s.quarter=m.quarter
          AND s.accession=m.accession AND s.context_id=m.context_id AND s.field='fair_value'""")
    pairs=con.execute('SELECT DISTINCT resolved_currency,quarter FROM monetary_valid ORDER BY ALL').fetchall()
    references=[]
    quote_by_id={q['quote_id']:q for q in quotes}
    for currency,quarter in pairs:
        selected=convert(1,currency,quarter,quotes)
        quote=quote_by_id.get(selected.get('quote_id'))
        source_leg=usd_leg=None
        if selected['method']=='already_USD': source_leg=usd_leg='1'
        elif selected['method']=='report_date_reference_conversion':
            # FRED H.10 quotes are direct USD-per-unit observations: the source
            # leg is one unit of the resolved currency, the USD leg is the quote.
            source_leg='1'
            usd_leg=str(quote['usd_per_unit'][currency])
        references.append((currency,quarter,source_leg,usd_leg,selected['method'],
            selected.get('quote_id'),quote['source_sha256'] if quote else None))
    columns=['resolved_currency','quarter','source_leg','usd_leg','method','quote_id','quote_source_sha256']
    con.register('monetary_reference_quotes',pd.DataFrame(references,columns=columns).astype('string'))
    con.execute("""CREATE OR REPLACE TABLE monetary_values AS SELECT m.*,q.* EXCLUDE(resolved_currency,quarter),
        row_number() OVER(ORDER BY cik,quarter,accession,context_id) AS reference_id
        FROM monetary_valid m JOIN monetary_reference_quotes q USING(resolved_currency,quarter)""")
    values=con.execute("""SELECT reference_id,CAST(source_value AS VARCHAR) AS amount,
        CAST(precision_bound AS VARCHAR) AS uncertainty,source_leg,usd_leg
        FROM monetary_values ORDER BY reference_id""").fetch_arrow_table()
    if not len(values): return
    # Independent arithmetic: multiply the source amount by the actual USD
    # quote leg, then divide by the source leg. Production multiplies by a
    # separately calculated cross-rate. Both project to the declared DOUBLE.
    usd=pc.cast(values['usd_leg'],pa.decimal256(18,12))
    source=pc.cast(values['source_leg'],pa.decimal256(18,12))
    calculated={}
    for name in ('amount','uncertainty'):
        raw=pc.cast(values[name],pa.decimal256(30,12))
        actual=pc.divide(pc.multiply(raw,usd),source)
        calculated[name]=pc.cast(pc.cast(actual,pa.float64()),pa.string())
    con.register('monetary_calculations',pa.table({'reference_id':values['reference_id'],**calculated}))
    con.execute("""INSERT INTO monetary_reference_audit SELECT m.cik,m.quarter,m.accession,m.context_id,
        m.decision_id,m.source_currency,m.resolved_currency,CAST(m.source_value AS VARCHAR),
        c.amount,c.uncertainty,m.method,m.quote_id,m.quote_source_sha256
        FROM monetary_values m JOIN monetary_calculations c USING(reference_id)""")
    con.execute("""CREATE OR REPLACE TABLE source_fields AS SELECT s.* REPLACE(
        CASE WHEN a.method IN ('already_USD','report_date_reference_conversion')
             THEN TRY_CAST(a.reference_value AS DECIMAL(38,12)) ELSE s.reference_value END AS reference_value,
        CASE WHEN a.method IN ('already_USD','report_date_reference_conversion')
             THEN TRY_CAST(a.precision_bound AS DECIMAL(38,12)) ELSE s.precision_bound END AS precision_bound,
        CASE WHEN a.method IN ('already_USD','report_date_reference_conversion') THEN 'USD' ELSE s.currency END AS currency,
        CASE WHEN a.method IN ('already_USD','report_date_reference_conversion') THEN 'ready'
             WHEN a.method IS NOT NULL THEN a.method ELSE s.reason END AS reason)
        FROM source_fields s LEFT JOIN monetary_reference_audit a
          ON s.cik=a.cik AND s.quarter=a.quarter AND s.accession=a.accession
          AND s.context_id=a.context_id AND s.field='fair_value'""")
