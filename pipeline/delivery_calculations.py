"""Validate exported FX calculations and their typed arithmetic, without IO."""


def validate_fx_evidence(con):
    """Bind each displayed calculation to its observation and replay the math.

    The financial stage verifies admitted FRED inputs independently. Delivery
    verifies the published event, units, dates and decimal arithmetic. It does
    not turn a calculation into a direct source citation.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    con.execute("""CREATE TEMP TABLE delivery_fx AS SELECT h.row_id,h.report_date,h.fair_value,
        h.fair_value_currency,e.payload,
        json_extract(payload,'$.calculation') AS event,
        json_extract(TRY_CAST(h.src_facts AS JSON),'$._financial_fx.fair_value') AS source_event,
        json_extract_string(TRY_CAST(h.src_facts AS JSON),'$._financial_units.source_sha256') AS source_hash,
        TRY_CAST(json_extract_string(payload,'$.calculation.source_value') AS DECIMAL(38,20)) AS amount,
        TRY_CAST(CASE WHEN json_extract_string(payload,'$.method')='already_USD' THEN '1'
            ELSE json_extract_string(payload,'$.calculation.conversion.rate_USD_per_source') END
            AS DECIMAL(36,28)) AS factor
        FROM delivery_rows h JOIN delivery_evidence e USING(row_id)
        WHERE e.field='fair_value' AND json_extract_string(payload,'$.status')='calculated'""")
    factors = con.execute('SELECT row_id,amount,factor FROM delivery_fx ORDER BY row_id').fetch_arrow_table()
    amounts = pc.cast(factors['amount'], pa.decimal256(38,20))
    rates = pc.cast(factors['factor'], pa.decimal256(36,28))
    values = pc.multiply(amounts, rates)
    con.register('delivery_fx_arithmetic', pa.table(dict(row_id=factors['row_id'],
        expected_value=pc.cast(values, pa.float64()), expected_decimal=pc.cast(values, pa.string()))))
    try:
        con.execute("""CREATE TEMP TABLE delivery_fx_checks AS SELECT f.row_id,coalesce(
            json_contains(f.event,f.source_event) AND json_contains(f.source_event,f.event)
            AND f.source_event IS NOT NULL
            AND json_extract_string(f.payload,'$.method')=json_extract_string(f.event,'$.conversion.method')
            AND json_extract_string(f.payload,'$.input.status')='unavailable'
            AND coalesce(json_extract_string(f.payload,'$.input.reason'),'')<>''
            AND json_extract_string(f.event,'$.document_sha256')=f.source_hash
            AND regexp_full_match(f.source_hash,'[a-f0-9]{64}')
            AND regexp_full_match(json_extract_string(f.event,'$.reference_sha256'),'[a-f0-9]{64}')
            AND coalesce(json_extract_string(f.event,'$.decision_id'),'')<>''
            AND regexp_full_match(json_extract_string(f.event,'$.resolved_currency'),'[A-Z]{3}')
            AND f.fair_value_currency='USD' AND isfinite(f.fair_value)
            AND f.fair_value=a.expected_value
            AND f.fair_value=TRY_CAST(json_extract_string(f.event,'$.final_value') AS DOUBLE)
            AND json_extract_string(f.event,'$.decimal_value')=a.expected_decimal
            AND f.factor>0
            AND CASE json_extract_string(f.payload,'$.method')
              WHEN 'already_USD' THEN json_extract_string(f.event,'$.resolved_currency')='USD'
                AND json_extract_string(f.event,'$.conversion.quote_id') IS NULL
              WHEN 'report_date_reference_conversion' THEN
                json_extract_string(f.event,'$.resolved_currency')<>'USD'
                AND json_extract_string(f.event,'$.conversion.quote_inputs.provider')='FRED'
                AND coalesce(json_extract_string(f.event,'$.conversion.quote_id'),'')<>''
                AND regexp_full_match(json_extract_string(f.event,'$.conversion.quote_inputs.source_sha256'),'[a-f0-9]{64}')
                AND json_extract_string(f.event,'$.conversion.quote_date')=
                    json_extract_string(f.event,'$.conversion.quote_inputs.quote_date')
                AND date_diff('day',TRY_CAST(json_extract_string(f.event,'$.conversion.quote_date') AS DATE),
                    f.report_date) BETWEEN 0 AND 7
                AND date_diff('day',TRY_CAST(json_extract_string(f.event,'$.conversion.quote_date') AS DATE),
                    f.report_date)=TRY_CAST(json_extract_string(f.event,'$.conversion.age_days') AS BIGINT)
                AND f.factor=TRY_CAST(json_extract_string(f.event,'$.conversion.quote_inputs.usd_per_unit') AS DECIMAL(36,28))
                AND f.factor=TRY_CAST(json_extract_string(f.event,'$.conversion.value') AS DECIMAL(36,28))
              ELSE false END,false) AS valid
            FROM delivery_fx f JOIN delivery_fx_arithmetic a USING(row_id)""")
    finally:
        con.unregister('delivery_fx_arithmetic')
