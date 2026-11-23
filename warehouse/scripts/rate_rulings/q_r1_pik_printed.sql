-- Controller ruling R1 (fix round 1): cash legs that ruling A sets equal to the all-in rate (reason cash_equals_all_in)
-- where the rate tag's own printed cell prints a PIK, by the exact test of int_rate_tag_cell: lower(cell) matches
-- (^|[^a-z])pik([^a-z]|$). Per fund and basis (published / unpublished / not compared), with production's cash leg and
-- its PIK source. Reads int_field_normalised as built before or after the fix: before, the reason is
-- cash_equals_all_in; after, pik_printed_not_tagged. Run with scripts/slice2/run_sql.py.
with cash as (
    select n.accession, n.context_id, n.cik, n.report_date, n.value, n.reason
    from int_field_normalised n
    where n.field = 'interest_rate_cash' and n.reason in ('cash_equals_all_in', 'pik_printed_not_tagged')
)

, cell as (
    select c.*
        , dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1] as rate_cell
    from cash c
    join int_field_read r
        on r.accession = c.accession and r.context_id = c.context_id and r.field = 'interest_rate_tag'
    left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
    left join stg_filed_document_row dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
)

, flagged as (
    select * from cell
    where coalesce(regexp_matches(lower(rate_cell), '(^|[^a-z])pik([^a-z]|$)'), false)
)

select f.cik, f.reason, coalesce(m.basis, 'not compared') as basis
    , coalesce(m.outcome, '-') as cash_outcome
    , coalesce(m.cause || '|' || m.cause_detail, '-') as cash_cause
    , count(*) as n
    , count(*) filter (where m.value_production = 0) as production_cash_zero
    , any_value(f.rate_cell) as example_cell
from flagged f
left join cmp_rate m
    on m.accession = f.accession and m.context_id = f.context_id and m.field = 'interest_rate_cash'
group by all
order by 1, 2, 3, 4, 5
