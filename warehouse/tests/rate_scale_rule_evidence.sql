-- Owner ruling B (2026-11-23): a scale rule (fund rule ratio_value_is_percent) may decide only a row whose own printed
-- number agrees. This test re-checks, from the filed layer and independently of int_rate_scale's own columns, every
-- row int_rate_scale marks kept_as_percent: the filed fact's displayed text, read as a number, must equal the tagged
-- value (reading 'percent', with a percent sign printed right after it in its cell or at the start of the next cell)
-- or the tagged value times 100 (reading 'basis_points', spread only, printed after a '+' as in 'S+450'). Any row
-- that fails blocks the build: a rule deciding a row without agreeing evidence.
with kept as (
    select s.accession, s.context_id, s.field, s.scale_rule_id, s.printed_reading, r.fact_id, r.value_filed
    from {{ ref('int_rate_scale') }} s
    join {{ ref('int_field_read') }} r
        on r.accession = s.accession and r.context_id = s.context_id and r.field = s.field
    where s.outcome = 'kept_as_percent'
)

, shown as (
    select
        k.*
        , pl.displayed_text
        , try_cast(replace(trim(pl.displayed_text), ',', '') as double) as displayed_number
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1], '') as cell
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 2], '') as cell_after
    from kept k
    left join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = k.accession and pl.fact_id = k.fact_id
    left join {{ ref('stg_filed_document_row') }} dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
)

select accession, context_id, field, scale_rule_id, printed_reading, value_filed, displayed_text, cell
    , 'scale rule decided a row whose print does not agree' as problem
from shown
where not coalesce(
    case printed_reading
        when 'percent' then
            abs(displayed_number - value_filed) < 0.000001
            and (strpos(replace(cell, ' ', ''), trim(displayed_text) || '%') > 0
                 or (trim(cell) = trim(displayed_text) and left(ltrim(cell_after), 1) = '%'))
        when 'basis_points' then
            field = 'spread'
            and abs(displayed_number - value_filed * 100) < 0.0001
            and strpos(replace(cell, ' ', ''), '+' || trim(displayed_text)) > 0
    end, false)
