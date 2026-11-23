-- The printed cell of each position's interest-rate tag, and whether that cell prints a PIK (controller ruling R1,
-- 2026-11-23, fix round 1 of the rate rulings). One row per (accession, context_id) where int_field_read reads the
-- interest-rate tag with a value (status read, not nil).
-- printed_cell: the table cell the filed layer places the tag's fact in (fact_placement cell_index, or for a hidden
-- fact the cell that shows it, shown_cell_index), as int_rate_scale reads it. Null when the fact is not placed.
-- prints_pik, the exact test: the lowercased cell contains the letters 'pik' as a word of their own, that is not
-- preceded and not followed by a letter: regexp (^|[^a-z])pik([^a-z]|$). Examples that trip it: "6.00% PIK",
-- "11.62% (4.50% PIK)", "12.74% (incl. 0.50% PIK)". Examples that do not: "9.48%", "Pikes Peak 7.00%" (letters
-- follow), "SPIKE" (letters before), a PIK printed in another cell of the row (only the tag's own cell is read). A
-- null cell is false (not known to print a PIK). Narrow on purpose: it reads one cell and one word, nothing else.
-- int_field_normalised reads prints_pik: under rate_is_all_in with no PIK rate read, a cell that prints a PIK leaves
-- the cash leg unresolved (pik_printed_not_tagged) instead of setting it equal to the all-in rate (ruling A).
with tag as (
    select accession, context_id, fact_id
    from {{ ref('int_field_read') }}
    where field = 'interest_rate_tag' and status = 'read' and not is_nil and value_filed is not null
)

, placed as (
    select
        t.accession
        , t.context_id
        , dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1] as printed_cell
    from tag t
    left join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = t.accession and pl.fact_id = t.fact_id
    left join {{ ref('stg_filed_document_row') }} dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
)

select
    accession
    , context_id
    , printed_cell
    , coalesce(regexp_matches(lower(printed_cell), '(^|[^a-z])pik([^a-z]|$)'), false) as prints_pik
from placed
