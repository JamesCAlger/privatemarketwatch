{#- Text slice P fix round 1: every placed filed fact that is read as a field, on any row (positions, subtotals,
    totals), with the cell it is placed in and that cell's column (int_page_cell_column). field: the field int_field_read
    reads the fact as (positions, any rule, the fund's own concepts included); otherwise the read_field of the
    concept_map row whose local name and namespace pattern match the fact's concept (standard concepts on any row). A
    hidden fact counts in the cell that shows it. Facts in cells with no int_page_cell_column row (tables without a
    header, header rows) are left out. Used by tests/baseline_int_page_field_split_columns.sql and
    tests/baseline_int_page_field_fact_no_column.sql. -#}
{% macro page_field_fact() -%}
with read_fact as (
    select accession, fact_id, min(field) as field
    from {{ ref('int_field_read') }}
    where status = 'read' and fact_id is not null
    group by 1, 2
)

, mapped_fact as (
    select f.accession, f.fact_id, min(m.read_field) as field
    from {{ ref('stg_filed_fact') }} f
    join {{ ref('concept_map') }} m
        on m.concept_local = f.concept_local and m.read_field is not null
        and f.concept_namespace like replace(m.namespace_pattern, '*', '%')
    group by 1, 2
)

, fact_field as (
    select coalesce(r.accession, m.accession) as accession, coalesce(r.fact_id, m.fact_id) as fact_id
        , coalesce(r.field, m.field) as field
    from read_fact r
    full join mapped_fact m on m.accession = r.accession and m.fact_id = r.fact_id
)

select ff.accession, ff.fact_id, ff.field, cc.table_index, cc.row_index, cc.cell_index, cc.column_rule
    , cc.header_signature
from fact_field ff
join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = ff.accession and pl.fact_id = ff.fact_id
join {{ ref('int_page_cell_column') }} cc
    on cc.accession = pl.accession
    and cc.row_index = coalesce(pl.row_index, pl.shown_row_index)
    and cc.cell_index = coalesce(pl.cell_index, pl.shown_cell_index)
{%- endmacro %}
