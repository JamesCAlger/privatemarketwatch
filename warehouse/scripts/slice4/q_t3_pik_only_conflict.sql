-- Slice 4 Task 3 (stop condition): rows a pik_only_is_coupon and a pik_only_is_margin rule of the same fund would both
-- select. Feature pik_tag_only as production reads "a PIK-only row" (pipeline/financial_conventions.py prepare: PIK
-- above zero, no reported rate, no spread): PIK read with a value above zero, no interest-rate or cash-pay tag carried,
-- no spread value. Funds come from stg_reading_rule (no CIK here). Also: how many of those rows carry any tagged fact
-- whose concept names a reference rate (the feature production separates the two readings by is text: the row's
-- reference rate and coupon type).
with both_funds as (
    select cik
    from stg_reading_rule
    where action in ('pik_only_is_coupon', 'pik_only_is_margin')
    group by cik
    having count(distinct action) = 2
)

, rows as (
    select r.cik, r.accession, r.context_id, any_value(r.report_date) as report_date
        , bool_or(r.field = 'pik_rate' and r.status = 'read' and r.value_filed > 0) as pik_positive
        , bool_or(r.field in ('interest_rate_tag', 'interest_rate_cash_tag') and r.status <> 'absent') as has_rate_tag
        , bool_or(r.field = 'spread' and r.status = 'read' and r.value_filed is not null) as spread_value
        , bool_or(r.field = 'spread' and r.status <> 'absent') as spread_carried
    from int_field_read r
    semi join both_funds b on b.cik = r.cik
    group by 1, 2, 3
)

, refrate as (
    select distinct f.accession, f.context_id
    from stg_filed_fact f
    where lower(f.concept_local) like '%referencerate%' or lower(f.concept_local) like '%variableinterestratetype%'
)

select r.cik, r.report_date
    , count(*) filter (where r.pik_positive and not r.has_rate_tag and not r.spread_value) as pik_tag_only
    , count(*) filter (where r.pik_positive and not r.has_rate_tag and not r.spread_carried) as pik_only_no_spread_fact
    , count(*) filter (where r.pik_positive and not r.has_rate_tag and not r.spread_value and s.is_published)
        as pik_tag_only_published
    , count(*) filter (where r.pik_positive and not r.has_rate_tag and not r.spread_value and rr.context_id is not null)
        as with_reference_rate_fact
from rows r
join int_source_row s on s.accession = r.accession and s.context_id = r.context_id
left join refrate rr on rr.accession = r.accession and rr.context_id = r.context_id
group by all
order by 1, 2
