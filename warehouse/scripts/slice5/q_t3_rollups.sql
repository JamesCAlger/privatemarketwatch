-- Slice 5 Task 3 report (brief: the Apollo zero-value lines): per quarter, each rollup row (a subtotal decided through a
-- fund rule subtotal_on_fair_value, int_source_row rule 6 with rule_id) that has a zero line beneath it (a context
-- corrections made a position through its fair value, correction_supplies_fair_value, whose identifier label starts
-- with the rollup's label): the rollup's filed fair value and cost against the sum of the positions beneath it after
-- corrections (positions of int_row_corrected in the same filing whose label starts with the rollup's label, the
-- rollup itself left out), corrected values of int_field_corrected. No role changes: the rollup stays an aggregate.
with promoted_zero as (
    select r.accession, r.context_id, cf.identifier_label
    from main.int_row_corrected r
    join main.int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
    where r.row_reason = 'correction_supplies_fair_value'
)
, rollup as (
    select distinct s.cik, s.report_date, s.accession, s.context_id, cf.identifier_label, cf.fair_value, cf.cost
    from main.int_source_row s
    join main.int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    join promoted_zero z on z.accession = s.accession and starts_with(z.identifier_label, cf.identifier_label)
    where s.role = 'aggregate' and s.role_rule = 6 and s.rule_id is not null
)
select u.cik, u.report_date, u.identifier_label as rollup_label, u.fair_value as rollup_fair_value, u.cost as rollup_cost
    , count(r.context_id) as rows_beneath
    , count(r.context_id) filter (where r.row_reason = 'correction_supplies_fair_value') as zero_lines_beneath
    , sum(fv.value) as fair_value_beneath
    , sum(co.value) as cost_beneath
    , u.fair_value - sum(fv.value) as fair_value_gap
    , u.cost - sum(co.value) as cost_gap
    , sum(co.value) filter (where r.row_reason = 'correction_supplies_fair_value') as cost_of_zero_lines
from rollup u
join main.int_context_feature cf on cf.accession = u.accession and starts_with(cf.identifier_label, u.identifier_label)
    and cf.context_id <> u.context_id
join main.int_row_corrected r on r.accession = cf.accession and r.context_id = cf.context_id
left join main.int_field_corrected fv on fv.accession = r.accession and fv.context_id = r.context_id and fv.field = 'fair_value'
left join main.int_field_corrected co on co.accession = r.accession and co.context_id = r.context_id and co.field = 'cost'
group by u.cik, u.report_date, u.identifier_label, u.fair_value, u.cost
order by 1, 2, 3
