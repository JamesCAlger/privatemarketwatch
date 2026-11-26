-- Slice P, 2026-11-26: header signatures per fund (filings and tables with each), and the signature set changes
-- between a fund's consecutive filings. Read-only.
with fs as (
    select cik, report_date, accession, list(distinct header_signature order by header_signature) as sigs
    from int_page_column_filing group by all
)
, seq as (
    select *, lag(sigs) over (partition by cik order by report_date) as prev_sigs from fs
)
select 'change' as k, cik, cast(report_date as varchar) as a
    , array_to_string(list_filter(sigs, x -> not list_contains(coalesce(prev_sigs, []), x)), ' , ') as added
    , array_to_string(list_filter(coalesce(prev_sigs, []), x -> not list_contains(sigs, x)), ' , ') as removed
    , null::bigint as n
from seq where prev_sigs is not null and (sigs <> prev_sigs)
union all
select 'sig', cik, header_signature, null, null, count(*)
from int_page_column_filing group by all
union all
select 'filings', cik, null, null, null, count(*) from fs group by all
order by 1, 2, 3
