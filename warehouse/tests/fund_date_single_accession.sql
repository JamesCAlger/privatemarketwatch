-- One filing per fund and report date. Two would double-count the published total.
select cik, report_date, count(distinct accession_number) as accessions
from {{ ref('stg_holdings') }}
group by 1, 2
having count(distinct accession_number) > 1