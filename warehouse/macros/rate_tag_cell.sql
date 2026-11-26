{#- The body of model int_rate_tag_cell, moved here unchanged (slice 5 Task 3) so that int_field_reread can run it on
    the rows corrections make positions. The model's header says what it decides. Inputs: read_rel. -#}
{% macro rate_tag_cell(read_rel) -%}
with tag as (
    select accession, context_id, fact_id
    from {{ read_rel }}
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
{%- endmacro %}
