-- Slice 4 Task 2: every unresolved row of the new fields, with its facts (value, unit, text). Row limit by the runner.
select r.cik, r.report_date, r.field, r.reason, r.accession, r.context_id, r.fact_count
    , f.fact_id, f.value_numeric, f.value_text, u.numerator as unit
from int_field_read r
join stg_filed_fact f on f.accession = r.accession and f.context_id = r.context_id
join concept_map m on m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern
    and m.read_field = r.field
left join stg_filed_unit u on u.accession = f.accession and u.unit_id = f.unit_id
where r.status = 'unresolved'
  and r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread', 'maturity_date')
order by r.cik, r.field, r.report_date, r.context_id, f.fact_index
