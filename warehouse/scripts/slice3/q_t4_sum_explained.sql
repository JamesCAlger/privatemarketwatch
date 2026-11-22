-- Slice 3 Task 4: for every fund-quarter where the published normalised fair value misses the filed total, the gap
-- (with and without cash rows) against the cause groups of the two comparisons, published basis: fair-value
-- differences on rows both sides have (cmp_amount, by cause), production-only rows' production fair value
-- (cmp_row_set, by cause) and new-only rows' fair value (cmp_row_set, by cause). The residual is the gap left after
-- the groups that are not this layer's intent (new_wrong reversed, production-only rows added). Values in $m.
with published as (
    select s.cik, s.report_date, sum(n.value) as published_fv
        , coalesce(sum(n.value) filter (where s.is_cash), 0) as cash_fv
    from int_source_row s
    join int_field_normalised n on n.accession = s.accession and n.context_id = s.context_id and n.field = 'fair_value'
    where s.is_published
    group by 1, 2
)
, gaps as (
    select p.*, f.investments_at_fair_value as filed_total
        , p.published_fv - f.investments_at_fair_value as gap
        , p.published_fv - p.cash_fv - f.investments_at_fair_value as gap_ex_cash
    from published p
    left join stg_fund_financials f on f.cik = p.cik and f.report_date = p.report_date
)
, amount_groups as (
    select cik, report_date, cause || '|' || cause_detail as grp, sum(difference) as fv
    from cmp_amount where basis = 'published' and field = 'fair_value' and outcome <> 'equal'
    group by all
)
, row_groups as (
    select cik, report_date, side || ':' || cause || '|' || cause_detail as grp
        , sum(case when side = 'production_only' then fair_value else new_fair_value end) as fv
    from cmp_row_set where basis = 'published' and side <> 'both'
    group by all
)
, groups as (
    select cik, report_date, string_agg(grp || ' ' || cast(round(fv / 1e6, 3) as varchar), '; ' order by grp) as groups_m
    from (select * from amount_groups union all select * from row_groups)
    group by all
)
select g.cik, g.report_date, round(g.filed_total / 1e6, 3) as filed_m, round(g.gap / 1e6, 3) as gap_m
    , round(g.gap_ex_cash / 1e6, 3) as gap_ex_cash_m, gr.groups_m
from gaps g
left join groups gr on gr.cik = g.cik and gr.report_date = g.report_date
where g.filed_total is null or abs(g.gap) > 500000
order by 1, 2
limit 60
