CREATE TABLE cohort AS SELECT lpad(unnest(entries).cik,10,'0') cik FROM read_json_auto('data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json');

CREATE TABLE quarters AS SELECT CAST(last_day(d + INTERVAL 2 MONTH) AS VARCHAR) report_date FROM generate_series(DATE '2023-01-01', DATE '2026-01-01', INTERVAL 3 MONTH) t(d);

CREATE TABLE h AS SELECT source, cik, report_date, accession_number,
    row_id, row_id_basis, src_context_id, entity_id, position_id, position_key,
    bdc_investment_identifier, try_cast(basis_spread AS DOUBLE) spread,
    cost_source, interest_rate_source, principal_fx_status, maturity_date,
    fair_value_currency, cost_currency, principal_amount_currency,
    gics_sub_industry, nonaccrual_footnote, nonaccrual_dimension, is_subsidiary,
    try_cast(fair_value AS DOUBLE) fv, try_cast(cost AS DOUBLE) cost_value,
    try_cast(interest_rate AS DOUBLE) rate, try_cast(pik_rate AS DOUBLE) pik,
    try_cast(principal_amount AS DOUBLE) principal,
    try_cast(principal_amount_usd AS DOUBLE) principal_usd,
    try_cast(pct_of_net_assets AS DOUBLE) pct
    FROM read_csv('data/output/private_markets_holdings.csv', all_varchar=true)
    WHERE cik IN (SELECT cik FROM cohort) AND report_date IN (SELECT report_date FROM quarters);

-- quarter_profile
SELECT report_date, count(*) row_count,
    count(DISTINCT cik) funds, sum(fv) signed_fv, sum(abs(fv)) absolute_fv,
    count(*) FILTER (WHERE fv IS NULL) missing_fv,
    count(*) FILTER (WHERE fv < 0) negative_fv,
    count(*) FILTER (WHERE cost_source='derived_proxy') cost_proxy_rows,
    sum(abs(fv)) FILTER (WHERE cost_source='derived_proxy') cost_proxy_absolute_fv,
    count(*) FILTER (WHERE cost_value=0) zero_cost_rows,
    count(*) FILTER (WHERE rate IS NULL) missing_rate,
    count(*) FILTER (WHERE pik>0 AND rate=0) positive_pik_zero_rate,
    count(*) FILTER (WHERE abs(pct)>150) pct_outside_schema,
    count(*) FILTER (WHERE coalesce(entity_id,'')='') missing_entity_id,
    count(*) FILTER (WHERE coalesce(position_id,'')='') missing_position_id,
    count(*) FILTER (WHERE coalesce(position_key,'')='') missing_position_key,
    count(*) FILTER (WHERE coalesce(gics_sub_industry,'')<>'') gics_populated,
    sum(abs(fv)) FILTER (WHERE coalesce(gics_sub_industry,'')<>'') gics_populated_absolute_fv,
    count(*) FILTER (WHERE try_cast(is_subsidiary AS INTEGER)=1) subsidiary_rows
    FROM h GROUP BY 1 ORDER BY 1;

-- currency_profile
SELECT report_date, field, coalesce(currency,'<blank>') currency,
    count(*) row_count, count(amount_value) populated_amounts, sum(abs(amount_value)) absolute_native_amount
    FROM (SELECT report_date,'fair_value' field,fair_value_currency currency,fv amount_value FROM h
    UNION ALL SELECT report_date,'cost',cost_currency,cost_value FROM h
    UNION ALL SELECT report_date,'principal',principal_amount_currency,principal FROM h)
    GROUP BY 1,2,3 ORDER BY 1,2,3;

-- principal_fx_profile
SELECT report_date, coalesce(principal_fx_status,'<blank>') status,
    count(*) row_count, count(principal) populated_principal, count(principal_usd) populated_usd
    FROM h GROUP BY 1,2 ORDER BY 1,2;

-- key_collisions
SELECT 'row_id' key_kind, count(*) duplicate_groups,
    coalesce(sum(n-1),0) excess_rows FROM (SELECT row_id,count(*) n FROM h
    WHERE coalesce(row_id,'')<>'' GROUP BY 1 HAVING count(*)>1)
    UNION ALL SELECT 'source_context',count(*),coalesce(sum(n-1),0) FROM (
    SELECT cik,report_date,accession_number,src_context_id,count(*) n FROM h
    WHERE coalesce(src_context_id,'')<>'' GROUP BY 1,2,3,4 HAVING count(*)>1)
    UNION ALL SELECT 'within_quarter_position_key',count(*),coalesce(sum(n-1),0) FROM (
    SELECT cik,report_date,position_key,count(*) n FROM h WHERE coalesce(position_key,'')<>''
    GROUP BY 1,2,3 HAVING count(*)>1);

-- row_id_basis
SELECT row_id_basis,count(*) row_count FROM h GROUP BY 1 ORDER BY 1;

-- subsidiary_flag_values
SELECT is_subsidiary,count(*) row_count FROM h GROUP BY 1 ORDER BY 1;

-- entity_lookup_multiplicity
SELECT count(*) duplicate_join_keys,
    coalesce(sum(n-1),0) excess_lookup_rows, count(*) FILTER (WHERE ids>1) conflicting_ids
    FROM (SELECT issuer_name_variant,source,count(*) n,count(DISTINCT entity_id) ids
    FROM read_csv('data/output/entity_lookup.csv',all_varchar=true)
    GROUP BY 1,2 HAVING count(*)>1);

-- spread_override_saved_matches
WITH corrections AS (
    SELECT unnest(corrections) c FROM read_json_auto('data/overrides/identifier_spread_corrections.json'))
    SELECT c.cik,c.report_date,c.identifier,c.new_value_decimal,
    c.new_value_decimal * 100 expected_percentage_points,h.row_id,h.spread saved_spread,
    h.fv FROM corrections LEFT JOIN h ON c.cik=h.cik AND c.report_date=h.report_date
    AND c.identifier=h.bdc_investment_identifier ORDER BY 1,2,3;

-- raw_monetary_units
SELECT field,coalesce(unit,'<blank>') unit,
    count(*) row_count FROM (SELECT fair_value_unit,cost_unit,principal_amount_unit
    FROM read_csv('data/output/bdc_holdings.csv',all_varchar=true)
    WHERE lpad(cik,10,'0') IN (SELECT cik FROM cohort)
    AND period IN (SELECT report_date FROM quarters))
    UNPIVOT INCLUDE NULLS (unit FOR field IN (fair_value_unit,cost_unit,principal_amount_unit))
    GROUP BY 1,2 ORDER BY 1,2;

-- obligations
WITH saved AS (SELECT cik,report_date,count(*) n
    FROM h GROUP BY 1,2), filings AS (SELECT lpad(cik,10,'0') cik,report_date,
    count(*) n,count(*) FILTER (WHERE coalesce(xbrl_local_path,'')<>'') paths_recorded
    FROM read_csv('data/output/bdc_filings_index.csv',all_varchar=true) GROUP BY 1,2)
    SELECT c.cik,q.report_date,coalesce(s.n,0) holdings_rows,
    coalesce(f.n,0) indexed_filings,coalesce(f.paths_recorded,0) indexed_local_paths,
    'eligibility_not_yet_adjudicated' eligibility_status
    FROM cohort c CROSS JOIN quarters q LEFT JOIN saved s USING(cik,report_date)
    LEFT JOIN filings f USING(cik,report_date) ORDER BY 1,2;
