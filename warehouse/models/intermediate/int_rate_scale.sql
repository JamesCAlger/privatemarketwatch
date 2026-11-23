-- Decides the scale of each rate number filed above 1 in a ratio unit (pure or utr:Rate): owner ruling B, 2026-11-23.
-- One row per (accession, context_id, field) of int_field_read where the field is a rate tag, the PIK rate or the
-- spread, read with a number above 1 in a ratio unit. Such a number may already be a percent; its size alone does not
-- decide (controller ruling, slice 4 Task 3). A fund rule decides it instead: action ratio_value_is_percent in the
-- fund's wrapper copy (warehouse/wrappers/<cik>.json, reading_rules), naming the filing (accession) and, in its
-- parameter, the read field and the printed form the evidence rests on:
--   '<field> percent'        the page prints the same number followed by a percent sign ("13.00%", "6.25% PIK")
--   '<field> basis_points'   the page prints the number times 100 after a reference rate ("S+450" for 4.50); spread
--                            only (a printed margin is a spread; tests/rate_scale_rule_selectors.sql)
-- The rule decides a row only where that row's own print agrees (per row, not per filing): a row whose print is
-- missing or disagrees stays scale_not_decided. tests/rate_scale_rule_evidence.sql re-checks every decided row against
-- the filed layer; tests/rate_scale_rule_live.sql fails a rule that decides no row.
-- outcome:
--   kept_as_percent    a rule matches and the print agrees: the value is the filed number, already a percent
--   printed_disagrees  a rule matches, the print is missing or does not agree: not decided
--   no_scale_rule      no rule: not decided
-- printed_number: the first number in the fact's printed text (int_field_read.printed_text), commas removed.
-- printed_form: percent_form when the fact's cell prints that number then a percent sign (or the cell holds only the
-- number and the next cell starts with a percent sign); margin_bps when the cell prints capital letters, '+', then the
-- number; else other.
with above_one as (
    select r.accession, r.context_id, r.field, r.cik, r.report_date, r.value_filed, r.unit, r.printed_text, r.fact_id
    from {{ ref('int_field_read') }} r
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
