-- Slice 5 Task 4: published needs_correction rate rows of cmp_rate that still differ from production after the rate
-- corrections, with the corrected row. Read-only.
with c as (
    select c.field, c.cik, c.accession, c.context_id, c.value_production, c.text_production, c.cause_detail
        , f.value, f.rate_kind, f.status, f.reason, f.correction_id, f.value_normalised
    from cmp_rate c
    left join int_field_corrected f
        on f.accession = c.accession and f.context_id = c.context_id
        and f.field = case c.field when 'rate_kind' then 'interest_rate' else c.field end
    where c.basis = 'published' and c.cause = 'needs_correction'
)
select c.*, a.outcome, a.reason as outcome_reason
from c
left join (select accession, context_id, string_agg(distinct outcome, ',') as outcome, string_agg(distinct reason, ',') as reason
           from int_correction_application where step = 'reading_input' group by 1, 2) a using (accession, context_id)
where case
        when field = 'rate_kind' then rate_kind is distinct from text_production
        else not coalesce(abs(value - value_production) <= 1e-9, value is null and value_production is null)
      end
  and field <> 'maturity_date'
order by field, accession, context_id
