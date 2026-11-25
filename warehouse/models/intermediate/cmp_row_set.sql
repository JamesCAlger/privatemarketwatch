-- Decides which position rows sit on one side only when this layer is compared with production, and why
-- (spec intermediate_spine.md section 8, D1). Joined on accession and context id, never on a position id.
--
-- Two bases, one row per (basis, accession, context_id); no (accession, context_id) may sit in both bases
-- (tests/cmp_row_set_key_and_cause.sql), so (accession, context_id) is also unique:
--   published   : this layer's position rows after corrections (int_row_corrected, slice 5 Task 5) that are
--                 is_published, against production rows whose accounting_record_class is not 'underlying_schedule'
--                 (the published basis).
--   unpublished : the same rows that are not is_published (a JV's own schedule), against production rows whose
--                 accounting_record_class is 'underlying_schedule'.
-- int_row_corrected holds every filed position plus the contexts a correction makes a position (row_reason, carried
-- here). The row features the causes read (role, rule, reason, cash flags) stay those of int_source_row: a one-sided
-- row is explained by why this layer's reading left it out.
-- An adopted rate-only pair (int_rate_adjacent, slice 5 Task 4): production removes the giver row and in some filings
-- keeps the giver's context id on the merged row. Where production has a row at the giver and none at the taker, its
-- row is compared with this layer's taker; production_context_id keeps production's own context id (cmp_amount and
-- cmp_rate join production on it). A pair rule, not a list of contexts.
-- A production row with no context id cannot be joined; it is counted by tests/baseline_cmp_row_set_no_context.sql.
-- A fund and report date production has no rows for is left out of the comparison (owner, 2026-11-19); those
-- quarters and their row counts are in cmp_excluded_quarter. They re-enter when production is built with them.
--
-- cause is set by rules on row features, first match wins, never by a list of accession or context ids. Closed
-- list: old_wrong, new_wrong, convention, needs_store_not_loaded, needs_correction, owner_review,
-- not_yet_explained. old_wrong has no rule today: no measured group shows production reading a filing wrongly. The
-- evidence behind each rule is in docs/baseline_roles_2026-11-19.md. A row that reaches not_yet_explained gets the
-- detail relabel_loaded when a loaded relabel names its context (the store says the filer's label names the wrong
-- position): it shows the relabel is on file. It is not a cause; it says nothing about why the other side lacks the
-- row. Agreement between the two sides shows they
-- agree. It does not show either is right.
with prod_raw as (
    select
        cik
        , report_date
        , accession_number as accession
        , src_context_id as production_context_id
        , case when accounting_record_class = 'underlying_schedule' then 'unpublished' else 'published' end as basis
        , accounting_record_class
        , fair_value
        , corrected_fields
    from {{ ref('stg_holdings') }}
    where src_context_id is not null
)

, giver_to_taker as (
    -- an adopted pair whose taker is a position here, where production has a row at the giver and none at the taker
    select a.accession, a.giver_context_id, a.taker_context_id
    from {{ ref('int_rate_adjacent') }} a
    where a.taker_is_position
      and exists (
          select 1 from prod_raw p where p.accession = a.accession and p.production_context_id = a.giver_context_id
      )
      and not exists (
          select 1 from prod_raw p where p.accession = a.accession and p.production_context_id = a.taker_context_id
      )
)

, prod as (
    select
        p.*
        , coalesce(g.taker_context_id, p.production_context_id) as context_id
    from prod_raw p
    left join giver_to_taker g on g.accession = p.accession and g.giver_context_id = p.production_context_id
)

, new_side as (
    select
        r.accession
        , r.context_id
        , r.cik
        , r.report_date
        , case when r.is_published then 'published' else 'unpublished' end as basis
        , r.role
        , r.row_reason
        , r.row_correction_ids
    from {{ ref('int_row_corrected') }} r
    where r.role = 'position'
      and exists (
          select 1 from {{ ref('stg_holdings') }} h where h.cik = r.cik and h.report_date = r.report_date
      )
)

, joined as (
    select
        coalesce(n.basis, p.basis) as basis
        , coalesce(n.accession, p.accession) as accession
        , coalesce(n.context_id, p.context_id) as context_id
        , coalesce(n.cik, p.cik) as cik
        , coalesce(n.report_date, p.report_date) as report_date
        , case
            when n.accession is not null and p.accession is not null then 'both'
            when n.accession is not null then 'new_only'
            else 'production_only'
          end as side
        , p.production_context_id
        , n.row_reason
        , n.row_correction_ids
        , p.accounting_record_class
        , p.fair_value
        , p.corrected_fields
    from new_side n
    full join prod p
        on p.accession = n.accession and p.context_id = n.context_id and p.basis = n.basis
)

, one_sided as (
    select * from joined where side <> 'both'
)

, rate_facts as (
    -- a fact of a rate, spread or PIK rate concept, matched on local name and namespace pattern from the seed
    -- concept_map (us-gaap or the FASB supplement, as int_context_feature reads term facts). Field rate includes the
    -- cash-pay rate concept, which the slice 2 list left out; measured 2026-11-22, no row moved.
    select distinct f.accession, f.context_id
    from {{ ref('stg_filed_fact') }} f
    semi join one_sided o on o.accession = f.accession and o.context_id = f.context_id
    join {{ ref('concept_map') }} m
        on m.field in ('rate', 'spread', 'pik_rate') and m.concept_local = f.concept_local
        and f.concept_namespace glob m.namespace_pattern
)

, value_correction as (
    -- a loaded context-keyed correction that supplies the fair value, or a term field (not applied in this slice). The
    -- term fields are the ones the cross-check reads (principal, shares, rate, spread, PIK rate, maturity).
    select
        accession
        , context_id
        , bool_or(field = 'fair_value') as supplies_fair_value
        , bool_or(field in ('principal_amount', 'shares_held', 'interest_rate', 'basis_spread', 'pik_rate', 'maturity_date'))
            as supplies_term
    from {{ ref('stg_correction') }}
    where kind = 'value'
      and context_id is not null
    group by 1, 2
)

, relabel_correction as (
    -- a loaded context-keyed relabel: the store says the context carries another position's label (not applied here)
    select distinct accession, context_id
    from {{ ref('stg_correction') }}
    where kind = 'relabel' and context_id is not null
)

, filer_not_loaded as (
    select distinct cik, wrapper_key from {{ ref('stg_reading_not_loaded') }}
    -- slice 5 Task 4: the rate_only_contexts declaration is loaded as the rule adopt_adjacent_rate_context (loader
    -- version 7) instead of a not_loaded row; it still marks the fund as declaring it. Since Task 5 the pairs the rule
    -- adopts are joined (giver_to_taker above), so this cause is left for a pair the rule does not find.
    union
    select distinct cik, 'rate_only_contexts' from {{ ref('stg_reading_rule') }}
    where action = 'adopt_adjacent_rate_context'
)

, featured as (
    select
        o.*
        , r.role
        , r.reason
        , r.role_rule
        , coalesce(r.is_cash, false) as is_cash
        , r.cash_rule_id
        , r.cash_pattern_id
        , coalesce(r.held_for_two_scopes, false) as held_for_two_scopes
        , cf.identifier_label
        , cf.fair_value_fact_count
        , cf.has_term_fact
        , rf.accession is not null as has_rate_fact
        , coalesce(vc.supplies_fair_value, false) as has_fair_value_correction
        , coalesce(vc.supplies_term, false) as has_term_correction
        , rc.accession is not null as has_relabel_correction
        , coalesce(o.corrected_fields like '%_row:added%', false) as production_row_added
        , nl.cik is not null as filer_has_rate_only_declaration
    from one_sided o
    left join {{ ref('int_source_row') }} r on r.accession = o.accession and r.context_id = o.context_id
    left join {{ ref('int_context_feature') }} cf on cf.accession = o.accession and cf.context_id = o.context_id
    left join rate_facts rf on rf.accession = o.accession and rf.context_id = o.context_id
    left join value_correction vc on vc.accession = o.accession and vc.context_id = o.context_id
    left join relabel_correction rc on rc.accession = o.accession and rc.context_id = o.context_id
    left join filer_not_loaded nl on nl.cik = o.cik and nl.wrapper_key = 'rate_only_contexts'
)

, paired as (
    -- A one-sided row whose twin (same basis, accession and identifier label) is one-sided on the other side, where
    -- the production row's context carries rate facts and no fair value: the rate-only / value-only context pair a
    -- filer's unloaded rate_only_contexts declaration joins.
    select
        f.*
        , exists (
            select 1 from featured t
            where t.basis = f.basis and t.accession = f.accession and t.identifier_label = f.identifier_label
              and t.side <> f.side
              and (case when f.side = 'production_only' then f.fair_value_fact_count = 0 and f.has_rate_fact
                        else t.fair_value_fact_count = 0 and t.has_rate_fact end)
          ) as has_rate_only_twin
    from featured f
)

, early as (
    -- rules that do not need the fund total
    -- Since slice 5 Task 5 this side is the corrected row set, so a context a correction makes a position is on both
    -- sides. A correction left on a production-only row is one this layer loaded and did not use to make the row a
    -- position (rejected, failed or not a promotion route): detail correction_not_promoted (ceiling 0 today).
    -- needs_correction fires only where the correction's field is what this side lacks (final fix wave F2): a fair-value
    -- correction on a row rule 3 left out for no fair-value fact, or a term-field correction on a row held unresolved
    -- for want of a term fact (rule 7 or 9). A row held because it carries two scopes (rule 7) is not held for want of a
    -- term fact, so a term correction does not explain it (slice 3 Task 1, item d). A correction on any other field, or
    -- on a row decided another way, falls through. The cash convention (D7) fires only for a cash row flagged by a
    -- named source, which the detail names: a fund cash rule (cash_rule_id) or a seed cash pattern (cash_pattern_id).
    -- A cash row flagged another way (rule 8, the filed cash axis) falls through.
    select
        *
        , case
            when side = 'production_only' and production_row_added
                then 'needs_store_not_loaded|production_row_added'
            when has_rate_only_twin and filer_has_rate_only_declaration
                then 'needs_store_not_loaded|rate_only_context_pair'
            when side = 'production_only' and has_fair_value_correction
                 and role = 'not_schedule' and role_rule = 3 and fair_value_fact_count = 0
                then 'needs_correction|correction_not_promoted'
            when side = 'production_only' and has_term_correction
                 and role = 'unresolved' and role_rule in (7, 9) and not has_term_fact and not held_for_two_scopes
                then 'needs_correction|correction_not_promoted'
            when side = 'new_only' and is_cash and cash_rule_id is not null
                then 'convention|cash_published_d7_fund_rule'
            when side = 'new_only' and is_cash and cash_pattern_id is not null
                then 'convention|cash_published_d7_seed_pattern'
          end as early_cause
    from paired
)

-- The tie to the filed total. For a fund and date: this layer's published total without cash rows against the filed
-- total investments (stg_fund_financials). A group of production-only unresolved rows with a non-zero fair value is
-- new_wrong when this layer misses the filed total and adding the group's fair value closes the gap, both within
-- var('reconcile_tolerance'). Otherwise such rows are owner_review (D5). Only the published basis has a filed total.
-- Since slice 5 Task 5 this layer's total is the corrected one (int_row_corrected, int_field_corrected fair value).
, new_total as (
    select s.cik, s.report_date, sum(fc.value) as new_fair_value
    from {{ ref('int_row_corrected') }} s
    join {{ ref('int_field_corrected') }} fc
        on fc.accession = s.accession and fc.context_id = s.context_id and fc.field = 'fair_value'
    where s.role = 'position' and s.is_published and not s.is_cash
    group by 1, 2
)

, held_group as (
    select cik, report_date, sum(fair_value) as group_fair_value
    from early
    where early_cause is null and basis = 'published' and side = 'production_only'
      and role = 'unresolved' and fair_value <> 0
    group by 1, 2
)

, tie as (
    select
        g.cik
        , g.report_date
        , abs(t.new_fair_value - f.investments_at_fair_value) > {{ var('reconcile_tolerance') }}
          and abs(t.new_fair_value + g.group_fair_value - f.investments_at_fair_value) <= {{ var('reconcile_tolerance') }}
            as group_closes_gap
    from held_group g
    join new_total t on t.cik = g.cik and t.report_date = g.report_date
    join {{ ref('stg_fund_financials') }} f on f.cik = g.cik and f.report_date = g.report_date
)

, caused as (
    select
        e.basis
        , e.accession
        , e.context_id
        , case
            when e.early_cause is not null then e.early_cause
            when e.side = 'production_only' and e.role = 'unresolved' and e.basis = 'published' and e.fair_value <> 0
                 and coalesce(t.group_closes_gap, false)
                then 'new_wrong|held_unresolved_ties_filed_total'
            when e.side = 'production_only' and e.role = 'unresolved'
                then 'owner_review|held_unresolved_d5'
            when e.has_relabel_correction then 'not_yet_explained|relabel_loaded'
            else 'not_yet_explained|none'
          end as cause_key
    from early e
    left join tie t on t.cik = e.cik and t.report_date = e.report_date
)

select
    j.basis
    , j.accession
    , j.context_id
    , j.cik
    , j.report_date
    , j.side
    , coalesce(rc.role, r.role) as role
    , r.role_rule
    , r.rule_id
    , r.reason
    , coalesce(rc.is_published, r.is_published) as is_published
    , j.row_reason
    , j.row_correction_ids
    , j.production_context_id
    , j.accounting_record_class
    , j.fair_value
    , cf.fair_value as new_fair_value
    , split_part(c.cause_key, '|', 1) as cause
    , nullif(split_part(c.cause_key, '|', 2), '') as cause_detail
from joined j
left join {{ ref('int_source_row') }} r on r.accession = j.accession and r.context_id = j.context_id
left join {{ ref('int_row_corrected') }} rc on rc.accession = j.accession and rc.context_id = j.context_id
left join {{ ref('int_context_feature') }} cf on cf.accession = j.accession and cf.context_id = j.context_id
left join caused c on c.basis = j.basis and c.accession = j.accession and c.context_id = j.context_id
