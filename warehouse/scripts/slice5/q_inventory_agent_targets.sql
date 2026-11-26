-- Slice 5 Task 2 inventory: where the agent stores' keys land today. add_row: each added position's (accession,
-- src_context_id) in int_source_row (its role here) and in production's holdings (stg_holdings). B2 value leaf: the
-- row_id in stg_holdings (its accession and context). Read-only; nothing is applied.
with add_group as (
    select add_group_id, any_value(cik) as cik, any_value(report_date) as report_date, any_value(accession) as accession
        , any_value(context_id) as context_id
        , any_value(value) filter (where field = 'fair_value') as fair_value_added
    from main.stg_correction where kind = 'add_row' group by 1
)
select
    'add_row' as what, g.add_group_id as key, g.cik, g.report_date, g.accession, g.context_id
    , s.role as role_here
    , (select count(*) from main.stg_holdings h
        where h.accession_number = g.accession and h.src_context_id = g.context_id) as production_rows
    , g.fair_value_added
from add_group g
left join main.int_source_row s on s.accession = g.accession and s.context_id = g.context_id
union all
select
    'b2_value', c.row_id, c.cik, c.report_date, any_value(h.accession_number), any_value(h.src_context_id)
    , any_value(s.role), count(distinct h.row_id), string_agg(c.field || '=' || c.value, ';' order by c.field)
from main.stg_correction c
left join main.stg_holdings h on h.row_id = c.row_id
left join main.int_source_row s on s.accession = h.accession_number and s.context_id = h.src_context_id
where c.row_id is not null
group by c.row_id, c.cik, c.report_date
order by 1, 2
