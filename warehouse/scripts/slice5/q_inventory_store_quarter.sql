-- Slice 5 Task 2 inventory: loaded corrections per fund and quarter, one column per store (wrapper entries carry no
-- date: report_date null).
select
    cik
    , report_date
    , count(*) filter (where store = 'row_corrections') as row_corrections
    , count(*) filter (where store = 'row_corrections_by_context') as by_context
    , count(*) filter (where store like 'wrapper:%') as wrapper
    , count(*) filter (where store = 'agent_investigate_rules') as agent_rules
    , count(*) filter (where store = 'agent_b2_corrections') as agent_b2
    , count(*) as total
from main.stg_correction
group by all
order by cik, report_date nulls first
