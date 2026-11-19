-- Final fix wave F2: the needs_correction rows, with this layer's role and features and the fields their corrections touch.
with c as (
    select accession, context_id, string_agg(distinct field, ',' order by field) as fields
    from stg_correction
    where kind = 'value' and context_id is not null
    group by 1, 2
)
select x.cik, x.report_date, x.role, x.role_rule, x.reason, cf.fair_value_fact_count, cf.has_term_fact, c.fields, count(*) as n
from cmp_row_set x
left join int_context_feature cf using (accession, context_id)
left join c using (accession, context_id)
where x.cause = 'needs_correction'
group by all
order by all
