-- Summarises the spread-plus-base check per column unit, quarter and code (text slice R phase 1, 2026-11-26). One row
-- per (unit_key, report_date, code_key). Every quarter is its own row: a quarter passes or fails on its own (spec
-- section 11), never as a pooled average.
--
-- Rows: int_text_check_spread_base. code_key: the code upper case, white space removed. is_read_sofr: the existing
-- rules read the code as SOFR at that quarter (all rows of a code at one date share it).
-- positions: rows; checked: rows with check_state pass or fail; passed; pass_share = passed / checked (null when no
-- row was checked); pik_present, inputs_missing, no_sofr_value: the rows not judged. median_residual over checked rows.
select
    unit_key
    , report_date
    , upper(replace(code, ' ', '')) as code_key
    , min(cik) as cik
    , bool_and(is_read_sofr) as is_read_sofr
    , count(*) as positions
    , count(*) filter (where is_published) as published_positions
    , count(*) filter (where check_state in ('pass', 'fail')) as checked
    , count(*) filter (where check_state = 'pass') as passed
    , count(*) filter (where check_state = 'pass')
        / nullif(count(*) filter (where check_state in ('pass', 'fail')), 0) as pass_share
    , count(*) filter (where check_state = 'pik_present') as pik_present
    , count(*) filter (where check_state = 'inputs_missing') as inputs_missing
    , count(*) filter (where check_state = 'no_sofr_value') as no_sofr_value
    , median(residual) filter (where check_state in ('pass', 'fail')) as median_residual
from {{ ref('int_text_check_spread_base') }}
group by 1, 2, 3
