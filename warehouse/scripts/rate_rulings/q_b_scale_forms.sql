-- Rate ruling B: how the printed cell of each value filed above 1 in a ratio unit reads, per fund, filing and field.
--   percent_form   the fact's cell (or, where the cell holds only the number, the next cell) prints the number then a
--                  percent sign: "13.00%", "6.25% PIK", "9.48% (2.88% PIK)"
--   margin_bps     the cell prints a reference rate plus the number in basis points: "S+610, 1.00% Floor"
--   other          anything else
-- and how many cells name PIK. Run with scripts/slice2/run_sql.py.
with r as (
    select r.cik, r.accession, r.report_date, r.field, r.context_id, r.value_filed, r.printed_text, r.fact_id
    from int_field_read r
    where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
      and r.status = 'read' and not r.is_nil and r.unit in ('pure', 'utr:Rate') and r.value_filed > 1
)

, c as (
    select
        r.*
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1], '') as own_cell
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 2], '') as next_cell
    from r
    left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
    left join stg_filed_document_row dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
)

, f as (
    select
        *
        , case
            when position(printed_text in own_cell) > 0
                 and (regexp_matches(own_cell, '(^|[^0-9.])' || replace(printed_text, '.', '\.') || '\s*%')
                      or (trim(own_cell) = trim(printed_text) and ltrim(next_cell) like '\%%' escape '\'))
                then 'percent_form'
            when regexp_matches(own_cell, '^\s*[A-Z]+\s*\+\s*' || printed_text || '([^0-9.]|$)') then 'margin_bps'
            else 'other'
          end as form
    from c
)

select cik, accession, report_date, field
    , count(*) as rows_above_one
    , count(*) filter (where form = 'percent_form') as percent_form
    , count(*) filter (where form = 'margin_bps') as margin_bps
    , count(*) filter (where form = 'other') as other
    , count(*) filter (where upper(own_cell) like '%PIK%') as cell_names_pik
    , any_value(own_cell) filter (where form = 'other') as other_example
from f
group by all
order by cik, report_date, field
