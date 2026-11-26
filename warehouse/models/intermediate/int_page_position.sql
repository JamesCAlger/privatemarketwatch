-- Decides, for each position (int_source_row role position, published or not), the printed row of its fair value
-- (text slice P1, 2026-11-26). One row per (accession, context_id).
--
-- The fair-value fact: the fact int_field_read reads as the position's fair value (field fair_value, status read).
-- Its printed rows: the table rows (stg_filed_fact_placement.row_index) where the filed layer places that fact
-- visibly (not in_hidden; a hidden fact's shown row is not used).
-- placement_status:
--   one_row       the fact is placed visibly in exactly one row; row_index, table_index and row_in_table are that row.
--   several_rows  it is placed visibly in two or more distinct rows; no row is taken (all three null).
--   not_placed    no visible placement, or no fair value read; no row.
-- Nothing here says the row is the right one; it is where the filer's inline document puts the fact.
with placed_position as (
    select accession, context_id, cik, report_date, is_published
    from {{ ref('int_source_row') }}
    where role = 'position'
)

, fair_value_fact as (
    select accession, context_id, fact_id
    from {{ ref('int_field_read') }}
    where field = 'fair_value' and status = 'read' and fact_id is not null
)

, printed as (
    select f.accession, f.context_id, count(distinct pl.row_index) as printed_rows, min(pl.row_index) as row_index
    from fair_value_fact f
    join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = f.accession and pl.fact_id = f.fact_id
    where pl.row_index is not null and not pl.in_hidden
    group by 1, 2
)

select
    p.accession
    , p.context_id
    , p.cik
    , p.report_date
    , p.is_published
    , f.fact_id as fair_value_fact_id
    , case
        when pr.printed_rows = 1 then 'one_row'
        when pr.printed_rows > 1 then 'several_rows'
        else 'not_placed'
    end as placement_status
    , dr.row_index
    , dr.table_index
    , dr.row_in_table
from placed_position p
left join fair_value_fact f on f.accession = p.accession and f.context_id = p.context_id
left join printed pr on pr.accession = p.accession and pr.context_id = p.context_id
left join {{ ref('stg_filed_document_row') }} dr
    on dr.accession = pr.accession and dr.row_index = pr.row_index and pr.printed_rows = 1
