-- Decides, for every position row both this layer and production have, whether each amount agrees with production and,
-- where it does not, why (spec intermediate_spine.md section 8, D1). One row per (accession, context_id, field).
--
-- Rows: cmp_row_set side = 'both', both bases, quarters in cmp_excluded_quarter left out. Joined on accession and
-- context id, as cmp_row_set is. Production is the comparison side only: nothing here changes a value of this layer.
-- Field pairs (this layer -> production column):
--   fair_value                -> fair_value
--   cost                      -> cost_reported (the filed cost; production's cost column equals it unless a donor
--                                proxy fills it, pipeline/financial_conventions.py cost_proxies. value_production_cost
--                                carries production's cost column as the second measure.)
--   principal_amount          -> principal_amount (in the filed currency on both sides)
--   principal_amount_currency -> principal_amount_currency (text; compared in currency_new / currency_production)
--   principal_amount_usd      -> principal_amount_usd
--   shares                    -> shares_held
--   pct_of_net_assets         -> pct_of_net_assets (a percent on both sides)
-- Equal: |difference| < var('cmp_amount_tolerance')['dollar'] (1) for the four dollar fields (D1, to the dollar);
-- <= var('cmp_amount_tolerance')['measured'] for shares and share of net assets (both read from one tag; the only
-- difference measured on equal rows is float rounding of the times-100, below 2e-15); text equality for the currency.
-- Outcome: equal, differs, new_empty (production has a value, this layer none), production_empty, both_empty.
--
-- cause is set by rules on row features, first match wins, never by a list of ids. Closed list: old_wrong, new_wrong,
-- convention, needs_correction, needs_store_not_loaded, production_stale, owner_review, not_yet_explained. Null on
-- equal and both_empty rows. The evidence behind each rule is in docs/baseline_amounts_2026-11-22.md.
--   Since slice 5 Task 5 this layer's side is the corrected value (int_field_corrected; value_normalised beside it, the
--   value before corrections, and correction_id, the correction that set it), production's row is joined on
--   cmp_row_set's production_context_id, and a correction both sides apply is equal. A covering correction is a loaded
--   value correction of a field that sets this one (correction_cover) with a target row on this position in
--   int_correction_application; it is used when its outcome is applied or no_op.
--   convention|untagged_principal_currency_blank_in_production  the currency: a principal set at step filed by a
--        correction with no unit (a wrapper untagged value), production's currency empty. Production fills the value
--        at parse time with no unit, so its currency stays blank; this layer's conversion reads a value with no unit as
--        dollars and writes USD. Unverified: both pipelines assume USD for a principal with no unit (Task 5 review).
--   old_wrong|filled_principal_currency_blank_in_production  the currency, production's currency empty, and its
--        src_filled_fields names principal_amount: production's dedupe copied the principal value from a sibling context
--        of the same identifier (pipeline/bdc_filings.py _deduplicate_bdc_holdings) without its unit, so its currency
--        stays blank (and it converts the value as dollars); this layer reads the principal on its own context with its
--        unit. Seen on the two adopted pairs whose production row keeps the giver's context id. Old wrong since the
--        Task 5 review (controller ruling 2026-11-25; was convention): the copy drops the unit.
--   needs_correction|correction_<outcome>_<reason>  covering corrections are loaded on the row and none is used here
--        (rejected, failed or deferred, the outcome and reason of the first). Ceiling 0 on every field.
--   not_yet_explained|correction_applied_value_differs  a correction applied on this field and production holds
--        another value, with no rule below to say why. Checked last, before none.
--   needs_store_not_loaded|production_corrected_no_loaded_store  production's corrected_fields names the field, no
--        loaded correction covers it.
--   new_wrong|filer_concept_not_read  this layer read no fact; the context carries a numeric fact whose local name
--        contains a concept_map local name of the field, in a namespace no concept_map row of the field matches
--        (production matches concept names as substrings in any namespace, pipeline/bdc_filings.py CONCEPT_MAP).
--   new_wrong|bracket_split_across_cells  fair value or cost of a filing with a bracketed_unsigned rule, the two sides
--        opposite in sign, and the fact printed as "(123" with ")" in the next cell: a layout int_field_rule's bracket
--        test does not read as brackets.
--   owner_review|par_tagged_loan_test_stand_in  this layer moved a share count to principal (par_tagged_as_units,
--        whose "is a loan" test is a debt term fact) where production kept it as shares.
--   owner_review|units_tagged_equity_test_stand_in  units_tagged_as_par: this layer took shares from the principal
--        where production did not, or production took them where this layer did not (its "is equity" test is "no
--        debt term fact", production's is a text class).
--   owner_review|unverified_unit_count_read_as_principal  production holds no principal or dollar principal but
--        kept the principal's currency, and its index class is one pipeline/unified_holdings.py empties principal on
--        (common or preferred equity or a fund; lines 1346-1360). This layer reads the principal tag as filed and
--        stores it as a dollar principal; in the samples read the tag holds a unit count, not a par. Not verified, so
--        not a convention (controller ruling, final fix wave F7).
--   old_wrong|principal_emptied_then_reclassified  the same signature on a row whose production class is not one of
--        those, where a loaded correction sets the row's index class or asset category: production emptied the
--        principal under its first class (the class step comes before row corrections in unified_holdings.py) and the
--        correction re-classed the row as debt without restoring the filed par (fix round 1, item 1).
--   old_wrong|principal_emptied_before_section_reclass  the same signature, a class that is not equity or fund, and
--        no loaded class correction (fix round 1, item 1; was not_yet_explained|principal_empty_class_not_equity until
--        the Task 5 review, then owner_review until the owner's decision of 2026-11-25, item b). Traced in slice 5
--        Task 5 (baseline_corrections section 4.4): the 14 rows (one fund's "Units" lines) are emptied under their
--        first class (COMMON_EQUITY, from the label word "Units") and then re-classed STRUCTURED_CREDIT by the printed
--        section (pipeline/printed_sections.py apply_structured_sections, after the class step): production empties
--        the principal under a class it then rejects. Checked on all 14 (baseline section 6): the tagged principal
--        equals the tagged cost to the dollar, is in USD and the row has a maturity date. The printed column header is
--        "Par Amount/Units", which does not say which of the two a row holds.
--   convention|count_principal_currency_blank_in_production  a principal taken from a share count: production leaves
--        its currency blank (and converts it as dollars), this layer writes USD.
--   old_wrong|pct_size_bound_keeps_fraction  share of net assets: production stores the filed fraction unscaled (its
--        size bound keeps values above 0.50), this layer stores it times 100.
--   not_yet_explained|none  anything else.
-- Agreement between the two sides shows they agree. It does not show either is right: a value both pipelines read
-- wrongly in the same way is equal here.
with both_rows as (
    select c.basis, c.accession, c.context_id, coalesce(c.production_context_id, c.context_id) as production_context_id,
        c.cik, c.report_date
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
        , fair_value
        , cost_reported
        , cost
        , principal_amount
        , principal_amount_currency
        , principal_amount_usd
        , shares_held
        , pct_of_net_assets
        , corrected_fields
        , coalesce(src_filled_fields, '') as src_filled_fields
        , bdc_investment_identifier
        , index_classification
    from {{ ref('stg_holdings') }}
    where src_context_id is not null
)

, field_list as (
    -- the field, production's name for it in corrected_fields and stg_correction, and its tolerance class
    select * from (values
        ('fair_value', 'fair_value', 'dollar'),
        ('cost', 'cost', 'dollar'),
        ('principal_amount', 'principal_amount', 'dollar'),
        ('principal_amount_currency', 'principal_amount_currency', 'text'),
        ('principal_amount_usd', 'principal_amount_usd', 'dollar'),
        ('shares', 'shares_held', 'measured'),
        ('pct_of_net_assets', 'pct_of_net_assets', 'measured')
    ) v(field, production_field, tolerance_class)
)

, correction_cover as (
    -- which correction fields set which compared field (a principal or its currency also sets the dollar principal)
    select * from (values
        ('fair_value', 'fair_value'),
        ('cost', 'cost'), ('cost', 'cost_currency'),
        ('principal_amount', 'principal_amount'),
        ('principal_amount_currency', 'principal_amount_currency'), ('principal_amount_currency', 'principal_amount'),
        ('principal_amount_usd', 'principal_amount_usd'), ('principal_amount_usd', 'principal_amount'),
        ('principal_amount_usd', 'principal_amount_currency'), ('principal_amount_usd', 'principal_fx_rate_to_usd'),
        ('principal_amount_usd', 'principal_fx_status'),
        ('shares', 'shares_held'),
        ('pct_of_net_assets', 'pct_of_net_assets')
    ) v(field, correction_field)
)

, production_equity_class as (
    -- the index classes pipeline/unified_holdings.py empties principal on (lines 1346-1360)
    select * from (values
        ('COMMON_EQUITY'), ('PREFERRED_EQUITY'), ('PRIVATE_EQUITY_FUND'), ('PRIVATE_CREDIT_FUND'), ('REAL_ESTATE_FUND'),
        ('HEDGE_FUND')
    ) v(index_classification)
)

, norm as (
    select accession, context_id, field, value, value_normalised, currency, currency_normalised, value_filed, action,
        rule_id, status, reason, correction_id
    from {{ ref('int_field_corrected') }}
)

, principal_norm as (
    select accession, context_id, value, currency, currency_normalised, action, correction_id
    from norm where field = 'principal_amount'
)

, application as (
    -- correction targets on positions, with whether the correction was used here (applied or no_op)
    select a.correction_id, a.accession, a.context_id, a.field as correction_field, a.outcome, a.reason,
        a.applied_at_step, a.outcome in ('applied', 'no_op') as is_used
    from {{ ref('int_correction_application') }} a
    where a.kind = 'value' and a.context_id is not null
)

, untagged_principal as (
    -- a principal set at step filed by a correction with no unit
    select distinct a.accession, a.context_id
    from application a
    join {{ ref('stg_correction') }} c on c.correction_id = a.correction_id
    where a.correction_field = 'principal_amount' and a.outcome = 'applied' and a.applied_at_step = 'filed'
      and nullif(trim(c.value_unit), '') is null
)

, shares_norm as (
    select accession, context_id, value, value_filed, action, reason from norm where field = 'shares'
)

, pairs as (
    select
        b.basis
        , b.accession
        , b.context_id
        , fl.field
        , fl.production_field
        , fl.tolerance_class
        , b.cik
        , b.report_date
        , case when fl.field = 'principal_amount_currency' then null else n.value end as value_new
        , case when fl.field = 'principal_amount_currency' then null else n.value_normalised end as value_normalised
        , case when fl.field = 'principal_amount_currency' then pn.currency_normalised end as currency_normalised
        , case when fl.field = 'principal_amount_currency' then pn.correction_id else n.correction_id end
            as correction_id
        , case fl.field
            when 'fair_value' then p.fair_value
            when 'cost' then p.cost_reported
            when 'principal_amount' then p.principal_amount
            when 'principal_amount_usd' then p.principal_amount_usd
            when 'shares' then p.shares_held
            when 'pct_of_net_assets' then p.pct_of_net_assets
          end as value_production
        , case when fl.field = 'cost' then p.cost end as value_production_cost
        , case when fl.field = 'principal_amount_currency' then pn.currency end as currency_new
        , case when fl.field = 'principal_amount_currency' then p.principal_amount_currency end as currency_production
        , coalesce(n.action, case when fl.field = 'principal_amount_currency' then pn.action end) as new_action
        , n.rule_id as new_rule_id
        , n.status as new_status
        , n.reason as new_reason
        , n.value_filed as new_value_filed
        , pn.value as new_principal
        , pn.action as new_principal_action
        , sn.value_filed as new_shares_filed
        , sn.action as new_shares_action
        , sn.reason as new_shares_reason
        , p.principal_amount as production_principal
        , p.principal_amount_currency as production_currency
        , p.shares_held as production_shares
        , p.corrected_fields
        , p.src_filled_fields
        , p.bdc_investment_identifier
        , p.index_classification as production_class
        , pc.index_classification is not null as production_class_empties_principal
    from both_rows b
    cross join field_list fl
    join prod p on p.accession = b.accession and p.context_id = b.production_context_id
    left join norm n
        on n.accession = b.accession and n.context_id = b.context_id
        and n.field = case when fl.field = 'principal_amount_currency' then 'principal_amount' else fl.field end
    left join principal_norm pn on pn.accession = b.accession and pn.context_id = b.context_id
    left join shares_norm sn on sn.accession = b.accession and sn.context_id = b.context_id
    left join production_equity_class pc on pc.index_classification = p.index_classification
)

, outcomes as (
    select
        *
        , case
            when tolerance_class = 'text' then
                case
                    when currency_new is null and currency_production is null then 'both_empty'
                    when currency_new is null then 'new_empty'
                    when currency_production is null then 'production_empty'
                    when currency_new = currency_production then 'equal'
                    else 'differs'
                end
            when value_new is null and value_production is null then 'both_empty'
            when value_new is null then 'new_empty'
            when value_production is null then 'production_empty'
            when tolerance_class = 'dollar'
                 and abs(value_new - value_production) < {{ var('cmp_amount_tolerance')['dollar'] }} then 'equal'
            when tolerance_class = 'measured'
                 and abs(value_new - value_production) <= {{ var('cmp_amount_tolerance')['measured'] }} then 'equal'
            else 'differs'
          end as outcome
    from pairs
)

, open_pairs as (
    select * from outcomes where outcome in ('differs', 'new_empty', 'production_empty')
)

, loaded_correction as (
    -- covering corrections with a target on the row: whether any is used here, and the outcome and reason of the first
    -- unused one (by outcome, then reason)
    select
        o.accession
        , o.context_id
        , o.field
        , true as has_loaded_correction
        , bool_or(a.is_used) as any_used
        , min(case when not a.is_used then a.outcome || '_' || coalesce(a.reason, '') end) as unused_outcome
    from open_pairs o
    join correction_cover cc on cc.field = o.field
    join application a
        on a.accession = o.accession and a.context_id = o.context_id and a.correction_field = cc.correction_field
    group by 1, 2, 3
)

, class_correction as (
    -- a loaded correction that sets the row's index class or asset category (by context id, or accession and identifier)
    select distinct o.accession, o.context_id
    from open_pairs o
    join {{ ref('stg_correction') }} c
        on c.kind = 'value' and c.field in ('index_classification', 'asset_category') and c.accession = o.accession
        and (c.context_id = o.context_id
             or (c.context_id is null and c.identifier = o.bdc_investment_identifier))
)

, filer_concept as (
    -- a numeric fact on the context whose local name contains a concept_map local name of the field, in a namespace
    -- that no concept_map row of the field matches
    select distinct o.accession, o.context_id, o.field
    from open_pairs o
    join {{ ref('stg_filed_fact') }} f on f.accession = o.accession and f.context_id = o.context_id
    join {{ ref('concept_map') }} m on m.field = o.field and contains(f.concept_local, m.concept_local)
    where o.outcome = 'new_empty'
      and f.value_numeric is not null
      and not exists (
          select 1 from {{ ref('concept_map') }} m2
          where m2.field = o.field and m2.concept_local = f.concept_local and f.concept_namespace glob m2.namespace_pattern
      )
)

, sign_rule_filing as (
    select distinct cik, sel_accession as accession
    from {{ ref('stg_reading_rule') }}
    where action = 'bracketed_unsigned' and sel_accession is not null
)

, units_rule_filing as (
    select distinct cik, sel_accession as accession
    from {{ ref('stg_reading_rule') }}
    where action = 'units_tagged_as_par' and sel_accession is not null
)

, split_bracket as (
    -- the read fact printed as "(123" with ")" opening the next cell
    select distinct o.accession, o.context_id, o.field
    from open_pairs o
    semi join sign_rule_filing s on s.cik = o.cik and s.accession = o.accession
    join {{ ref('int_field_read') }} r on r.accession = o.accession and r.context_id = o.context_id and r.field = o.field
    join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = r.accession and pl.fact_id = r.fact_id
    join {{ ref('stg_filed_document_row') }} dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
    where o.field in ('fair_value', 'cost')
      and regexp_full_match(coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1], ''), '\s*\$?\s*\([^)]*')
      and ltrim(coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 2], '')) like ')%'
)

, featured as (
    select
        o.*
        , coalesce(lc.has_loaded_correction, false) as has_loaded_correction
        , coalesce(lc.any_used, false) as loaded_correction_used
        , lc.unused_outcome
        , up.accession is not null as has_untagged_principal
        , coalesce(regexp_matches(coalesce(o.corrected_fields, ''), '(^|;)' || o.production_field || '([;:=]|$)'), false)
            as production_corrected
        , fc.accession is not null as has_filer_concept
        , sb.accession is not null as has_split_bracket
        , ur.accession is not null as filing_has_units_rule
        , cc.accession is not null as has_class_correction
    from open_pairs o
    left join loaded_correction lc on lc.accession = o.accession and lc.context_id = o.context_id and lc.field = o.field
    left join filer_concept fc on fc.accession = o.accession and fc.context_id = o.context_id and fc.field = o.field
    left join split_bracket sb on sb.accession = o.accession and sb.context_id = o.context_id and sb.field = o.field
    left join units_rule_filing ur on ur.cik = o.cik and ur.accession = o.accession
    left join class_correction cc on cc.accession = o.accession and cc.context_id = o.context_id
    left join untagged_principal up on up.accession = o.accession and up.context_id = o.context_id
)

, caused as (
    select
        accession
        , context_id
        , field
        , case
            when field = 'principal_amount_currency' and outcome = 'production_empty' and has_untagged_principal
                then 'convention|untagged_principal_currency_blank_in_production'
            when field = 'principal_amount_currency' and outcome = 'production_empty'
                 and regexp_matches(src_filled_fields, '(^|[,;])principal_amount([,;]|$)')
                then 'old_wrong|filled_principal_currency_blank_in_production'
            when has_loaded_correction and not loaded_correction_used
                then 'needs_correction|correction_' || unused_outcome
            when production_corrected and not has_loaded_correction
                then 'needs_store_not_loaded|production_corrected_no_loaded_store'
            when has_filer_concept then 'new_wrong|filer_concept_not_read'
            when has_split_bracket and value_new is not null and value_production is not null
                 and abs(value_new + value_production) < {{ var('cmp_amount_tolerance')['dollar'] }}
                then 'new_wrong|bracket_split_across_cells'
            -- par_tagged_as_units: this layer moved the count to principal, production kept it as shares
            when field in ('principal_amount', 'principal_amount_usd', 'principal_amount_currency')
                 and new_principal_action = 'par_tagged_as_units' and production_principal is null
                 and production_shares is not null
                then 'owner_review|par_tagged_loan_test_stand_in'
            when field = 'shares' and new_shares_action = 'par_tagged_as_units' and value_new is null
                 and value_production = new_shares_filed
                then 'owner_review|par_tagged_loan_test_stand_in'
            -- units_tagged_as_par: one side took shares from the principal tag, the other did not
            when field = 'shares' and new_shares_action = 'units_tagged_as_par' and value_production is null
                then 'owner_review|units_tagged_equity_test_stand_in'
            when field = 'shares' and value_new is null and filing_has_units_rule and value_production = new_principal
                then 'owner_review|units_tagged_equity_test_stand_in'
            when field in ('principal_amount', 'principal_amount_usd') and outcome = 'production_empty'
                 and production_principal is null and production_currency is not null
                 and new_principal_action = 'as_filed' and production_class_empties_principal
                then 'owner_review|unverified_unit_count_read_as_principal'
            when field in ('principal_amount', 'principal_amount_usd') and outcome = 'production_empty'
                 and production_principal is null and production_currency is not null
                 and new_principal_action = 'as_filed' and has_class_correction
                then 'old_wrong|principal_emptied_then_reclassified'
            when field in ('principal_amount', 'principal_amount_usd') and outcome = 'production_empty'
                 and production_principal is null and production_currency is not null
                 and new_principal_action = 'as_filed'
                then 'old_wrong|principal_emptied_before_section_reclass'
            when field = 'principal_amount_currency' and outcome = 'production_empty'
                 and new_principal_action = 'par_tagged_as_units' and currency_new = 'USD'
                then 'convention|count_principal_currency_blank_in_production'
            when field = 'pct_of_net_assets' and new_action = 'fraction_to_percent' and new_value_filed > 0.5
                 and abs(value_production - new_value_filed) <= {{ var('cmp_amount_tolerance')['measured'] }}
                then 'old_wrong|pct_size_bound_keeps_fraction'
            when correction_id is not null then 'not_yet_explained|correction_applied_value_differs'
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
    , o.value_normalised
    , o.value_production
    , o.value_new - o.value_production as difference
    , o.currency_new
    , o.currency_normalised
    , o.currency_production
    , o.correction_id
    , o.value_production_cost
    , o.outcome
    , split_part(c.cause_key, '|', 1) as cause
    , nullif(split_part(c.cause_key, '|', 2), '') as cause_detail
    , o.new_action
    , o.new_rule_id
    , o.new_status
    , o.new_reason
from outcomes o
left join caused c on c.accession = o.accession and c.context_id = o.context_id and c.field = o.field
