-- Rate ruling A (owner, 2026-11-23): cash legs set equal to the all-in rate (reason cash_equals_all_in), per fund,
-- and how many of them print 'PIK' in the rate tag's own cell (the residual risk: a PIK that exists but is not tagged
-- gives an overstated cash leg). Also the published comparison outcome of those rows. Run with scripts/slice2/run_sql.py.
with cash as (
    select n.accession, n.context_id, n.cik, n.report_date, n.value
    from int_field_normalised n
    where n.field = 'interest_rate_cash' and n.reason = 'cash_equals_all_in'
)

, cell as (
    select c.*
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1], '') as rate_cell
    from cash c
    join int_field_read r
        on r.accession = c.accession and r.context_id = c.context_id and r.field = 'interest_rate_tag'
    left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
    left join stg_filed_document_row dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
)

select c.cik
    , count(*) as cash_equals_all_in
    , count(*) filter (where upper(c.rate_cell) like '%PIK%') as rate_cell_names_pik
    , count(*) filter (where m.outcome = 'production_empty') as published_production_empty
    , count(*) filter (where m.outcome = 'equal') as published_equal
    , count(*) filter (where m.outcome = 'differs') as published_differs
    , any_value(c.rate_cell) filter (where upper(c.rate_cell) like '%PIK%') as pik_example
from cell c
left join cmp_rate m
    on m.accession = c.accession and m.context_id = c.context_id and m.field = 'interest_rate_cash'
    and m.basis = 'published'
group by all
order by 1
