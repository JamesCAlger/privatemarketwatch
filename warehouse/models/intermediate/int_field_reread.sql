-- Decides the normalised fields of the rows the conversion chain must read again because of a correction (slice 5
-- Task 3): the contexts corrections make positions (int_row_corrected, row_reason other than filed), and the filed
-- positions that carry a correction at step filed which passes int_correction_screen. One row per (run, accession,
-- context_id, field), with int_field_normalised's columns plus read_unit (the unit the field was read in).
--
-- It runs the same macros as the models of the chain (field_read, field_rule, rate_scale, rate_tag_cell,
-- amount_normalised, rate_normalised; their headers say what each decides), on these rows only:
--   run 'raw'            the filed facts, as int_field_normalised would give them if the row were a position. For a
--                        promoted row this is its value before corrections (value_normalised in int_field_corrected).
--                        For a filed position it must equal int_field_normalised
--                        (tests/int_field_reread_raw_equals_normalised.sql)
--   run 'filed_corrected'  the same, after each correction at step filed replaces the read of its field before the
--                        conversion rules run (production fills a printed, untagged value at parse time, before its
--                        conversion: pipeline/bdc_filings.py fill_untagged_values). The replaced read: value_filed the
--                        correction's number, unit 'iso4217:' plus the correction's currency (value_unit, else USD),
--                        status read, reason filed_by_correction, read_rule_id the correction_id, no fact. Amount
--                        fields only (the rate fields of this run are not computed: no correction at step filed sets a
--                        rate; seed correction_field). A withdrawal at step filed is not replaced here.
-- Rate fields are given for run raw only. A filed position's rate fields are not used from here (int_field_corrected
-- takes them from int_field_normalised).
-- (Join filters sit in subqueries, not in a join's ON clause: a filter there makes DuckDB plan a nested-loop join.)
with filed_screen as (
    select accession, context_id
    from {{ ref('int_correction_screen') }}
    where screen_outcome is null and step = 'filed' and value_column = 'value' and not is_withdrawal
)

, rr_position as (
    select accession, context_id, cik, report_date
    from {{ ref('int_row_corrected') }}
    where row_reason <> 'filed'
    union
    select r.accession, r.context_id, r.cik, r.report_date
    from {{ ref('int_row_corrected') }} r
    semi join filed_screen sc on sc.accession = r.accession and sc.context_id = r.context_id
)

, rr_read as (
    {{ field_read('rr_position') }}
)

, rr_rule as (
    {{ field_rule('rr_read') }}
)

, rr_scale as (
    {{ rate_scale('rr_read') }}
)

, rr_cell as (
    {{ rate_tag_cell('rr_read') }}
)

, rr_amount as (
    {{ amount_normalised('rr_rule', 'rr_read') }}
)

, rr_rate as (
    {{ rate_normalised('rr_rule', 'rr_read', 'rr_scale', 'rr_cell') }}
)

, fc_filed as (
    -- the corrections at step filed, one per field row (int_correction_screen leaves at most one value per field row
    -- of a target: two different values are a conflict)
    select accession, context_id, field_row as field, any_value(value_number) as value_number
        , any_value(upper(trim(value_unit))) as value_unit, min(correction_id) as correction_id
    from {{ ref('int_correction_screen') }}
    where screen_outcome is null and step = 'filed' and value_column = 'value' and not is_withdrawal
    group by 1, 2, 3
)

, fc_read as (
    select
        r.* replace (
            case when f.field is not null then 'read' else r.status end as status
            , case when f.field is not null then 'filed_by_correction' else r.reason end as reason
            , case when f.field is not null then f.value_number else r.value_filed end as value_filed
            , case when f.field is not null then null else r.value_date end as value_date
            , case when f.field is not null then 'iso4217:' || coalesce(f.value_unit, 'USD') else r.unit end as unit
            , case when f.field is not null then null else r.decimals end as decimals
            , case when f.field is not null then null else r.fact_id end as fact_id
            , case when f.field is not null then 0 else r.fact_count end as fact_count
            , case when f.field is not null then null else r.printed_text end as printed_text
            , case when f.field is not null then false else r.is_nil end as is_nil
            , case when f.field is not null then f.correction_id else r.read_rule_id end as read_rule_id
        )
    from rr_read r
    left join fc_filed f on f.accession = r.accession and f.context_id = r.context_id and f.field = r.field
    -- only the rows that carry a correction at step filed
    where exists (select 1 from fc_filed x where x.accession = r.accession and x.context_id = r.context_id)
)

, fc_rule as (
    {{ field_rule('fc_read') }}
)

, fc_amount as (
    {{ amount_normalised('fc_rule', 'fc_read') }}
)

select 'raw' as run, a.*, rd.unit as read_unit
from rr_amount a
left join rr_read rd on rd.accession = a.accession and rd.context_id = a.context_id and rd.field = a.field
union all
select 'raw' as run, a.*, cast(null as varchar) as read_unit
from rr_rate a
union all
select 'filed_corrected' as run, a.*, rd.unit as read_unit
from fc_amount a
left join fc_read rd on rd.accession = a.accession and rd.context_id = a.context_id and rd.field = a.field
