-- Task 5: every distinct identifier label of the five funds with 'liquidity fund' in a segment, and how the cash rule
-- reads it now. Used to tighten r5_liquidity_fund without losing a real money-market fund.
select cf.cik, cf.identifier_label, count(*) n, bool_or(r.is_cash) any_cash, string_agg(distinct r.role, ',') roles
from int_context_feature cf
join int_source_row r using (accession, context_id)
where regexp_matches(lower(cf.identifier_label), 'liquidity')
group by all order by 1, 2
