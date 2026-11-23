-- Slice 4 Task 5: the rows of one cmp_rate cause detail (DuckDB variable detail), for the baseline doc.
--   run_sql_vars.py q_t5_detail_rows.sql <max_rows> detail=<cause_detail>
select basis, cik, report_date, accession, context_id, field, outcome, value_new, value_production, text_new,
    text_production, new_reason
from cmp_rate
where cause_detail = getvariable('detail')
order by basis, cik, report_date, context_id, field
