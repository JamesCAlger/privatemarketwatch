-- Slice 3 Task 3: fair value and cost on positions of the filings a bracketed_unsigned rule lists, with the printed
-- cell, its neighbours and the tagged sign. Shows where printed brackets and the tagged sign disagree.
with listed as (
    select cik, sel_accession as accession from stg_reading_rule where action = 'bracketed_unsigned'
)
, r as (
    select f.accession, f.context_id, f.field, f.value_filed, f.printed_text, f.fact_id
    from int_field_read f join listed l on l.accession = f.accession
    where f.field in ('fair_value', 'cost') and f.status = 'read' and f.value_filed is not null
)
, p as (
    select r.*, pl.sign, pl.row_index, pl.cell_index, pl.shown_row_index
        , coalesce(pl.row_index, pl.shown_row_index) as ri, coalesce(pl.cell_index, pl.shown_cell_index) as ci
    from r left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
)
select p.accession, p.context_id, p.field, p.value_filed, p.sign, p.printed_text
    , dr.cells[p.ci] as cell_before, dr.cells[p.ci + 1] as cell, dr.cells[p.ci + 2] as cell_after
from p left join stg_filed_document_row dr on dr.accession = p.accession and dr.row_index = p.ri
where (dr.cells[p.ci + 1] like '%(%' or dr.cells[p.ci] like '%(' or p.sign = '-' or p.value_filed < 0)
order by 1, 2, 3
limit 400
