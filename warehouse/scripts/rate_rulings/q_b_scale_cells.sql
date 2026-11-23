-- Rate ruling B: example printed cells (the fact's own cell and the next two) for values filed above 1 in a ratio
-- unit, up to 3 rows per fund, filing and field, to read how the page prints them. Run with scripts/slice2/run_sql.py.
with r as (
    select r.cik, r.accession, r.field, r.context_id, r.value_filed, r.printed_text, r.fact_id
        , row_number() over (partition by r.cik, r.accession, r.field order by r.context_id) as k
    from int_field_read r
    where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
      and r.status = 'read' and not r.is_nil and r.unit in ('pure', 'utr:Rate') and r.value_filed > 1
)
select r.cik, r.accession, r.field, r.context_id, r.value_filed, r.printed_text, pl.scale, pl.format
    , dr.cells[coalesce(pl.cell_index, pl.shown_cell_index)] as prev_cell
    , dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1] as own_cell
    , dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 2] as next_cell
    , dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 3] as next_cell_2
from r
left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
left join stg_filed_document_row dr
    on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
where r.k <= 3
order by r.cik, r.accession, r.field, r.k
