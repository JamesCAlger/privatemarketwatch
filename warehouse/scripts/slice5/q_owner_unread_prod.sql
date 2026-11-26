-- Owner question 2026-11-25: how production holds the rates this layer leaves unread (text_not_read) and production
-- fills. By fund: production's rate source, kind, the rate transforms it records, and whether a correction set it.
-- Read-only.
with r as (
    select c.cik, c.accession, c.context_id
    from cmp_rate c
    join int_field_corrected f on f.accession = c.accession and f.context_id = c.context_id and f.field = c.field
    where f.reason = 'text_not_read' and c.is_published and c.field = 'interest_rate' and c.outcome = 'new_empty'
)
select r.cik, h.interest_rate_source, h.interest_rate_kind
    , array_to_string(list_sort(list_filter(string_split(coalesce(h.src_transforms, ''), ';'), x -> x like '%rate%' or x like '%pik%' or x like '%spread%' or x like '%coupon%')), ';') as rate_transforms
    , coalesce(regexp_matches(coalesce(h.corrected_fields, ''), 'interest_rate|pik_rate'), false) as corrected
    , count(*) as n
    , any_value(h.accession_number || ' ' || h.src_context_id) as example
from r
join cmp_row_set s on s.accession = r.accession and s.context_id = r.context_id and s.side = 'both'
join stg_holdings h on h.accession_number = r.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
group by all order by 1, n desc
