-- Slice 5 Task 6, consolidation measure (a), part 3: the agent rules loaded for the record (stg_correction_rule: 12
-- investigator row_exclusion rules and the B2 comparative_period_filter) with their scope and predicate, and the
-- agent row_add rules (loaded as add_row corrections, one group per position). Measure only; the classification
-- pinned / dated / all quarters is read from scope_quarters and the predicate text and written in the baseline file.
-- scope_kind: all_quarters when the scope names "all", else dated (one or more quarters named).
-- names_rows: the predicate names rows by a row id, a context id, a list of values, or equality on the identifier or
-- a member text (a heuristic on the text; every row is read by hand in the baseline file).
select
    cik
    , store
    , rule_id
    , rule_type
    , scope_quarters
    , case when scope_quarters ilike '%all%' then 'all_quarters' else 'dated' end as scope_kind
    , regexp_matches(predicate, '(row_id|src_context_id|context_id)', 'i')
      or regexp_matches(predicate, '(bdc_investment_identifier|bdc_dimensions_raw|issuer_name)\s*(=|in\s*\(|like)', 'i')
        as names_rows
    , predicate_form
    , left(regexp_replace(predicate, '\s+', ' ', 'g'), 400) as predicate
from main.stg_correction_rule
union all
select
    cik
    , store
    , min(source_file) as rule_id
    , 'row_add' as rule_type
    , string_agg(distinct cast(report_date as varchar), ';') as scope_quarters
    , 'dated' as scope_kind
    , true as names_rows
    , 'positions' as predicate_form
    , count(distinct add_group_id) || ' positions: ' || string_agg(distinct context_id, ';') as predicate
from main.stg_correction
where kind = 'add_row'
group by cik, store, source_file
order by 1, 2, 3
