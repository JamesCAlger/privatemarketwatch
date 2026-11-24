-- Slice 5 Task 2 inventory: loaded corrections per store, fund, quarter and field (the per-quarter grain the brief
-- asks for). Wrapper entries carry no date (report_date null).
select store, cik, report_date, field, count(*) as corrections
from main.stg_correction
group by all
order by store, cik, report_date nulls first, field
