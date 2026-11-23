-- Decides, for every position row both this layer and production have, whether each rate field agrees with
-- production and, where it does not, why (spec intermediate_spine.md section 8, D1; slice 4 Task 4). One row per
-- (accession, context_id, field).
--
-- Rows: cmp_row_set side = 'both', both bases, quarters in cmp_excluded_quarter left out. Joined on accession and
-- context id, as cmp_amount is. Production is the comparison side only: nothing here changes a value of this layer.
-- Field pairs (this layer, int_field_normalised -> production, stg_holdings):
--   interest_rate      -> interest_rate        (the all-in rate, percent)
--   interest_rate_cash -> interest_rate_cash   (the cash leg, percent)
--   pik_rate           -> pik_rate             (percent)
--   spread             -> basis_spread         (percent)
--   maturity_date      -> maturity_date        (date; this layer's value_date)
--   rate_kind          -> interest_rate_kind   (text; this layer's rate_kind on the interest_rate row)
-- Second measure: production's interest_rate_reported (its filed rate after its size scaling, before the reading) is
-- kept beside the interest_rate pair as value_production_reported; it is not compared. basis_spread_kind ('unresolved'
-- on every row of the five funds) and maturity_precision are not compared (docs/baseline_rates_2026-11-23.md).
-- Equal: |difference| <= var('cmp_rate_tolerance') percentage points for the four rates (both sides multiply one
-- tagged fraction by 100: the largest difference on agreeing rows is float rounding, below 4e-15); same date; same text.
-- Outcome: equal, differs, new_empty (production has a value, this layer none), production_empty, both_empty.
--
-- cause is set by rules on row features, first match wins, never by a list of ids. Closed list as cmp_amount. Null on
-- equal and both_empty rows. The evidence behind each rule is in docs/baseline_rates_2026-11-23.md.
--   needs_correction|correction_loaded_applied  a loaded value correction (stg_correction, keyed by context id, or by
--        accession and production's identifier) names a field that sets this one (correction_cover), and production's
--        corrected_fields names such a field.
--   not_yet_explained|correction_loaded_not_named  the same correction is loaded, production does not name it.
--   needs_store_not_loaded|production_corrected_no_loaded_store  production names a covering field, none is loaded.
--   needs_store_not_loaded|rate_only_context_not_adopted  production's src_filled_fields names a covering field:
--        production moved the rate facts of a neighbouring rate-only context onto this row (wrapper procedure
--        rate_only_contexts adopt_adjacent, pipeline/source_encodings.py adopt_rate_only_contexts; not built here).
--   needs_store_not_loaded|whole_coupon_pik_not_read  production's src_transforms has pik_rate:whole_coupon_printed:
--        it stored the printed coupon as the PIK rate (wrapper procedure pik_margin_reading whole_coupon,
--        pipeline/whole_coupon_pik.py; printed text, not built here). Rate, cash leg, PIK rate and kind only.
--   new_wrong|coupon_read_on_printed_floating_margin  this layer applied pik_only_is_coupon (all-in = the PIK rate)
--        on a row whose printed text names a floating margin: production read a spread from the identifier text
--        ('S+450 PIK') and so did not apply the coupon reading. The PIK tag is a margin, not the coupon. A defect of
--        the slice 4 Task 3 coupon ruling (no text test); not patched here (task-4 report).
--   needs_store_not_loaded|identifier_text_not_read  production's source for the field is identifier_text: it read
--        the value from the investment identifier's text (pipeline/staging_bdc.py, the _text_* fallbacks). For the
--        rate, cash leg and kind also when production's PIK rate came from that text (the legs follow from it).
--   needs_store_not_loaded|printed_maturity_not_read  maturity: production's source is ixbrl_field_status or
--        printed_page, a date read from the printed schedule row (pipeline/bdc_xbrl_html_bridge.py
--        apply_ixbrl_field_status_overlay).
--   needs_store_not_loaded|printed_reference_rate_column_not_read  src_transforms has interest_rate:from_spread_tag or
--        basis_spread:fixed_coupon: production read 'no reference rate' in the printed reference-rate column and
--        moved the spread tag to the rate or withdrew it (apply_ixbrl_field_status_overlay).
--   needs_store_not_loaded|pik_only_reading_needs_printed_text  this layer's reason is rule_conflict: the fund declares
--        both PIK-only readings; production separates them by printed reference rate and coupon type.
--   needs_store_not_loaded|printed_total_margin_not_read  this layer's reason is text_not_read: the printed total
--        margin decides printed_margin_cash_plus_pik.
--   needs_store_not_loaded|loan_class_not_read  this layer applied pik_only_is_coupon on a row production does not
--        class as a loan (asset_category, read from text); production applies the coupon reading to loans only.
--   owner_review|scale_decided_by_size_in_production  this layer's reason is scale_not_decided (a ratio-unit value
--        above 1): production keeps or rescales it by its size (pipeline/staging_bdc.py _prepare_bdc). Not a
--        convention: no filer rule says which scale the tag is in (controller ruling, slice 4 Task 3).
--   owner_review|two_values_filed_production_keeps_first  this layer's reason is values_differ (one concept filed
--        twice with different numbers, slice 4 Task 2): production keeps the first fact in the instance
--        (pipeline/bdc_filings.py, "keep first non-None"), this layer withholds the value (D5).
--   not_yet_explained|none  anything else.
-- Agreement between the two sides shows they agree. It does not show either is right: a rate both pipelines read
-- wrongly in the same way is equal here, and a rate missing on both sides is both_empty.
with both_rows as (
    select c.basis, c.accession, c.context_id, c.cik, c.report_date
    from {{ ref('cmp_row_set') }} c
    where c.side = 'both'
      and not exists (
          select 1 from {{ ref('cmp_excluded_quarter') }} x where x.cik = c.cik and x.report_date = c.report_date
      )
)

, prod as (
    select
        accession_number as accession
        , src_context_id as context_id
        , interest_rate
        , interest_rate_cash
        , interest_rate_reported
        , interest_rate_kind
        , pik_rate
        , basis_spread
        , maturity_date
        , interest_rate_source
        , basis_spread_source
        , pik_rate_source
        , maturity_date_source
        , coalesce(src_transforms, '') as src_transforms
        , coalesce(src_filled_fields, '') as src_filled_fields
        , corrected_fields
        , bdc_investment_identifier
        , asset_category
    from {{ ref('stg_holdings') }}
    where src_context_id is not null
)

, field_list as (
    -- the field, this layer's row in int_field_normalised, production's column, its value class and production's
    -- source column for it
    select * from (values
        ('interest_rate', 'interest_rate', 'interest_rate', 'number', 'interest_rate_source'),
        ('interest_rate_cash', 'interest_rate_cash', 'interest_rate_cash', 'number', 'interest_rate_source'),
        ('pik_rate', 'pik_rate', 'pik_rate', 'number', 'pik_rate_source'),
        ('spread', 'spread', 'basis_spread', 'number', 'basis_spread_source'),
        ('maturity_date', 'maturity_date', 'maturity_date', 'date', 'maturity_date_source'),
        ('rate_kind', 'interest_rate', 'interest_rate_kind', 'text', 'interest_rate_source')
    ) v(field, normalised_field, production_field, value_class, source_column)
)

, correction_cover as (
    -- which production fields, when a correction sets them, set the compared field (the all-in rate, its cash leg
    -- and its kind follow from the rate, the PIK rate and the kind; production's names)
    select * from (values
        ('interest_rate', 'interest_rate'), ('interest_rate', 'interest_rate_kind'), ('interest_rate', 'pik_rate'),
        ('interest_rate_cash', 'interest_rate'), ('interest_rate_cash', 'interest_rate_kind'),
        ('interest_rate_cash', 'pik_rate'), ('interest_rate_cash', 'interest_rate_cash'),
        ('rate_kind', 'interest_rate'), ('rate_kind', 'interest_rate_kind'), ('rate_kind', 'pik_rate'),
        ('pik_rate', 'pik_rate'),
        ('spread', 'basis_spread'),
        ('maturity_date', 'maturity_date')
    ) v(field, correction_field)
)

, norm as (
    select accession, context_id, field, value, value_date, rate_kind, action, rule_id, status, reason
    from {{ ref('int_field_normalised') }}
    where field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
)

, pairs as (
    select
        b.basis
        , b.accession
        , b.context_id
        , fl.field
        , fl.production_field
        , fl.value_class
        , b.cik
        , b.report_date
        , case when fl.value_class = 'number' then n.value end as value_new
        , case fl.field
            when 'interest_rate' then p.interest_rate
            when 'interest_rate_cash' then p.interest_rate_cash
            when 'pik_rate' then p.pik_rate
            when 'spread' then p.basis_spread
          end as value_production
        , case when fl.field = 'interest_rate' then p.interest_rate_reported end as value_production_reported
        , case when fl.value_class = 'date' then n.value_date end as date_new
        , case when fl.value_class = 'date' then p.maturity_date end as date_production
        , case when fl.value_class = 'text' then n.rate_kind end as text_new
        , case when fl.value_class = 'text' then p.interest_rate_kind end as text_production
        , n.action as new_action
        , n.rule_id as new_rule_id
        , n.status as new_status
        , n.reason as new_reason
        , case fl.source_column
            when 'interest_rate_source' then p.interest_rate_source
            when 'pik_rate_source' then p.pik_rate_source
            when 'basis_spread_source' then p.basis_spread_source
            when 'maturity_date_source' then p.maturity_date_source
          end as production_source
        , p.basis_spread_source as production_spread_source
        , p.pik_rate_source as production_pik_source
        , p.interest_rate as production_interest_rate
        , p.src_transforms
        , p.src_filled_fields
        , p.corrected_fields
        , p.bdc_investment_identifier
        , p.asset_category as production_asset_category
    from both_rows b
    cross join field_list fl
    join prod p on p.accession = b.accession and p.context_id = b.context_id
    left join norm n
        on n.accession = b.accession and n.context_id = b.context_id and n.field = fl.normalised_field
)

, outcomes as (
    select
        *
        , case
            when value_class = 'text' then
                case
                    when text_new is null and text_production is null then 'both_empty'
                    when text_new is null then 'new_empty'
                    when text_production is null then 'production_empty'
                    when text_new = text_production then 'equal'
                    else 'differs'
                end
            when value_class = 'date' then
                case
                    when date_new is null and date_production is null then 'both_empty'
                    when date_new is null then 'new_empty'
                    when date_production is null then 'production_empty'
                    when date_new = date_production then 'equal'
                    else 'differs'
                end
            when value_new is null and value_production is null then 'both_empty'
            when value_new is null then 'new_empty'
            when value_production is null then 'production_empty'
            when abs(value_new - value_production) <= {{ var('cmp_rate_tolerance') }} then 'equal'
            else 'differs'
          end as outcome
    from pairs
)

, open_pairs as (
    select * from outcomes where outcome in ('differs', 'new_empty', 'production_empty')
)

, loaded_correction as (
    -- a loaded value correction that sets a covering field of the row
    select distinct o.accession, o.context_id, o.field
    from open_pairs o
    join correction_cover cc on cc.field = o.field
    join {{ ref('stg_correction') }} c
        on c.kind = 'value' and c.field = cc.correction_field and c.accession = o.accession
        and (c.context_id = o.context_id
             or (c.context_id is null and c.identifier = o.bdc_investment_identifier))
)

, production_named as (
    -- production's corrected_fields, or its src_filled_fields, names a covering field
    select
        o.accession
        , o.context_id
        , o.field
        , bool_or(regexp_matches(coalesce(o.corrected_fields, ''), '(^|;)' || cc.correction_field || '([;:=]|$)'))
            as production_corrected
        , bool_or(regexp_matches(o.src_filled_fields, '(^|[,;])' || cc.correction_field || '([,;]|$)'))
            as production_filled
    from open_pairs o
    join correction_cover cc on cc.field = o.field
    group by 1, 2, 3
)

, featured as (
    select
        o.*
        , lc.accession is not null as has_loaded_correction
        , coalesce(pn.production_corrected, false) as production_corrected
        , coalesce(pn.production_filled, false) as production_filled
        , regexp_matches(o.src_transforms, '(^|;)pik_rate:whole_coupon_printed(;|$)') as whole_coupon
        , regexp_matches(o.src_transforms, '(^|;)(interest_rate:from_spread_tag|basis_spread:fixed_coupon)(;|$)')
            as reference_column_move
    from open_pairs o
    left join loaded_correction lc on lc.accession = o.accession and lc.context_id = o.context_id and lc.field = o.field
    left join production_named pn on pn.accession = o.accession and pn.context_id = o.context_id and pn.field = o.field
)

, caused as (
    select
        accession
        , context_id
        , field
        , case
            when has_loaded_correction and production_corrected then 'needs_correction|correction_loaded_applied'
            when has_loaded_correction then 'not_yet_explained|correction_loaded_not_named'
            when production_corrected then 'needs_store_not_loaded|production_corrected_no_loaded_store'
            when production_filled then 'needs_store_not_loaded|rate_only_context_not_adopted'
            when whole_coupon and field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'rate_kind')
                then 'needs_store_not_loaded|whole_coupon_pik_not_read'
            when new_action = 'pik_only_is_coupon' and field in ('interest_rate', 'interest_rate_cash', 'rate_kind')
                and production_spread_source = 'identifier_text' and production_interest_rate is null
                then 'new_wrong|coupon_read_on_printed_floating_margin'
            when production_source = 'identifier_text' then 'needs_store_not_loaded|identifier_text_not_read'
            when field in ('interest_rate', 'interest_rate_cash', 'rate_kind') and production_pik_source = 'identifier_text'
                then 'needs_store_not_loaded|identifier_text_not_read'
            when field = 'maturity_date' and production_source in ('ixbrl_field_status', 'printed_page')
                then 'needs_store_not_loaded|printed_maturity_not_read'
            when reference_column_move and field in ('interest_rate', 'interest_rate_cash', 'spread', 'rate_kind')
                then 'needs_store_not_loaded|printed_reference_rate_column_not_read'
            when new_reason = 'rule_conflict' then 'needs_store_not_loaded|pik_only_reading_needs_printed_text'
            when new_reason = 'text_not_read' then 'needs_store_not_loaded|printed_total_margin_not_read'
            when new_action = 'pik_only_is_coupon' and production_asset_category is distinct from 'LOAN'
                and field in ('interest_rate', 'interest_rate_cash', 'rate_kind')
                then 'needs_store_not_loaded|loan_class_not_read'
            when new_reason = 'scale_not_decided' then 'owner_review|scale_decided_by_size_in_production'
            when new_reason = 'values_differ' then 'owner_review|two_values_filed_production_keeps_first'
            else 'not_yet_explained|none'
          end as cause_key
    from featured
)

select
    o.basis
    , o.accession
    , o.context_id
    , o.field
    , o.cik
    , o.report_date
    , o.basis = 'published' as is_published
    , o.value_new
    , o.value_production
    , o.value_new - o.value_production as difference
    , o.value_production_reported
    , o.date_new
    , o.date_production
    , o.text_new
    , o.text_production
    , o.outcome
    , split_part(c.cause_key, '|', 1) as cause
    , nullif(split_part(c.cause_key, '|', 2), '') as cause_detail
    , o.new_action
    , o.new_rule_id
    , o.new_status
    , o.new_reason
    , o.production_source
from outcomes o
left join caused c on c.accession = o.accession and c.context_id = o.context_id and c.field = o.field
