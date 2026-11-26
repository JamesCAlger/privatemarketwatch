-- Decides the canonical value of each rate field of each position row, by applying the rule int_field_rule chose
-- (spec intermediate_spine.md 6.4). One row per (accession, context_id, field): interest_rate (the all-in rate,
-- percent; rate_kind beside it), interest_rate_cash (the cash leg, percent), pik_rate, spread (percent) and
-- maturity_date (in value_date). value_filed stays beside the value. The rate half of int_field_normalised (slice 5
-- Task 1 split it out unchanged; the amount half is int_amount_normalised, and int_field_normalised is the union of
-- the two). Columns are int_field_normalised's: currency, fx_rate and fx_rate_date are null here.
--
-- This model prepares the inputs, one row per position (CTE reading_input): each rate read field with its state and
-- its number in percent, and the rule of each rate rule field. The reading itself, and what each rate action does, is
-- macro rate_reading (macros/rate_reading.sql), so that it can run again on corrected inputs.
-- Input states: value (usable), absent (no fact or nil only), unresolved (why says why). A number in a ratio unit
-- (unit kind pure, seeds/unit_kind.csv) is a fraction: times 100 (fraction_to_percent). Above 1 it may already be a
-- percent; its scale is not decided by its size (controller ruling): unresolved scale_not_decided, unless a fund scale
-- rule kept it as a percent where the row's own print agrees (int_rate_scale, owner ruling B 2026-11-23): then the
-- filed number is the percent. A number in a unit that is not a ratio: unresolved unit_not_pure. The maturity date is a
-- value as read.
-- The body is macro rate_normalised (macros/rate_normalised.sql, slice 5 Task 3), run here on its usual inputs; int_field_reread
-- runs the same macro on the rows corrections make positions.
-- Slice 5 Task 4 (owner decision 5): a taker of int_rate_adjacent reads the rate facts of its giver. For the taker
-- positions only, the reads of interest_rate_tag, interest_rate_cash_tag, pik_rate and spread are the giver's (field_read
-- run on the giver context, given the taker's context id), and the taker's rate rules, scale decisions and rate-cell
-- test are chosen again on those reads with the same macros (field_rule, rate_scale, rate_tag_cell). Every other
-- position reads int_field_rule, int_field_read, int_rate_scale and int_rate_tag_cell as before (rows unchanged). A
-- taker that is not a filed position is not read here (int_field_reread does not apply the rule; tests/
-- int_rate_adjacent_taker_is_filed_position.sql keeps it so).
with adjacent as (
    select * from {{ ref('int_rate_adjacent') }} where taker_is_position
)

, adj_taker as (
    select accession, taker_context_id as context_id, cik, report_date from adjacent
)

, adj_giver as (
    select accession, giver_context_id as context_id, cik, report_date from adjacent
)

, adj_moved_field as (
    select a.accession, a.taker_context_id as context_id, f.field
    from adjacent a
    cross join (select unnest(['interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread']) as field) f
)

, giver_read as (
    {{ field_read('adj_giver') }}
)

, read_all as (
    select r.*
    from {{ ref('int_field_read') }} r
    anti join adj_moved_field m on m.accession = r.accession and m.context_id = r.context_id and m.field = r.field
    union all by name
    select g.* replace (a.taker_context_id as context_id, a.cik as cik, a.report_date as report_date)
    from giver_read g
    join adjacent a on a.accession = g.accession and a.giver_context_id = g.context_id
    where g.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
)

, taker_read as (
    select r.* from read_all r semi join adj_taker t on t.accession = r.accession and t.context_id = r.context_id
)

, taker_rule as (
    {{ field_rule('taker_read') }}
)

, taker_scale as (
    {{ rate_scale('taker_read') }}
)

, taker_cell as (
    {{ rate_tag_cell('taker_read') }}
)

, rule_all as (
    select r.* from {{ ref('int_field_rule') }} r
    anti join adj_taker t on t.accession = r.accession and t.context_id = r.context_id
    union all by name
    select * from taker_rule
)

, scale_all as (
    select s.* from {{ ref('int_rate_scale') }} s
    anti join adj_taker t on t.accession = s.accession and t.context_id = s.context_id
    union all by name
    select * from taker_scale
)

, cell_all as (
    select c.* from {{ ref('int_rate_tag_cell') }} c
    anti join adj_taker t on t.accession = c.accession and t.context_id = c.context_id
    union all by name
    select * from taker_cell
)

select * from ({{ rate_normalised('rule_all', 'read_all', 'scale_all', 'cell_all') }})
