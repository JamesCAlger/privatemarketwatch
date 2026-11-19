-- One row per fund and report date, and one for every fund and report date that has a candidate filing.
select cik, report_date, count(*) as n
from {{ ref('int_filing_selected') }}
group by 1, 2
having count(*) > 1
union all
select distinct c.cik, c.report_date, 0 as n
from {{ ref('int_filing_candidate') }} c
anti join {{ ref('int_filing_selected') }} s on s.cik = c.cik and s.report_date = c.report_date
