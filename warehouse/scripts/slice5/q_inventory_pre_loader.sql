-- Slice 5 Task 2 inventory, run at 8dc29093 before the loader change: loaded corrections per store, kind and fund,
-- with key shape and quarter range, and distinct field names overall (re-measures appendix A1).
select
    store
    , kind
    , cik
    , count(*) as corrections
    , count(*) filter (where context_id is not null) as with_context
    , count(*) filter (where identifier is not null) as with_identifier
    , count(*) filter (where report_date is not null) as with_report_date
    , count(distinct report_date) as quarters
    , min(report_date) as first_quarter
    , max(report_date) as last_quarter
    , count(distinct field) as fields
    , (select count(distinct field) from main.stg_correction) as fields_all_stores
from main.stg_correction
group by all
order by store, kind, cik
