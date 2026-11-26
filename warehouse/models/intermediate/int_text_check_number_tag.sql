-- Checks each number the PROPOSED rules read (int_text_rate_proposed) against the value the filer tagged for the same
-- field on the same position (text slice R phase 2, 2026-11-26). A measurement of the proposals; it publishes nothing.
-- One row per read number row whose field has a tag counterpart: (accession, context_id, unit_key, number_index).
--
-- Field -> tag (int_field_normalised, status normalised, percent, before any row correction):
--   spread -> spread    all_in_rate -> interest_rate (rate_kind all_in)    cash_rate -> interest_rate_cash
--   pik_rate -> pik_rate    pik_spread -> pik_rate (a PIK spread is the only PIK number such a cell prints, and the
--   filers tag it as the PIK rate; int_text_check_shape_legs, phase 1 section 14)
--   fixed_rate -> interest_rate (rate_kind all_in, as for all_in_rate: a fixed coupon is tagged as the interest rate)
-- floor has no tag at any of the five funds: not compared here (it is tested by int_text_check_leg_arithmetic (d)).
-- verdict: equal (abs(value - tag) <= var text_number_tolerance, 0.005 percentage points), differs, no_tag (no
-- normalised tag of that field on the position). interest_rate_cash: for most filers the spine derives it (all-in less
-- PIK), so a cash_rate equal to it agrees with the tagged all-in and PIK, not with a separate filed cash number.
-- tag_in_this_cell: the tag's own fact is placed in the cell being read (int_text_cell.fact_fields).
with read_number as (
    select accession, context_id, cik, report_date, is_published, unit_key, shape_key, shape, cell_text, number_index
        , role, field, value, fact_fields
        , case field
            when 'spread' then 'spread' when 'all_in_rate' then 'interest_rate'
            when 'cash_rate' then 'interest_rate_cash' when 'pik_rate' then 'pik_rate'
            when 'pik_spread' then 'pik_rate' when 'fixed_rate' then 'interest_rate'
          end as tag_field
    from {{ ref('int_text_rate_proposed') }}
    where status = 'read' and number_index > 0 and field <> 'floor'
)

, tag as (
    select accession, context_id, field as tag_field, any_value(value) as tag_value
    from {{ ref('int_field_normalised') }}
    where field in ('spread', 'interest_rate', 'interest_rate_cash', 'pik_rate') and status = 'normalised'
        and value is not null and (field <> 'interest_rate' or rate_kind = 'all_in')
    group by 1, 2, 3
)

select
    r.accession
    , r.context_id
    , r.cik
    , r.report_date
    , r.is_published
    , r.unit_key
    , r.shape_key
    , r.shape
    , r.cell_text
    , r.number_index
    , r.role
    , r.field
    , r.value
    , r.tag_field
    , t.tag_value
    , r.value - t.tag_value as difference
    , list_contains(r.fact_fields, case r.tag_field when 'interest_rate' then 'interest_rate_tag'
                                                    when 'interest_rate_cash' then 'interest_rate_cash_tag'
                                                    else r.tag_field end) as tag_in_this_cell
    , case
        when t.tag_value is null then 'no_tag'
        when abs(r.value - t.tag_value) <= {{ var('text_number_tolerance') }} then 'equal'
        else 'differs'
      end as verdict
from read_number r
left join tag t on t.accession = r.accession and t.context_id = r.context_id and t.tag_field = r.tag_field
