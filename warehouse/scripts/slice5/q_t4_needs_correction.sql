-- Slice 5 Task 4: the published rate rows cmp_rate calls needs_correction (on int_field_normalised), and how many of
-- them now carry production's value in int_field_corrected (same tolerance as cmp_rate; the kind compared as text; a
-- maturity as a date). Also the counts on all published rate rows where the corrected value differs from production
-- but the normalised one did not (corrections that move a row away from production). Read-only.
with c as (
    select c.field, c.accession, c.context_id, c.value_production, c.date_production, c.text_production, c.cause
        , f.value, f.value_date, f.rate_kind, f.status, f.correction_id, f.value_normalised, f.rate_kind_normalised
    from cmp_rate c
    left join int_field_corrected f
        on f.accession = c.accession and f.context_id = c.context_id
        and f.field = case c.field when 'rate_kind' then 'interest_rate' else c.field end
    where c.basis = 'published'
)
, judged as (
    select *
        , case
            when field = 'rate_kind' then rate_kind is not distinct from text_production
            when field = 'maturity_date' then value_date is not distinct from date_production
            else coalesce(abs(value - value_production) <= 1e-9, value is null and value_production is null)
          end as equal_after
        , case
            when field = 'rate_kind' then rate_kind_normalised is not distinct from text_production
            when field = 'maturity_date' then null
            else coalesce(abs(value_normalised - value_production) <= 1e-9, value_normalised is null and value_production is null)
          end as equal_before
    from c
)
select field, cause, count(*) as rows, count(*) filter (where equal_after) as equal_after
    , count(*) filter (where correction_id is not null) as corrected
from judged
where cause = 'needs_correction'
group by all
union all
select field, 'moved_away', count(*), null, count(*) filter (where correction_id is not null)
from judged where equal_before and not equal_after
group by all
order by 2, 1
