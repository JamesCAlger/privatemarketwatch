-- Fix round 2 C: distinct identifier labels with money-market-like words, and their current role and cash flag.
select cf.cik, cf.identifier_label, string_agg(distinct r.role, ',') roles, bool_or(r.is_cash) any_cash, count(*) n
from int_context_feature cf join int_source_row r using (accession, context_id)
where regexp_matches(lower(cf.identifier_label), 'liquidity|treasury|government|cash management|financial square|money market|institutional shares|premier|sweep')
group by all order by 1, 2
