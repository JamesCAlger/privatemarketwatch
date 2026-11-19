-- Task 5: unresolved rows by fund, why (rule and fair value zero or not) and production's handling, with fair value in
-- $m, for the baseline document's unresolved table.
with p as (
    select accession_number as accession, src_context_id as context_id
        , bool_or(accounting_record_class is distinct from 'underlying_schedule') as published
        , bool_or(accounting_record_class = 'underlying_schedule') as jv
    from stg_holdings group by 1, 2
)
select r.cik, r.role_rule, cf.fair_value = 0 as fv_zero
    , case when x.cik is not null then 'lacks_filing' when p.published then 'publishes' when p.jv then 'jv' else 'leaves_out' end as production
    , count(*) n, round(sum(cf.fair_value) / 1e6, 1) as fv_m
from int_source_row r
join int_context_feature cf using (accession, context_id)
left join p using (accession, context_id)
left join cmp_excluded_quarter x on x.cik = r.cik and x.report_date = r.report_date
where r.role = 'unresolved'
group by all order by 1, 2, 3, 4
