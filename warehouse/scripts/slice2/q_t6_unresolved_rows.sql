-- Task 6: every unresolved context, with its label, fair value, rule, and what production does with it
-- (publishes, jv = in a JV schedule, leaves_out, lacks_filing = excluded quarter). The false-positive set of Task 6 is
-- the rows with production in (leaves_out, lacks_filing).
with p as (
    select accession_number as accession, src_context_id as context_id
        , bool_or(accounting_record_class is distinct from 'underlying_schedule') as published
        , bool_or(accounting_record_class = 'underlying_schedule') as jv
    from stg_holdings group by 1, 2
)
select r.cik, r.report_date, r.accession, r.context_id, r.role_rule, r.scope
    , case when p.published then 'publishes' when p.jv then 'jv' when x.cik is not null then 'lacks_filing' else 'leaves_out' end as production
    , cf.fair_value, cf.cost, cf.identifier_label
    , exists (select 1 from stg_filed_fact f where f.accession = r.accession and f.context_id = r.context_id
              and f.concept_local ilike '%Commitment%') as has_commitment_fact
    , r.reason
from int_source_row r
join int_context_feature cf using (accession, context_id)
left join p using (accession, context_id)
left join cmp_excluded_quarter x on x.cik = r.cik and x.report_date = r.report_date
where r.role = 'unresolved'
order by r.cik, production, cf.identifier_label, r.report_date
