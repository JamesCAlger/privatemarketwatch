-- Slice 3 Task 3: rows each par_tagged_as_units rule changes, per fund, mode and report date (principal_amount rows),
-- with the scale chosen. For docs/owner_review_value_size_rules_2026-11-22.md.
select u.cik, u.parameter as mode, u.report_date, u.value_scale, count(*) as rows_changed
    , count(*) filter (where s.is_published) as published
from int_field_rule u
join int_source_row s on s.accession = u.accession and s.context_id = u.context_id
where u.field = 'principal_amount' and u.action = 'par_tagged_as_units'
group by all
order by 1, 2, 3, 4
limit 300
