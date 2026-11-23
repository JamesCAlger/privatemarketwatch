-- Rate ruling B: every rate value that rests on a number a scale rule kept as a percent (int_field_normalised
-- scale_rule_ids), against production (cmp_rate, both bases; rate_kind follows the interest_rate row). Part 1 counts
-- per fund, field and outcome; run q_b_scaled_differs.sql for the rows that are not equal. Run with
-- scripts/slice2/run_sql.py.
with scaled as (
    select accession, context_id, field, cik, report_date, value, scale_rule_ids
    from int_field_normalised
    where scale_rule_ids is not null
)

select s.cik, s.field, coalesce(m.basis, 'not compared') as basis, coalesce(m.outcome, '-') as outcome
    , coalesce(m.cause || '|' || m.cause_detail, '-') as cause, count(*) as n
from scaled s
left join cmp_rate m on m.accession = s.accession and m.context_id = s.context_id and m.field = s.field
group by all
order by 1, 2, 3, 4, 5
