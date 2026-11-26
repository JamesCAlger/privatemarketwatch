-- PROPOSAL, NOT A READING OF RECORD (text slice R phase 2, 2026-11-26). The proposed rate read of
-- int_text_rate_proposed gathered per position, beside the filer's tags, as the input of the checks
-- (int_text_check_leg_arithmetic, int_text_check_base_level). Nothing downstream may publish from it.
--
-- One row per position with at least one row in int_text_rate_proposed: (accession, context_id).
-- Printed values (p_<field>), from read rows only, over every column unit of the position's row:
--   spread, floor, all_in_rate, cash_rate, pik_rate, pik_spread, fixed_rate.
--   p_<field>: the value when every read value of the field on the position agrees within var text_number_tolerance
--   (the smallest, which differs from the others by at most that), else null; n_<field>: read values seen;
--   conflict_<field>: two read values differ by more than the tolerance (two columns print the field two ways, or one
--   cell prints it twice: "S+225 Cash plus 2.75% PIK, 0.50% PIK"). shapes_<field>: the shape_keys that printed it.
-- Code: the read code rows (field reference_rate_code). rate_name: the one normalised rate name of the read codes, null
-- when none or when two differ (conflict_rate_name); code, code_unit_key, code_shape_key: of the read code row (the
-- smallest unit_key when two columns print a code with one name). n_code_rows: code rows of any status.
-- Tags (int_field_normalised: the filed tags converted to percent, before any row correction; status normalised):
--   t_spread (spread), t_all_in (interest_rate, rate_kind all_in), t_cash (interest_rate_cash: for most filers the
--   spine derives it as all-in less PIK, so it is not a separate filed number), t_pik (pik_rate).
{% set fields = ['spread', 'floor', 'all_in_rate', 'cash_rate', 'pik_rate', 'pik_spread', 'fixed_rate'] %}
with read_row as (
    select * from {{ ref('int_text_rate_proposed') }}
)

, position as (
    select accession, context_id, min(cik) as cik, min(report_date) as report_date, bool_or(is_published) as is_published
        , list_sort(list_distinct(list(unit_key))) as unit_keys
        , count(*) filter (where field = 'reference_rate_code') as n_code_rows
    from read_row
    group by 1, 2
)

, printed as (
    select accession, context_id
    {%- for f in fields %}
        , count(*) filter (where field = '{{ f }}') as n_{{ f }}
        , min(value) filter (where field = '{{ f }}') as min_{{ f }}
        , max(value) filter (where field = '{{ f }}') as max_{{ f }}
        , list_sort(list_distinct(list(shape_key) filter (where field = '{{ f }}'))) as shapes_{{ f }}
    {%- endfor %}
    from read_row
    where status = 'read' and number_index > 0
    group by 1, 2
)

, coded as (
    select accession, context_id
        , count(distinct rate_name) as n_rate_names
        , min(rate_name) as rate_name
        , min_by(reference_rate_code, unit_key) as code
        , min(unit_key) as code_unit_key
        , min_by(shape_key, unit_key) as code_shape_key
    from read_row
    where status = 'read' and field = 'reference_rate_code'
    group by 1, 2
)

, tag as (
    select accession, context_id
        , any_value(value) filter (where field = 'spread') as t_spread
        , any_value(value) filter (where field = 'interest_rate' and rate_kind = 'all_in') as t_all_in
        , any_value(value) filter (where field = 'interest_rate_cash') as t_cash
        , any_value(value) filter (where field = 'pik_rate') as t_pik
    from {{ ref('int_field_normalised') }}
    where field in ('spread', 'interest_rate', 'interest_rate_cash', 'pik_rate') and status = 'normalised'
        and value is not null
    group by 1, 2
)

select
    p.accession
    , p.context_id
    , p.cik
    , p.report_date
    , p.is_published
    , p.unit_keys
    {%- for f in fields %}
    , case when pr.max_{{ f }} - pr.min_{{ f }} <= {{ var('text_number_tolerance') }} then pr.min_{{ f }} end as p_{{ f }}
    , coalesce(pr.n_{{ f }}, 0) as n_{{ f }}
    , coalesce(pr.max_{{ f }} - pr.min_{{ f }} > {{ var('text_number_tolerance') }}, false) as conflict_{{ f }}
    , coalesce(pr.shapes_{{ f }}, []::varchar[]) as shapes_{{ f }}
    {%- endfor %}
    , case when c.n_rate_names = 1 then c.rate_name end as rate_name
    , coalesce(c.n_rate_names > 1, false) as conflict_rate_name
    , c.code
    , c.code_unit_key
    , c.code_shape_key
    , p.n_code_rows
    , t.t_spread
    , t.t_all_in
    , t.t_cash
    , t.t_pik
from position p
left join printed pr on pr.accession = p.accession and pr.context_id = p.context_id
left join coded c on c.accession = p.accession and c.context_id = p.context_id
left join tag t on t.accession = p.accession and t.context_id = p.context_id
