{#- The body of model int_rate_scale, moved here unchanged (slice 5 Task 3) so that int_field_reread can run it on
    the rows corrections make positions. The model's header says what it decides. Inputs: read_rel. -#}
{% macro rate_scale(read_rel) -%}
with above_one as (
    select r.accession, r.context_id, r.field, r.cik, r.report_date, r.value_filed, r.unit, r.printed_text, r.fact_id
    from {{ read_rel }} r
    where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
      and r.status = 'read' and not r.is_nil and r.value_filed > 1
      and {{ unit_kind('r.unit') }} = 'pure'
)

, scale_rule as (
    select
        rule_id
        , cik
        , sel_accession as accession
        , split_part(parameter, ' ', 1) as field
        , split_part(parameter, ' ', 2) as printed_reading
    from {{ ref('stg_reading_rule') }}
    where action = 'ratio_value_is_percent'
)

, printed as (
    select
        a.*
        , try_cast(replace(regexp_extract(a.printed_text, '[0-9][0-9,]*(\.[0-9]+)?', 0), ',', '') as double)
            as printed_number
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1], '') as own_cell
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 2], '') as next_cell
    from above_one a
    left join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = a.accession and pl.fact_id = a.fact_id
    left join {{ ref('stg_filed_document_row') }} dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
)

, formed as (
    select
        p.* exclude (next_cell)
        , case
            when p.printed_text is null then 'other'
            when regexp_matches(p.own_cell, '(^|[^0-9.])' || replace(trim(p.printed_text), '.', '\.') || '\s*%')
                or (trim(p.own_cell) = trim(p.printed_text) and ltrim(p.next_cell) like '\%%' escape '\')
                then 'percent_form'
            when regexp_matches(p.own_cell, '^\s*[A-Z]+\s*\+\s*' || replace(trim(p.printed_text), '.', '\.') || '([^0-9.]|$)')
                then 'margin_bps'
            else 'other'
          end as printed_form
    from printed p
)

select
    f.accession
    , f.context_id
    , f.field
    , f.cik
    , f.report_date
    , f.value_filed
    , f.unit
    , f.printed_text
    , f.printed_number
    , f.printed_form
    , f.own_cell as printed_cell
    , s.rule_id as scale_rule_id
    , s.printed_reading
    , case
        when s.rule_id is null then 'no_scale_rule'
        when s.printed_reading = 'percent' and f.printed_form = 'percent_form'
            and abs(f.printed_number - f.value_filed) <= {{ var('rate_legs_tolerance') }} then 'kept_as_percent'
        when s.printed_reading = 'basis_points' and f.field = 'spread' and f.printed_form = 'margin_bps'
            and abs(f.printed_number - f.value_filed * 100) <= {{ var('rate_legs_tolerance') }} then 'kept_as_percent'
        else 'printed_disagrees'
      end as outcome
from formed f
left join scale_rule s on s.cik = f.cik and s.accession = f.accession and s.field = f.field
{%- endmacro %}
