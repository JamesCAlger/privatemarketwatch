-- Slice R phase 1 (2026-11-26): MEASUREMENT ONLY, not a check. The rule-read reference rate (int_text_reference_rate_read)
-- against production's reference_rate_type on published positions both sides hold (cmp_row_set basis published, side
-- both; production row joined as in q_a3_disagreements.sql). Agreement with production is not correctness. Read-only.
with j as (
    select r.cik, r.status, r.code, r.reference_rate as new_ref, nullif(h.reference_rate_type, '') as prod_ref
    from int_text_reference_rate_read r
    join cmp_row_set s on s.accession = r.accession and s.context_id = r.context_id and s.basis = 'published' and s.side = 'both'
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where r.is_published
)
, k as (
    select *, case
        when new_ref is null and prod_ref is null then 'both empty'
        when new_ref is null then 'production only'
        when prod_ref is null then 'new only'
        when upper(new_ref) = upper(prod_ref) then 'same'
        else 'differ' end as outcome
    from j
)
select 'outcome' as block, cik, outcome as what, null as detail, count(*) as n from k group by all
union all
select 'production only by code', cik, coalesce(code, '(' || status || ')'), prod_ref, count(*) from k where outcome = 'production only' group by all
union all
select 'differ', cik, code || ': ' || new_ref, prod_ref, count(*) from k where outcome = 'differ' group by all
union all
select 'new only', cik, code || ': ' || new_ref, null, count(*) from k where outcome = 'new only' group by all
order by 1, 2, 5 desc
