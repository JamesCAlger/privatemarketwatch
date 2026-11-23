-- Rate ruling B: the compared rows resting on a scale-rule value that are not equal to production, one per row, with
-- the printed cell of the rate tag. Run with scripts/slice2/run_sql.py.
with scaled as (
    select accession, context_id, field, cik, report_date, value, scale_rule_ids
    from int_field_normalised
    where scale_rule_ids is not null
)

select s.cik, s.report_date, s.accession, s.context_id, s.field, m.basis, s.value, m.value_production, m.outcome
    , m.cause, m.cause_detail, sc.printed_cell
from scaled s
join cmp_rate m on m.accession = s.accession and m.context_id = s.context_id and m.field = s.field
left join int_rate_scale sc
    on sc.accession = s.accession and sc.context_id = s.context_id
    and sc.field = case s.field when 'spread' then 'spread' when 'pik_rate' then 'pik_rate' else 'interest_rate_tag' end
where m.outcome <> 'equal'
order by 1, 2, 4, 5
