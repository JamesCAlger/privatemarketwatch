-- Slice 5 Task 2 inventory (A1): loaded corrections per store, kind and fund (stg_correction), with key shape.
-- Funds are shown by CIK; the doc maps them to names.
select
    store
    , kind
    , cik
    , count(*) as corrections
    , count(*) filter (where context_id is not null) as with_context
    , count(*) filter (where identifier is not null) as with_identifier
    , count(*) filter (where report_date is not null) as with_report_date
    , count(*) filter (where row_id is not null) as with_row_id
    , count(distinct report_date) as quarters
    , min(report_date) as first_quarter
    , max(report_date) as last_quarter
    , count(distinct field) as fields
from main.stg_correction
group by all
order by store, kind, cik
