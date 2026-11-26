-- Slice 5 Task 1, item f: the CI fixture's positions per filing with their report date and whether a rate tag is read,
-- to choose the fixture row that gets a rate tag and no rate reading. Run on a fixture ci.duckdb.
select s.accession, s.report_date, s.context_id
    , bool_or(r.field = 'interest_rate_tag' and r.status = 'read') as rate_tag_read
    , any_value(r.unit) filter (where r.field = 'interest_rate_tag') as rate_unit
    , any_value(r.value_filed) filter (where r.field = 'interest_rate_tag') as rate_filed
from main.int_source_row s
left join main.int_field_read r on r.accession = s.accession and r.context_id = s.context_id
where s.role = 'position'
group by all
order by 1, 3
