-- Slice 3 Task 3 fix round 1, item 3: share of net assets per filing: count, sum of absolute values (production's
-- filing-level percent test: 20 or more values summing past 20), and values above 0.50 (production keeps those as
-- already in percent). Filings with any value above 0.50 or a sum above 20 only.
select cik, report_date, accession, count(*) n, sum(abs(value_filed)) total
    , count(*) filter (where value_filed > 0.5) over_half, max(value_filed) mx
from int_field_read
where field = 'pct_of_net_assets' and status = 'read' and value_filed is not null
group by all
having count(*) filter (where value_filed > 0.5) > 0 or sum(abs(value_filed)) > 20
order by 1, 2
limit 60
